"""Phase A1: Diagnostic extraction test.

Samples articles from the latest snapshot and tries to extract full body
text via trafilatura. Reports per-bucket FULL / PARTIAL / STUB / NONE / ERROR
breakdown so we know where extraction works.

Output: extraction_test_<date>.md  (per-bucket table + sample dumps)
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

import requests
import trafilatura

ROOT = Path(__file__).parent
SNAPS = ROOT / "snapshots"
FRESH = ROOT / "fresh_pull"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Classification thresholds (chars of extracted body text)
def classify(body: str | None, error: str | None) -> str:
    if error:
        return "ERROR"
    n = len(body or "")
    if n >= 1000: return "FULL"
    if n >= 200:  return "PARTIAL"
    if n >= 50:   return "STUB"
    return "NONE"


def fetch_and_extract(item: dict, timeout: int = 15) -> dict:
    """Fetch URL with browser UA, extract body text via trafilatura."""
    url = item["link"]
    out = {
        "bucket": item["bucket"],
        "feed": item["feed"],
        "title": item["title"][:120],
        "link": url,
        "lang": item.get("lang"),
        "summary_chars": len(item.get("summary") or ""),
        "is_stub_rss": item.get("is_stub", False),
        "is_google_news": item.get("is_google_news", "news.google.com" in url),
        "http_status": None,
        "fetch_ms": None,
        "body_chars": 0,
        "body_first_500": "",
        "error": None,
        "status": None,
        "final_url": None,
    }
    t0 = time.time()
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        out["http_status"] = r.status_code
        out["final_url"] = r.url
        if r.status_code != 200:
            out["error"] = f"HTTP {r.status_code}"
        else:
            # trafilatura will pick out the article body
            body = trafilatura.extract(
                r.text,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
                favor_recall=True,
            )
            if body:
                out["body_chars"] = len(body)
                out["body_first_500"] = body[:500].replace("\n", " ")
    except requests.exceptions.SSLError as e:
        out["error"] = f"SSL: {str(e)[:60]}"
    except requests.exceptions.ConnectionError as e:
        out["error"] = f"CONN: {str(e)[:60]}"
    except requests.exceptions.Timeout:
        out["error"] = "TIMEOUT"
    except Exception as e:
        out["error"] = f"{e.__class__.__name__}: {str(e)[:60]}"
    out["fetch_ms"] = int(1000 * (time.time() - t0))
    out["status"] = classify(out["body_first_500"] if out["body_chars"] else "", out["error"])
    # We capped first_500 above; re-classify on full body length
    out["status"] = classify("x" * out["body_chars"], out["error"])
    return out


def sample_items(snapshot: dict, n_per_bucket: int = 1) -> list[dict]:
    """Pick n_per_bucket items from each bucket, prefer items with real links."""
    items = []
    for ck, cv in snapshot["countries"].items():
        bucket_items = []
        for f in cv.get("feeds", []):
            for it in f.get("items", []):
                if not it.get("link"):
                    continue
                bucket_items.append({
                    **it,
                    "bucket": ck,
                    "feed": f["name"],
                    "lang": f.get("lang"),
                })
        if not bucket_items:
            continue
        random.shuffle(bucket_items)
        items.extend(bucket_items[:n_per_bucket])
    return items


def main():
    # Prefer fresh_pull snapshot (real v0.4 with annotations); fall back to snapshots/
    snap_path = None
    for cand in [FRESH / "2026-05-06.json"] + sorted(SNAPS.glob("[0-9]*.json"), reverse=True):
        if cand.exists() and not cand.stem.endswith(("_convergence", "_similarity",
                                                      "_prompt", "_dedup", "_health",
                                                      "_pull_report")):
            snap_path = cand
            break
    if snap_path is None:
        sys.exit("No snapshot found")
    print(f"Using snapshot: {snap_path}")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))

    random.seed(42)
    samples = sample_items(snap, n_per_bucket=1)
    print(f"Sampled {len(samples)} items (1 per bucket)")

    # Probe in parallel — politely
    print(f"Fetching + extracting (concurrency 12, timeout 15s)...")
    results = []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for r in ex.map(fetch_and_extract, samples):
            results.append(r)
            marker = {"FULL": "✓", "PARTIAL": "·", "STUB": "~", "NONE": "✗", "ERROR": "!"}.get(r["status"], "?")
            print(f"  {marker} [{r['status']:<7}] {r['bucket']:<22}/{r['feed'][:25]:<25} "
                  f"{r['body_chars']:>5}c {r['fetch_ms']:>5}ms  {(r['error'] or '')[:40]}")

    # Aggregate
    by_bucket = defaultdict(Counter)
    overall = Counter()
    for r in results:
        by_bucket[r["bucket"]][r["status"]] += 1
        overall[r["status"]] += 1

    # Build markdown report
    md = [f"# Full-Text Extraction Test — {snap.get('date', '?')}",
          "",
          f"Sampled **{len(results)}** articles (1 per bucket) from `{snap_path.name}`.",
          ""]
    md.append("## Aggregate breakdown")
    md.append("")
    md.append("| Status | Count | % |")
    md.append("|---|---|---|")
    for k in ("FULL", "PARTIAL", "STUB", "NONE", "ERROR"):
        n = overall[k]
        pct = 100 * n / max(1, len(results))
        md.append(f"| {k} | {n} | {pct:.0f}% |")
    md.append("")

    md.append("## Per-bucket detail")
    md.append("")
    md.append("| Bucket | Status | Body chars | Feed | Title | URL host |")
    md.append("|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda r: (r["status"] != "FULL", r["bucket"])):
        host = urlparse(r.get("final_url") or r["link"]).netloc[:25]
        title = r["title"][:60].replace("|", "/")
        md.append(f"| {r['bucket']} | {r['status']} | {r['body_chars']} | {r['feed'][:20]} | {title} | {host} |")
    md.append("")

    # Sample dumps — one of each status from different buckets
    md.append("## Sample bodies (first 500 chars each)")
    md.append("")
    seen_buckets = set()
    for status in ("FULL", "PARTIAL", "STUB", "NONE", "ERROR"):
        md.append(f"### Examples: {status}")
        md.append("")
        examples = [r for r in results if r["status"] == status]
        random.shuffle(examples)
        shown = 0
        for r in examples:
            if r["bucket"] in seen_buckets and status != "FULL":
                continue
            seen_buckets.add(r["bucket"])
            md.append(f"**{r['bucket']} / {r['feed']}** — `{r['link'][:80]}`")
            md.append(f"  - status: {r['status']}, body: {r['body_chars']} chars, http: {r['http_status']}, error: {r['error']}")
            md.append(f"  - title: {r['title']}")
            if r["body_first_500"]:
                md.append(f"  - body[:500]:")
                md.append(f"    > {r['body_first_500'][:500]}")
            md.append("")
            shown += 1
            if shown >= 4:
                break
        md.append("")

    out = ROOT / f"extraction_test_{snap.get('date','sample')}.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport written to {out}")
    print(f"  Aggregate: {dict(overall)}")


if __name__ == "__main__":
    main()
