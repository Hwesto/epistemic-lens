#!/usr/bin/env python3
"""epistemic-lens v0.4: scaled async-style RSS ingestion.

Changes from v0.2:
  - Parallel fetch via ThreadPoolExecutor (default 30 workers)
  - Per-domain rate limiting (>=1.0s between requests to same host)
  - Browser User-Agent + Accept-Language per feed lang
  - Retry with exponential backoff on 5xx / network errors
  - Sitemap-news.xml fallback when feed returns < 3 items
  - Per-item quality flags: summary_chars, is_stub, is_google_news, published_age_hours
  - Per-feed metadata: fetch_ms, http_status, bytes, error, item_count
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

# SSL verification is disabled globally only when explicitly opted in via
# ALLOW_INSECURE_SSL=1. Many international RSS feeds (state media, smaller
# regional outlets) ship expired or self-signed certificates, so the
# production cron sets this to 1 in .github/workflows/daily.yml. Local
# development and CI default to verified SSL so cert problems surface
# clearly. Future work: replace global toggle with a per-feed allowlist
# tracked in feeds.json.
if os.environ.get("ALLOW_INSECURE_SSL") == "1":
    ssl._create_default_https_context = ssl._create_unverified_context
    print("WARN: ALLOW_INSECURE_SSL=1 — TLS certificate verification disabled",
          file=sys.stderr)

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

_STUB_SUMMARY_DIFF = int(meta.INGEST["stub_summary_diff"])
_SITEMAP_FALLBACK_MAX = int(meta.INGEST["sitemap_fallback_max"])
_FETCH_ATTEMPTS = int(meta.INGEST["fetch_attempts"])
_STUB_PCT_MIN = float(meta.HEALTH["stub_pct_min"])
_SLOW_FETCH_MS = int(meta.HEALTH["slow_fetch_ms"])

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")

# Per-host last-fetch timestamps for polite rate limiting
_host_lock = threading.Lock()
_host_last_fetch: dict[str, float] = {}


def _wait_for_host(host: str):
    with _host_lock:
        now = time.time()
        last = _host_last_fetch.get(host, 0)
        wait = max(0.0, (last + PER_HOST_DELAY) - now)
        # Reserve our slot so concurrent callers for the *same* host queue
        # behind us. Sleep happens outside the lock, so threads fetching
        # *other* hosts aren't blocked by our wait.
        _host_last_fetch[host] = now + wait
    if wait > 0:
        time.sleep(wait)


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
        except ValueError:
            # Format didn't match; try the next one.
            continue
    return None


def _http_get(url: str, lang: str, attempts: int | None = None) -> tuple[int, bytes, str | None]:
    """GET with backoff. Returns (status_code|0, body, error|None).

    `attempts` defaults to meta.INGEST.fetch_attempts so the retry budget
    is part of the methodology pin, not a per-call magic number."""
    if attempts is None:
        attempts = _FETCH_ATTEMPTS
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
        except (requests.RequestException, ValueError, OSError) as e:
            # Last-resort: anything else requests can raise (InvalidURL,
            # MissingSchema, ChunkedEncodingError, ContentDecodingError, …)
            last_err = f"{e.__class__.__name__}: {str(e)[:60]}"
            break
    return 0, b"", last_err


def _try_sitemap_fallback(url: str, lang: str) -> list[dict]:
    """If RSS returns fewer than ingest.sitemap_fallback_max items,
    try sitemap-news.xml at the site root."""
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
    except (requests.RequestException, ET.ParseError, ValueError, OSError) as e:
        print(f"  sitemap_fallback: {url} ({e.__class__.__name__}: {str(e)[:60]})",
              file=sys.stderr)
    return []


def _annotate_item(it: dict, now: datetime) -> dict:
    title = re.sub(r"\s+", " ", it.get("title", "")).strip()
    summary = re.sub(r"\s+", " ", it.get("summary", "")).strip()
    link = it.get("link", "")
    pub = _parse_pub(it.get("published", ""))
    is_stub = (not summary) or (
        summary.startswith(title[:60])
        and len(summary) - len(title) < _STUB_SUMMARY_DIFF
    )
    is_gn = "news.google.com" in link
    age_h = round((now - pub).total_seconds() / 3600, 1) if pub else None
    return {
        "title": title,
        "link": link,
        "summary": summary,
        "published": it.get("published", ""),
        "id": hashlib.md5((title + link).encode("utf-8", "ignore")).hexdigest()[:12],
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
    if 0 < len(items) < _SITEMAP_FALLBACK_MAX:
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
    # Stream cosine distance via sklearn's NearestNeighbors-backed DBSCAN
    # instead of materialising a full N×N matrix. Same algorithm + same
    # parameters; memory drops from O(n²) to ~O(n). At N=12k, the previous
    # precomputed matrix was ~1.1 GB.
    labels = DBSCAN(eps=eps, min_samples=min_samples,
                    metric="cosine").fit_predict(vectors)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    print(f"Found {n_clusters} clusters, {list(labels).count(-1)} noise")
    return labels


def compute_convergence(labels, vectors, all_meta):
    rep_bucket = meta.CLUSTERING.get("representative_bucket", "wire_services")
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
        wire = [a for a in articles if a["country"] == rep_bucket]
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
    n_stub = sum(1 for r in rows if r["stub_pct"] >= _STUB_PCT_MIN and r["items"] > 0)
    n_total = sum(r["items"] for r in rows)
    by_bucket = {}
    for r in rows:
        by_bucket.setdefault(r["bucket"], 0)
        by_bucket[r["bucket"]] += r["items"]
    md = ["# Pull Report — " + snapshot["date"], ""]
    md.append(f"- Total feeds: **{len(rows)}**")
    md.append(f"- Total items: **{n_total}**")
    md.append(f"- Errored feeds: **{n_err}**")
    md.append(f"- Stub-only feeds (>={_STUB_PCT_MIN:g}% stubs): **{n_stub}**")
    md.append("")
    md.append("## Items per bucket")
    for b in sorted(by_bucket, key=lambda x: -by_bucket[x]):
        md.append(f"- {b}: {by_bucket[b]}")
    md.append("\n## Errored feeds")
    for r in sorted(rows, key=lambda x: (x["http"] or 0, x["bucket"])):
        if r["error"] or r["http"] != 200:
            md.append(f"- {r['bucket']} / {r['feed']} — http={r['http']} err={r['error']}")
    md.append(f"\n## Slow feeds (>{_SLOW_FETCH_MS / 1000:g}s)")
    for r in sorted(rows, key=lambda x: -x["ms"])[:15]:
        md.append(f"- {r['ms']:>5}ms  {r['bucket']} / {r['feed']}")
    md.append("\n## Stub-only feeds")
    for r in rows:
        if r["stub_pct"] >= _STUB_PCT_MIN and r["items"] > 0:
            md.append(f"- {r['bucket']} / {r['feed']} — stub {r['stub_pct']}%")
    (output_dir / f"{snapshot['date']}_pull_report.md").write_text("\n".join(md))


def _validate_feeds_config(config: dict) -> None:
    """Fail fast on a malformed feeds.json. Without this, a missing 'url'
    or duplicate feed name surfaces as a KeyError mid-fetch."""
    import jsonschema
    schema_path = meta.REPO_ROOT / "docs" / "api" / "schema" / "feeds.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=config, schema=schema)
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        sys.exit(f"feeds.json failed schema validation at {path}: {e.message}")
    # Schema can't express "feed names unique within a bucket"; check here.
    for ckey, cval in config["countries"].items():
        names = [f["name"] for f in cval["feeds"]]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            sys.exit(f"feeds.json: duplicate feed names in bucket '{ckey}': {dupes}")


if __name__ == "__main__":
    print("=" * 60)
    print("EPISTEMIC LENS v0.4")
    print(f"{datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    with open(FEEDS_CONFIG, encoding="utf-8") as f:
        config = json.load(f)
    _validate_feeds_config(config)

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

    write_pull_report(snapshot, out_dir)

    total = sum(sum(f.get("item_count", 0) for f in c["feeds"]) for c in snapshot["countries"].values())
    feeds = sum(len(c["feeds"]) for c in snapshot["countries"].values())
    print(f"\nDone: {feeds} feeds, {total} headlines saved to {out_dir}/{d}*")
    if convergence:
        print(f"Clusters: {len(convergence)}")
