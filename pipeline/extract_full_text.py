#!/usr/bin/env python3
"""epistemic-lens A2: production full-text extractor.

Runs after ingest.py. For each item with a link in the snapshot, fetches
the article HTML, runs trafilatura body extraction, and annotates the
item with body fields. Idempotent — items already extracted are skipped.

Default behaviour: extract only items belonging to the top-K clusters
(by country_count) from the convergence file. This keeps daily extraction
budget at ~5-10 minutes / ~$0 in API costs since we only extract ~300
articles instead of all 12,000.

If --top-clusters=0 or no convergence file exists, extracts all items.

Per-item annotations added:
  body_text          first MAX_BODY_CHARS chars of extracted body
  body_chars         full length of extracted body (pre-truncation)
  extraction_status  FULL | PARTIAL | STUB | NONE | ERROR | SKIPPED
  extraction_ms      ms spent fetching + extracting
  extraction_http    HTTP status of the article fetch
  extraction_final_url  final URL after redirects (for GN URLs especially)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

import meta

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    trafilatura = None
    HAS_TRAFILATURA = False

ROOT = meta.REPO_ROOT
SNAPS_DEFAULT = ROOT / "snapshots"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Per-host throttle (same pattern as ingest.py)
_host_lock = threading.Lock()
_host_last_fetch: dict[str, float] = {}


def _wait_for_host(host: str, delay: float):
    with _host_lock:
        last = _host_last_fetch.get(host, 0)
        wait = (last + delay) - time.time()
        if wait > 0:
            time.sleep(wait)
        _host_last_fetch[host] = time.time()


_BODY_FULL_MIN = int(meta.EXTRACTION["body_full_min"])
_BODY_PARTIAL_MIN = int(meta.EXTRACTION["body_partial_min"])
_BODY_STUB_MIN = int(meta.EXTRACTION["body_stub_min"])


def classify(body_chars: int, error: str | None) -> str:
    if error:
        return "ERROR"
    if body_chars >= _BODY_FULL_MIN: return "FULL"
    if body_chars >= _BODY_PARTIAL_MIN: return "PARTIAL"
    if body_chars >= _BODY_STUB_MIN: return "STUB"
    return "NONE"


def _try_wayback(url: str, timeout: int = 12) -> tuple[int | None, str, str]:
    """Try to fetch the article via Wayback Machine when direct fetch failed.
    Returns (http_status, final_url, body_text). body_text is empty on failure.
    """
    # Wayback's "newest available capture" redirect endpoint. The year
    # segment biases toward recent captures; use current UTC year so this
    # keeps working past 2026.
    wb_url = f"https://web.archive.org/web/{datetime.now(timezone.utc).year}/{url}"
    try:
        r = requests.get(wb_url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and r.content:
            body = trafilatura.extract(r.text, include_comments=False,
                                       include_tables=False, favor_recall=True) or ""
            return r.status_code, r.url, body
        return r.status_code, r.url, ""
    except Exception:
        return None, "", ""


def extract_one(item: dict, max_body: int = 4000, timeout: int = 15,
                attempts: int = 2, per_host_delay: float = 1.0,
                use_wayback_fallback: bool = True) -> dict:
    """Fetch + extract a single article. Returns dict with annotations."""
    url = item.get("link") or ""
    out = {
        "extraction_status": "NONE",
        "extraction_ms": 0,
        "extraction_http": None,
        "extraction_final_url": None,
        "extraction_via_wayback": False,
        "body_chars": 0,
        "body_text": "",
        "extraction_error": None,
    }
    if not url:
        out["extraction_status"] = "SKIPPED"
        out["extraction_error"] = "no link"
        return out

    host = urlparse(url).netloc
    t0 = time.time()
    last_err = None
    for i in range(attempts):
        _wait_for_host(host, per_host_delay)
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            out["extraction_http"] = r.status_code
            out["extraction_final_url"] = r.url
            if r.status_code >= 500 and i < attempts - 1:
                time.sleep(2 ** i)
                continue
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                break
            body = trafilatura.extract(r.text, include_comments=False,
                                       include_tables=False, favor_recall=True) or ""
            out["body_chars"] = len(body)
            out["body_text"] = body[:max_body]
            last_err = None
            break
        except requests.exceptions.SSLError as e:
            last_err = f"SSL: {str(e)[:60]}"
            break
        except requests.exceptions.ConnectionError as e:
            last_err = f"CONN: {str(e)[:60]}"
            if i < attempts - 1:
                time.sleep(2 ** i)
                continue
        except requests.exceptions.Timeout:
            last_err = "TIMEOUT"
            if i < attempts - 1:
                time.sleep(2 ** i)
                continue
        except Exception as e:
            last_err = f"{e.__class__.__name__}: {str(e)[:60]}"
            break

    # Wayback fallback when direct fetch returned 4xx (anti-bot/paywall)
    # or when extraction yielded too-thin a body.
    if (use_wayback_fallback
        and out["body_chars"] < 200
        and out["extraction_http"] in (None, 400, 401, 403, 404, 429)):
        wb_status, wb_url, wb_body = _try_wayback(url, timeout=timeout)
        if wb_body and len(wb_body) > out["body_chars"]:
            out["body_text"] = wb_body[:max_body]
            out["body_chars"] = len(wb_body)
            out["extraction_final_url"] = wb_url
            out["extraction_via_wayback"] = True
            last_err = None  # success via fallback

    out["extraction_ms"] = int(1000 * (time.time() - t0))
    out["extraction_error"] = last_err
    out["extraction_status"] = classify(out["body_chars"], last_err)
    return out


def signal_text(item: dict, prefer_body: bool = True,
                max_chars: int | None = None) -> tuple[str, str]:
    """Best-available text for framing analysis.

    Returns (signal_level, text) where signal_level is one of:
      'body'    — full article body (>= meta.SIGNAL_TEXT.min_body_chars_for_body)
      'summary' — RSS summary (>= meta.SIGNAL_TEXT.min_summary_chars_for_summary),
                  prepended with title
      'title'   — title only (last-resort)
      'empty'   — nothing usable

    Thresholds are pinned by meta_version.json so vocabulary metrics computed
    today are comparable to those computed last week. Bumping a threshold is
    a major-version change.
    """
    cfg = meta.SIGNAL_TEXT
    if max_chars is None:
        max_chars = int(cfg["max_chars"])
    min_body = int(cfg["min_body_chars_for_body"])
    min_summary = int(cfg["min_summary_chars_for_summary"])
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    body = (item.get("body_text") or "").strip()
    if prefer_body and body and len(body) >= min_body:
        return ("body", body[:max_chars])
    if summary and len(summary) >= min_summary:
        head = title + "\n\n" if title else ""
        return ("summary", (head + summary)[:max_chars])
    if title:
        return ("title", title[:max_chars])
    return ("empty", "")


def select_items(snap: dict, conv: list | None, top_clusters: int,
                 max_per_feed: int = 0) -> list[tuple]:
    """Return list of (country_key, feed_name, item_dict) to extract.

    Selection rule (UNION of the two strategies):
      An item is selected if EITHER
        (a) it appears in one of the top-N convergence clusters, OR
        (b) it is one of the first `max_per_feed` items in its feed.
    Plus:
      - Skip items with no link.
      - Skip items already extracted (idempotent).

    If both top_clusters=0 and max_per_feed=0, selects everything.
    """
    # Build cluster-target set
    cluster_ids: set[str] = set()
    if top_clusters > 0 and conv:
        for cl in sorted(conv, key=lambda c: -c.get("country_count", 0))[:top_clusters]:
            for art in cl.get("articles", []):
                if art.get("id"):
                    cluster_ids.add(art["id"])

    # Selection
    use_any_filter = (top_clusters > 0 and conv) or (max_per_feed > 0)
    out = []
    for ck, cv in snap["countries"].items():
        for f in cv.get("feeds", []):
            kept_per_feed_count = 0
            for it in f.get("items", []):
                if not it.get("link"):
                    continue
                # Idempotent: skip items already classified into a terminal
                # state. ERROR and NONE are retried on the next run.
                if it.get("extraction_status") in ("FULL", "PARTIAL", "STUB", "SKIPPED"):
                    continue

                # Cluster membership
                in_cluster = it.get("id") in cluster_ids
                # Per-feed quota
                in_per_feed_quota = (max_per_feed > 0 and kept_per_feed_count < max_per_feed)

                if use_any_filter:
                    if not (in_cluster or in_per_feed_quota):
                        continue
                # else: no filters, take everything

                out.append((ck, f["name"], it))
                if in_per_feed_quota and not in_cluster:
                    # Only consume per-feed quota for items kept solely on that basis
                    kept_per_feed_count += 1
                elif in_per_feed_quota:
                    # Item also in cluster — still counts toward per-feed quota
                    kept_per_feed_count += 1
    # Dedupe (an item could match both rules but is only added once above)
    return out


def main():
    if not HAS_TRAFILATURA:
        sys.exit("trafilatura not installed — pip install trafilatura")
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None,
                    help="Path to snapshot.json (default: latest under snapshots/)")
    ap.add_argument("--top-clusters", type=int,
                    default=int(os.environ.get("TOP_CLUSTERS", str(meta.EXTRACTION["top_clusters"]))),
                    help="Extract items only in top-N clusters (0 = all items)")
    ap.add_argument("--max-body-chars", type=int,
                    default=int(os.environ.get("MAX_BODY_CHARS", str(meta.EXTRACTION["max_body_chars"]))),
                    help="Cap on body_text storage per item")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("EXTRACT_WORKERS", "20")))
    ap.add_argument("--per-host-delay", type=float, default=float(os.environ.get("PER_HOST_DELAY", "1.0")))
    ap.add_argument("--timeout", type=int,
                    default=int(os.environ.get("EXTRACT_TIMEOUT", str(meta.EXTRACTION["extract_timeout_s"]))))
    ap.add_argument("--snapshots-dir", default=str(SNAPS_DEFAULT))
    ap.add_argument("--max-per-feed", type=int,
                    default=int(os.environ.get("MAX_PER_FEED", str(meta.EXTRACTION["max_per_feed"]))),
                    help="Cap items extracted per (bucket, feed). 0 = no cap. "
                         "Use ~3 in production hybrid mode to guarantee per-country "
                         "coverage on top of cluster-based extraction.")
    ap.add_argument("--checkpoint-every", type=int, default=200,
                    help="Save snapshot to disk every N completed items so partial progress isn't lost on interruption.")
    args = ap.parse_args()

    snaps_dir = Path(args.snapshots_dir)

    # Resolve snapshot path
    if args.snapshot:
        snap_path = Path(args.snapshot)
    else:
        cands = sorted(p for p in snaps_dir.glob("[0-9]*.json")
                       if not p.stem.endswith(("_convergence", "_similarity",
                                                "_prompt", "_dedup", "_health",
                                                "_pull_report", "_baseline")))
        if not cands:
            sys.exit(f"No snapshot found in {snaps_dir}")
        snap_path = cands[-1]
    print(f"Snapshot: {snap_path}")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))

    # Try to load convergence file for top-cluster filtering
    conv = None
    conv_path = snap_path.with_name(snap_path.stem + "_convergence.json")
    if conv_path.exists():
        conv = json.loads(conv_path.read_text(encoding="utf-8"))
        print(f"Convergence loaded: {len(conv)} clusters")
    else:
        print(f"No convergence file — will extract all items")

    targets = select_items(snap, conv, args.top_clusters, max_per_feed=args.max_per_feed)
    print(f"Targets: {len(targets)} items "
          f"(top_clusters={args.top_clusters}, max_per_feed={args.max_per_feed}, "
          f"max_body={args.max_body_chars})", flush=True)
    if not targets:
        print("Nothing to extract.")
        return

    # Run extraction in parallel
    print(f"Extracting (workers={args.workers}, per-host {args.per_host_delay}s, "
          f"checkpoint every {args.checkpoint_every}, timeout {args.timeout}s)", flush=True)
    t_start = time.time()
    done = 0
    last_checkpoint_done = 0
    last_progress_t = t_start
    statuses_running = {}
    fn = lambda payload: extract_one(payload[2], max_body=args.max_body_chars,
                                     timeout=args.timeout, per_host_delay=args.per_host_delay)
    print_every = max(1, min(50, len(targets) // 50))  # print 50 progress lines max
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(fn, t): t for t in targets}
        for fut in cf.as_completed(futures):
            ck, fname, item = futures[fut]
            result = fut.result()
            # Annotate item in place
            item.update(result)
            done += 1
            statuses_running[result["extraction_status"]] = (
                statuses_running.get(result["extraction_status"], 0) + 1
            )
            now = time.time()
            if done % print_every == 0 or done == len(targets):
                rate = done / max(0.1, now - t_start)
                remaining = (len(targets) - done) / max(0.1, rate)
                pct = 100 * done / len(targets)
                # Live status counters
                stat = " ".join(f"{k}={v}" for k, v in sorted(statuses_running.items()))
                print(f"  [{done:>4}/{len(targets)}] {pct:>5.1f}%  "
                      f"{rate:>4.1f}/s  ETA {remaining:>5.0f}s  | {stat}", flush=True)
                last_progress_t = now
            # Checkpoint save
            if args.checkpoint_every and done - last_checkpoint_done >= args.checkpoint_every:
                snap_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False))
                last_checkpoint_done = done
                print(f"  ... checkpoint saved at {done} items", flush=True)

    elapsed = time.time() - t_start

    # Tally
    from collections import Counter
    statuses = Counter()
    for ck, cv in snap["countries"].items():
        for f in cv.get("feeds", []):
            for it in f.get("items", []):
                if "extraction_status" in it:
                    statuses[it["extraction_status"]] += 1
    print(f"\nExtraction complete in {elapsed:.1f}s")
    for s in ("FULL", "PARTIAL", "STUB", "NONE", "ERROR", "SKIPPED"):
        n = statuses.get(s, 0)
        if n:
            pct = 100 * n / max(1, sum(statuses.values()))
            print(f"  {s:<8} {n:>5}  ({pct:>4.1f}%)")

    # Persist (re-stamp so the in-place rewrite carries the live meta_version)
    meta.stamp(snap)
    snap_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False))
    print(f"\nSnapshot updated: {snap_path}")


if __name__ == "__main__":
    main()
