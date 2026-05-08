#!/usr/bin/env python3
"""epistemic-lens v0.4: scaled async-style RSS ingestion.

Changes from v0.2:
  - Parallel fetch via ThreadPoolExecutor (default 30 workers)
  - Per-domain rate limiting (>=1.0s between requests to same host)
  - Browser User-Agent + Accept-Language per feed lang
  - Retry with exponential backoff on 5xx / network errors
  - Sitemap-news.xml fallback when feed returns < 3 items
  - Per-item quality flags: summary_chars, is_stub, is_google_news, published_age_hours
  - Per-feed metadata: fetch_ms, http_status, bytes, error, items_after_dedup
  - Self-sufficient parser (xml.etree) — feedparser optional
  - MAX_ITEMS default 50 (was 10)
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import html
import json
import os
import re
import ssl
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

# Optional ML imports — pipeline still works for fetch-only.
try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import DBSCAN
    from sklearn.metrics.pairwise import cosine_similarity
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

ssl._create_default_https_context = ssl._create_unverified_context

import meta

# Pinned defaults come from meta_version.json; env vars still allow ad-hoc
# override for local debugging (e.g. SKIP_EMBED=1 python ingest.py).
MODEL_NAME = meta.EMBEDDING["model"]
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", str(meta.INGEST["max_items_per_feed"])))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", str(meta.INGEST["max_workers"])))
PER_HOST_DELAY = float(os.environ.get("PER_HOST_DELAY", str(meta.INGEST["per_host_delay_s"])))
TIMEOUT_S = int(os.environ.get("FETCH_TIMEOUT", str(meta.INGEST["fetch_timeout_s"])))
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "snapshots")
FEEDS_CONFIG = os.environ.get("FEEDS_CONFIG", "feeds.json")
SKIP_EMBED = os.environ.get("SKIP_EMBED", "0") == "1"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")

# Per-host last-fetch timestamps for polite rate limiting
_host_lock = threading.Lock()
_host_last_fetch: dict[str, float] = {}


def _wait_for_host(host: str):
    with _host_lock:
        last = _host_last_fetch.get(host, 0)
        wait = (last + PER_HOST_DELAY) - time.time()
        if wait > 0:
            time.sleep(wait)
        _host_last_fetch[host] = time.time()


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_feed(body: bytes, max_n: int = MAX_ITEMS) -> list[dict]:
    """RSS 2.0 / Atom / RDF tolerant parser using xml.etree."""
    if not body:
        return []
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        tag = el.tag.split("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = summary = published = ""
        for child in el:
            ctag = child.tag.split("}", 1)[-1]
            text = (child.text or "").strip()
            if ctag == "title":
                title = _strip_html(text)
            elif ctag == "link":
                link = (child.get("href") or text).strip()
            elif ctag in ("description", "summary"):
                summary = _strip_html(text)
            elif ctag == "encoded" and not summary:
                summary = _strip_html(text)
            elif ctag in ("pubDate", "published", "updated", "date"):
                published = text
        if title:
            out.append({
                "title": title[:300],
                "link": link[:400],
                "summary": summary[:500],
                "published": published[:60],
            })
        if len(out) >= max_n:
            break
    return out


def _parse_pub(s: str):
    if not s:
        return None
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    ]
    s = s.strip().replace("GMT", "+0000").replace("UTC", "+0000")
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None


def _http_get(url: str, lang: str, attempts: int = 3) -> tuple[int, bytes, str | None]:
    """GET with backoff. Returns (status_code|0, body, error|None)."""
    host = urlparse(url).netloc
    headers = {
        "User-Agent": UA,
        "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.5",
        "Accept-Language": f"{lang},en;q=0.5",
    }
    backoff = 2.0
    last_err = None
    for i in range(attempts):
        _wait_for_host(host)
        try:
            r = requests.get(url, headers=headers, timeout=TIMEOUT_S, allow_redirects=True)
            if r.status_code >= 500:
                last_err = f"HTTP {r.status_code}"
                if i < attempts - 1:
                    time.sleep(backoff); backoff *= 2
                    continue
            return r.status_code, r.content, None
        except requests.exceptions.SSLError as e:
            last_err = f"SSL: {str(e)[:80]}"
            break  # don't retry SSL
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_err = f"{e.__class__.__name__}: {str(e)[:60]}"
            if i < attempts - 1:
                time.sleep(backoff); backoff *= 2
                continue
        except Exception as e:
            last_err = f"{e.__class__.__name__}: {str(e)[:60]}"
            break
    return 0, b"", last_err


def _try_sitemap_fallback(url: str, lang: str) -> list[dict]:
    """If RSS returns <3 items, try sitemap-news.xml at the site root."""
    try:
        u = urlparse(url)
        base = f"{u.scheme}://{u.netloc}"
        for path in ("/sitemap-news.xml", "/news-sitemap.xml", "/sitemap_news.xml"):
            status, body, _ = _http_get(base + path, lang, attempts=1)
            if status == 200 and body:
                # Parse as sitemap — <url><news:news><news:title>...
                items = []
                try:
                    root = ET.fromstring(body)
                except ET.ParseError:
                    continue
                for u_el in root.iter():
                    if u_el.tag.split("}", 1)[-1] != "url":
                        continue
                    loc = ""
                    title = ""
                    pub = ""
                    for c in u_el.iter():
                        t = c.tag.split("}", 1)[-1]
                        if t == "loc" and not loc:
                            loc = (c.text or "").strip()
                        elif t == "title":
                            title = _strip_html(c.text or "")
                        elif t == "publication_date":
                            pub = (c.text or "").strip()
                    if title:
                        items.append({"title": title[:300], "link": loc[:400],
                                      "summary": "", "published": pub[:60]})
                    if len(items) >= MAX_ITEMS:
                        break
                if items:
                    return items
    except Exception:
        pass
    return []


def _annotate_item(it: dict, now: datetime) -> dict:
    title = re.sub(r"\s+", " ", it.get("title", "")).strip()
    summary = re.sub(r"\s+", " ", it.get("summary", "")).strip()
    link = it.get("link", "")
    pub = _parse_pub(it.get("published", ""))
    is_stub = (not summary) or (
        summary.startswith(title[:60]) and len(summary) - len(title) < 40
    )
    is_gn = "news.google.com" in link
    age_h = round((now - pub).total_seconds() / 3600, 1) if pub else None
    return {
        "title": title,
        "link": link,
        "summary": summary,
        "published": it.get("published", ""),
        "id": hashlib.md5((title + link).encode("utf-8", "ignore")).hexdigest()[:8],
        "summary_chars": len(summary),
        "is_stub": is_stub,
        "is_google_news": is_gn,
        "published_age_hours": age_h,
        "_embed_text": f"{title}. {summary}" if summary and not is_stub else title,
    }


def pull_feed(feed_info: dict) -> dict:
    """Fetch one feed with retries, parsing, fallback, and annotation."""
    t0 = time.time()
    url = feed_info["url"]
    lang = feed_info.get("lang", "en")
    status, body, err = _http_get(url, lang)
    bytes_n = len(body)
    items = _parse_feed(body) if status == 200 else []
    if 0 < len(items) < 3:
        # Thin RSS — try sitemap fallback for more content
        more = _try_sitemap_fallback(url, lang)
        # Merge by title to avoid dupes
        seen = {i["title"] for i in items}
        for m in more:
            if m["title"] not in seen:
                items.append(m)
                seen.add(m["title"])

    now = datetime.now(timezone.utc)
    annotated = [_annotate_item(i, now) for i in items]

    return {
        "name": feed_info["name"],
        "lang": lang,
        "lean": feed_info.get("lean", ""),
        "declared_status": feed_info.get("status", ""),
        "fetch_ms": int(1000 * (time.time() - t0)),
        "http_status": status if status else None,
        "bytes": bytes_n,
        "error": err,
        "item_count": len(annotated),
        "items": annotated,
    }


def pull_all(config: dict) -> dict:
    """Parallel fetch of all feeds. Returns snapshot dict."""
    now = datetime.now(timezone.utc)
    snapshot = meta.stamp({
        "pulled_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "config_version": config.get("meta", {}).get("version", "?"),
        "max_items": MAX_ITEMS,
        "countries": {},
    })
    # Initialise buckets to preserve order
    for ckey, cval in config["countries"].items():
        snapshot["countries"][ckey] = {"label": cval["label"], "feeds": []}

    # Build flat work list
    jobs = []
    for ckey, cval in config["countries"].items():
        for f in cval["feeds"]:
            jobs.append((ckey, f))

    print(f"Pulling {len(jobs)} feeds across {len(config['countries'])} buckets "
          f"(workers={MAX_WORKERS}, per-host {PER_HOST_DELAY}s)")

    t_start = time.time()
    results: dict[tuple[str, str], dict] = {}

    def _do(job):
        ckey, finfo = job
        return ckey, finfo, pull_feed(finfo)

    done = 0
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for ckey, finfo, res in ex.map(_do, jobs):
            results[(ckey, finfo["name"])] = res
            done += 1
            if done % 20 == 0 or done == len(jobs):
                print(f"  ...{done}/{len(jobs)} feeds done")

    # Reattach in declared order
    for ckey, cval in config["countries"].items():
        for f in cval["feeds"]:
            res = results[(ckey, f["name"])]
            snapshot["countries"][ckey]["feeds"].append(res)

    elapsed = time.time() - t_start
    total_items = sum(r["item_count"] for r in results.values())
    n_err = sum(1 for r in results.values() if r["error"] or r["http_status"] != 200)
    print(f"Pull complete in {elapsed:.1f}s — {total_items} items, "
          f"{n_err} feed errors")
    return snapshot


# ---------------------------------------------------------------------------
# Embed / cluster (unchanged from v0.2 except for skipping stubs)
# ---------------------------------------------------------------------------
def embed_snapshot(snapshot, model):
    all_texts, all_meta = [], []
    for ckey, cdata in snapshot["countries"].items():
        for feed in cdata["feeds"]:
            for item in feed.get("items", []):
                txt = item.get("_embed_text") or item["title"]
                all_texts.append(txt)
                all_meta.append({
                    "country": ckey, "country_label": cdata["label"],
                    "feed": feed["name"], "lang": feed.get("lang", "en"),
                    "lean": feed.get("lean", ""), "title": item["title"],
                    "id": item["id"],
                })
    if not all_texts:
        return None
    print(f"Embedding {len(all_texts)} headlines...")
    vectors = model.encode(all_texts, show_progress_bar=False, batch_size=64)
    return vectors, all_meta


def cluster_topics(vectors,
                   eps: float | None = None,
                   min_samples: int | None = None):
    if eps is None:
        eps = float(meta.CLUSTERING["eps"])
    if min_samples is None:
        min_samples = int(meta.CLUSTERING["min_samples"])
    dist = 1 - cosine_similarity(vectors)
    dist = np.maximum(dist, 0)
    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="precomputed").fit_predict(dist)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    print(f"Found {n_clusters} clusters, {list(labels).count(-1)} noise")
    return labels


def compute_convergence(labels, vectors, all_meta):
    clusters = {}
    for idx, label in enumerate(labels):
        if label == -1:
            continue
        clusters.setdefault(label, []).append({**all_meta[idx], "vector_idx": idx})
    results = []
    for label, articles in clusters.items():
        idxs = [a["vector_idx"] for a in articles]
        cluster_vecs = vectors[idxs]
        mean_sim = float(np.mean(cosine_similarity(cluster_vecs)))
        countries = set(a["country"] for a in articles)
        wire = [a for a in articles if a["country"] == "wire_services"]
        rep = wire[0]["title"] if wire else articles[0]["title"]
        results.append({
            "cluster_id": int(label), "representative_title": rep,
            "article_count": len(articles), "country_count": len(countries),
            "countries_present": list(countries),
            "feeds_present": list(set(a["feed"] for a in articles)),
            "mean_similarity": round(mean_sim, 3),
            "articles": [{"feed": a["feed"], "country": a["country_label"],
                          "lang": a["lang"], "title": a["title"]}
                         for a in articles],
        })
    results.sort(key=lambda x: x["country_count"], reverse=True)
    return results


def compute_similarity_matrix(vectors, all_meta):
    feed_vecs = {}
    for idx, m in enumerate(all_meta):
        key = f"{m['country_label']} | {m['feed']}"
        feed_vecs.setdefault(key, []).append(vectors[idx])
    names = sorted(feed_vecs.keys())
    centroids = np.array([np.mean(feed_vecs[k], axis=0) for k in names])
    sim = cosine_similarity(centroids)
    return {"feeds": names, "matrix": [[round(float(v), 3) for v in row] for row in sim]}


def generate_prompt(snapshot, convergence, similarity):
    date = snapshot["date"]
    lines = [f"# Epistemic Lens - {date}\n"]
    lines.append("## HEADLINES BY COUNTRY\n")
    for cdata in snapshot["countries"].values():
        lines.append(f"### {cdata['label']}")
        for feed in cdata["feeds"]:
            lines.append(f"**{feed['name']}** ({feed.get('lang','en')}) - {feed.get('lean','')}")
            for item in feed.get("items", [])[:7]:
                lines.append(f"- {item['title']}")
            lines.append("")
    if convergence:
        lines.append("## SHARED STORIES (auto-detected cross-lingual clusters)\n")
        for c in convergence[:10]:
            lines.append(f"### {c['representative_title']}")
            lines.append(f"{c['country_count']} countries, {c['article_count']} articles, similarity: {c['mean_similarity']}")
            for a in c["articles"]:
                lines.append(f"  - [{a['lang']}] {a['feed']}: {a['title']}")
            lines.append("")
    if similarity:
        lines.append("## NEWSPAPER SIMILARITY (top pairs)\n")
        feeds = similarity["feeds"]
        pairs = []
        for i in range(len(feeds)):
            for j in range(i + 1, len(feeds)):
                pairs.append((feeds[i], feeds[j], similarity["matrix"][i][j]))
        pairs.sort(key=lambda x: x[2], reverse=True)
        lines.append("Most similar (echo chambers):")
        for a, b, s in pairs[:10]:
            lines.append(f"  {s:.3f} | {a} <-> {b}")
        lines.append("\nMost different (epistemic gaps):")
        pairs.sort(key=lambda x: x[2])
        for a, b, s in pairs[:10]:
            lines.append(f"  {s:.3f} | {a} <-> {b}")
    lines.extend([
        "\n## ANALYSIS TASK",
        "1. For shared stories: how does each outlet frame it?",
        "2. What does each outlet CALL the event?",
        "3. Which countries ABSENT from major stories?",
        "4. Claims converging across adversarial sources = likely facts",
        "5. Claims in only one bloc = likely spin",
        "6. Any outlet behaving unusually?",
        "7. Produce: Claim | Sources agree | Sources contradict | Confidence",
    ])
    return "\n".join(lines)


def write_pull_report(snapshot: dict, output_dir: Path):
    """Per-day operational report — feeds with errors, stubs, slow fetches."""
    rows = []
    for ckey, cval in snapshot["countries"].items():
        for f in cval["feeds"]:
            stub_pct = (sum(1 for i in f["items"] if i.get("is_stub")) /
                        max(1, len(f["items"]))) * 100
            rows.append({
                "bucket": ckey, "feed": f["name"],
                "items": f["item_count"], "http": f["http_status"],
                "ms": f["fetch_ms"], "bytes": f["bytes"],
                "stub_pct": round(stub_pct, 1), "error": f["error"],
            })
    n_err = sum(1 for r in rows if r["error"] or r["http"] != 200)
    n_stub = sum(1 for r in rows if r["stub_pct"] >= 80 and r["items"] > 0)
    n_total = sum(r["items"] for r in rows)
    by_bucket = {}
    for r in rows:
        by_bucket.setdefault(r["bucket"], 0)
        by_bucket[r["bucket"]] += r["items"]
    md = ["# Pull Report — " + snapshot["date"], ""]
    md.append(f"- Total feeds: **{len(rows)}**")
    md.append(f"- Total items: **{n_total}**")
    md.append(f"- Errored feeds: **{n_err}**")
    md.append(f"- Stub-only feeds (>=80% stubs): **{n_stub}**")
    md.append("")
    md.append("## Items per bucket")
    for b in sorted(by_bucket, key=lambda x: -by_bucket[x]):
        md.append(f"- {b}: {by_bucket[b]}")
    md.append("\n## Errored feeds")
    for r in sorted(rows, key=lambda x: (x["http"] or 0, x["bucket"])):
        if r["error"] or r["http"] != 200:
            md.append(f"- {r['bucket']} / {r['feed']} — http={r['http']} err={r['error']}")
    md.append("\n## Slow feeds (>5s)")
    for r in sorted(rows, key=lambda x: -x["ms"])[:15]:
        md.append(f"- {r['ms']:>5}ms  {r['bucket']} / {r['feed']}")
    md.append("\n## Stub-only feeds")
    for r in rows:
        if r["stub_pct"] >= 80 and r["items"] > 0:
            md.append(f"- {r['bucket']} / {r['feed']} — stub {r['stub_pct']}%")
    (output_dir / f"{snapshot['date']}_pull_report.md").write_text("\n".join(md))


if __name__ == "__main__":
    print("=" * 60)
    print("EPISTEMIC LENS v0.4")
    print(f"{datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    with open(FEEDS_CONFIG, encoding="utf-8") as f:
        config = json.load(f)

    snapshot = pull_all(config)
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    convergence, similarity = None, None
    if not SKIP_EMBED and ML_AVAILABLE:
        print(f"\nLoading {MODEL_NAME}...")
        model = SentenceTransformer(MODEL_NAME)
        result = embed_snapshot(snapshot, model)
        if result:
            vectors, all_meta = result
            labels = cluster_topics(vectors)
            convergence = compute_convergence(labels, vectors, all_meta)
            similarity = compute_similarity_matrix(vectors, all_meta)
    elif SKIP_EMBED:
        print("SKIP_EMBED=1 — skipping embedding/clustering.")
    else:
        print("ML deps missing (sentence-transformers/sklearn) — skipping embed.")

    # Strip _embed_text before persisting
    for c in snapshot["countries"].values():
        for f in c["feeds"]:
            for item in f.get("items", []):
                item.pop("_embed_text", None)

    d = snapshot["date"]
    for name, data in [("", snapshot), ("_convergence", convergence), ("_similarity", similarity)]:
        if data is not None:
            (out_dir / f"{d}{name}.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False)
            )

    if convergence and similarity:
        prompt = generate_prompt(snapshot, convergence, similarity)
        (out_dir / f"{d}_prompt.md").write_text(prompt)

    write_pull_report(snapshot, out_dir)

    total = sum(sum(f.get("item_count", 0) for f in c["feeds"]) for c in snapshot["countries"].values())
    feeds = sum(len(c["feeds"]) for c in snapshot["countries"].values())
    print(f"\nDone: {feeds} feeds, {total} headlines saved to {out_dir}/{d}*")
    if convergence:
        print(f"Clusters: {len(convergence)}")
