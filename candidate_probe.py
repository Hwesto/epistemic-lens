"""Phase 2: probe each candidate feed once, score content quality, decide.

Output:
  review/probe_results.json   raw probe data + scoring
  review/<bucket>__<slug>.md  per-feed review card with samples + flags
  review/decisions.tsv        bucket\tname\turl\tdecision\treason

Auto-decision rules (acting as the human reviewer):
  ACCEPT   if status==200 AND items>=3 AND has_real_summary AND not_stale
  RETRY    if status in (403, 429) — likely UA-blocked; keep, may work from prod IP
  REJECT   if dead, unreachable, returns HTML page, or is_stub on >80% items
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).parent
CANDS = json.loads((ROOT / "candidates.json").read_text(encoding="utf-8"))
REVIEW = ROOT / "review"
REVIEW.mkdir(exist_ok=True)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.5"}

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
}

def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()

def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s[:60]

def parse_feed_items(body: bytes, max_n: int = 10):
    """Tolerant parser — RSS 2.0, RDF/RSS 1.0, Atom. Returns list of dicts."""
    try:
        # Strip XML declaration BOM if present
        if body.startswith(b"\xef\xbb\xbf"):
            body = body[3:]
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    items = []
    # RSS 2.0: <channel><item>
    for item in root.iter():
        tag = item.tag.split("}", 1)[-1]
        if tag != "item" and tag != "entry":
            continue
        title = ""
        link = ""
        summary = ""
        published = ""
        for child in item:
            ctag = child.tag.split("}", 1)[-1]
            text = (child.text or "").strip()
            if ctag == "title":
                title = strip_html(text)
            elif ctag == "link":
                href = child.get("href")
                link = href or text
            elif ctag in ("description", "summary"):
                summary = strip_html(text)
            elif ctag == "encoded":
                summary = strip_html(text) if not summary else summary
            elif ctag in ("pubDate", "published", "updated", "date"):
                published = text
        if title:
            items.append({
                "title": title[:200],
                "link": link[:300],
                "summary": summary[:500],
                "published": published[:50],
            })
        if len(items) >= max_n:
            break
    return items

def parse_published(s: str):
    if not s:
        return None
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
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

def probe(payload):
    bucket, feed = payload
    url = feed["url"]
    out = {
        "bucket": bucket, "name": feed["name"], "url": url,
        "lang_declared": feed.get("lang"), "lean": feed.get("lean", ""),
        "status": None, "ctype": None, "bytes": 0, "elapsed_s": None,
        "items": [], "items_count": 0, "error": None,
        "summary_avg_chars": 0, "stub_pct": 0, "is_google_news": False,
        "freshness_hours": None, "newest_published": None,
        "decision": None, "reason": None,
    }
    t0 = time.time()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        out["status"] = r.status_code
        out["ctype"] = (r.headers.get("content-type") or "")[:80]
        out["bytes"] = len(r.content)
        if r.status_code == 200 and r.content:
            items = parse_feed_items(r.content, max_n=10)
            out["items_count"] = len(items)
            out["items"] = items
            if items:
                lens = [len(i["summary"]) for i in items]
                out["summary_avg_chars"] = round(sum(lens) / len(lens), 1)
                # stub detection: summary close to title length
                stubs = 0
                for i in items:
                    s = re.sub(r"\s+", " ", i["summary"]).strip()
                    t = re.sub(r"\s+", " ", i["title"]).strip()
                    if not s:
                        stubs += 1
                    elif s.startswith(t[:60]) and len(s) - len(t) < 40:
                        stubs += 1
                out["stub_pct"] = round(100 * stubs / len(items), 1)
                # GN detection
                gn = sum(1 for i in items if "news.google.com" in i["link"])
                out["is_google_news"] = gn >= len(items) // 2
                # freshness — newest published age
                ages = []
                for i in items:
                    dt = parse_published(i["published"])
                    if dt:
                        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                        ages.append(age)
                if ages:
                    newest = min(ages)
                    out["freshness_hours"] = round(newest, 1)
                    out["newest_published"] = items[ages.index(newest)]["published"]
    except requests.exceptions.SSLError as e:
        out["error"] = f"SSL: {str(e)[:80]}"
    except requests.exceptions.ConnectionError as e:
        out["error"] = f"CONN: {str(e)[:80]}"
    except requests.exceptions.Timeout:
        out["error"] = "TIMEOUT"
    except Exception as e:
        out["error"] = f"{e.__class__.__name__}: {str(e)[:80]}"
    out["elapsed_s"] = round(time.time() - t0, 2)

    # Auto-decision
    if out["status"] == 200 and out["items_count"] >= 3:
        if out["stub_pct"] >= 80 and not out["is_google_news"]:
            # title-only feeds — keep but flag
            out["decision"] = "ACCEPT_STUB"
            out["reason"] = f"stub_pct={out['stub_pct']}% — titles only, no body"
        elif out["freshness_hours"] is not None and out["freshness_hours"] > 24*14:
            out["decision"] = "REJECT"
            out["reason"] = f"stale: newest item {out['freshness_hours']:.0f}h old"
        else:
            out["decision"] = "ACCEPT"
            out["reason"] = (
                f"items={out['items_count']}, "
                f"avg_summary={out['summary_avg_chars']}c, "
                f"stub={out['stub_pct']}%, "
                f"fresh={out['freshness_hours']}h"
            )
    elif out["status"] in (403, 429):
        out["decision"] = "RETRY_FROM_PROD"
        out["reason"] = f"{out['status']} from container — likely UA/IP block, may work from prod"
    elif out["status"] == 200 and out["items_count"] == 0:
        out["decision"] = "REJECT"
        out["reason"] = "200 but no parseable items (likely HTML page)"
    else:
        out["decision"] = "REJECT"
        out["reason"] = out["error"] or f"http {out['status']}"
    return out

# Flatten and probe in parallel
flat = []
for bucket, cv in CANDS["countries"].items():
    for f in cv["feeds"]:
        flat.append((bucket, f))

print(f"Probing {len(flat)} candidates (concurrency 20, timeout 15s)...")
results = []
with cf.ThreadPoolExecutor(max_workers=20) as ex:
    for r in ex.map(probe, flat):
        results.append(r)
        marker = {"ACCEPT": "+", "ACCEPT_STUB": "~", "RETRY_FROM_PROD": "?", "REJECT": "-"}.get(r["decision"], " ")
        print(f"  {marker} [{r['decision']:<16}] {r['bucket']}/{r['name']:<38} {str(r['status'] or '-'):<4} items={r['items_count']:>2}  {r['reason'][:50]}")

# Persist machine-readable + decisions
(REVIEW / "probe_results.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False)
)

# Decisions TSV
with (REVIEW / "decisions.tsv").open("w", encoding="utf-8") as f:
    f.write("decision\tbucket\tname\turl\tstatus\titems\tstub_pct\tfreshness_h\treason\n")
    for r in sorted(results, key=lambda x: (x["decision"], x["bucket"], x["name"])):
        f.write("\t".join([
            r["decision"] or "",
            r["bucket"], r["name"], r["url"],
            str(r["status"] or ""), str(r["items_count"]),
            str(r["stub_pct"]), str(r["freshness_hours"] or ""),
            (r["reason"] or "")[:120],
        ]) + "\n")

# Per-feed review cards (only ACCEPT and RETRY_FROM_PROD; rejects don't get cards)
for r in results:
    if r["decision"] == "REJECT":
        continue
    fname = f"{r['bucket']}__{slug(r['name'])}.md"
    p = REVIEW / fname
    md = []
    md.append(f"# {r['bucket']} / {r['name']}")
    md.append("")
    md.append(f"- URL: <{r['url']}>")
    md.append(f"- Decision: **{r['decision']}** — {r['reason']}")
    md.append(f"- Lang declared: `{r['lang_declared']}`  Lean: {r['lean']}")
    md.append(f"- Status: {r['status']}  Items: {r['items_count']}  Bytes: {r['bytes']}")
    md.append(f"- Summary avg: {r['summary_avg_chars']} chars  Stub: {r['stub_pct']}%  GN: {r['is_google_news']}")
    md.append(f"- Newest: {r['newest_published']}  ({r['freshness_hours']}h old)")
    md.append("")
    md.append("## Sample items")
    for i, it in enumerate(r["items"][:5], 1):
        md.append(f"\n**{i}.** {it['title']}")
        md.append(f"  - link: {it['link'][:100]}")
        md.append(f"  - published: {it['published']}")
        if it["summary"]:
            md.append(f"  - summary ({len(it['summary'])}c): {it['summary'][:300]}")
    p.write_text("\n".join(md), encoding="utf-8")

# Summary
counts = {}
for r in results:
    counts[r["decision"]] = counts.get(r["decision"], 0) + 1
print()
print(f"Probed {len(results)} candidates:")
for d, n in sorted(counts.items()):
    print(f"  {d:<18} {n}")
print()
print(f"Decisions written to review/decisions.tsv")
print(f"Cards written to review/<bucket>__<slug>.md")
