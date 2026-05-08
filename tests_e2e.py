"""End-to-end smoke test for the epistemic-lens v0.4 pipeline.

Pipeline steps exercised (no embedding/clustering — those need
sentence-transformers which isn't in this container):

  1. Build a tiny live config (5 known-good feeds)
  2. Run pull_all() against it
  3. Persist snapshot JSON
  4. Run dedup_snapshot()
  5. Run daily_health.health_for()
  6. Run feed_rot_check (against 1 day of data — should run cleanly)
  7. Verify all output files exist + parse + contain expected fields

Outputs report to stdout; exits non-zero if any assertion fails.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

E2E_DIR = ROOT / "e2e_test"
if E2E_DIR.exists():
    shutil.rmtree(E2E_DIR)
E2E_DIR.mkdir()
SNAPS = E2E_DIR / "snapshots"
SNAPS.mkdir()

# Use known-good feeds from the audit
TEST_FEEDS = {
    "meta": {"version": "e2e-test"},
    "countries": {
        "wire_services": {"label": "Wire Services", "feeds": [
            {"name": "AFP F24 EN", "url": "https://www.france24.com/en/rss",
             "lang": "en", "lean": "wire", "status": "OK"}
        ]},
        "germany": {"label": "Germany", "feeds": [
            {"name": "DW EN", "url": "https://rss.dw.com/rdf/rss-en-all",
             "lang": "en", "lean": "public", "status": "OK"}
        ]},
        "pakistan": {"label": "Pakistan", "feeds": [
            {"name": "Dawn", "url": "https://www.dawn.com/feeds/home",
             "lang": "en", "lean": "independent", "status": "OK"}
        ]},
        "russia_native": {"label": "Russia (RU)", "feeds": [
            {"name": "Kommersant", "url": "https://www.kommersant.ru/RSS/news.xml",
             "lang": "ru", "lean": "business", "status": "OK"}
        ]},
        "ukraine": {"label": "Ukraine", "feeds": [
            {"name": "Pravda EN", "url": "https://www.pravda.com.ua/eng/rss/",
             "lang": "en", "lean": "independent", "status": "OK"}
        ]},
    },
}

cfg_path = E2E_DIR / "feeds.json"
cfg_path.write_text(json.dumps(TEST_FEEDS, indent=2))

# Force ingest to use the e2e dir
os.environ["OUTPUT_DIR"] = str(SNAPS)
os.environ["FEEDS_CONFIG"] = str(cfg_path)
os.environ["SKIP_EMBED"] = "1"
os.environ["MAX_ITEMS"] = "10"
os.environ["MAX_WORKERS"] = "5"
os.environ["PER_HOST_DELAY"] = "0.5"

passed = 0
failed = 0


def check(label: str, cond: bool, detail: str = ""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}  -- {detail}")


print("=" * 70)
print("E2E SMOKE TEST")
print("=" * 70)

# --- 1. Run ingest ---
print("\n[1] Running ingest.pull_all() on 5 feeds")
t0 = time.time()
import importlib
if "ingest" in sys.modules:
    importlib.reload(sys.modules["ingest"])
from pipeline import ingest

snap = ingest.pull_all(TEST_FEEDS)
elapsed = time.time() - t0
print(f"    {elapsed:.2f}s elapsed")

check("snap has date", "date" in snap)
check("snap has 5 country buckets", len(snap["countries"]) == 5)

total_items = sum(sum(f["item_count"] for f in c["feeds"]) for c in snap["countries"].values())
check("at least 30 items pulled", total_items >= 30, f"got {total_items}")

# Each feed should have items
for ck, cv in snap["countries"].items():
    for f in cv["feeds"]:
        check(f"  {ck}/{f['name']} has items", f["item_count"] > 0,
              f"http={f['http_status']} err={f['error']}")

# Check item-level flags exist
for cv in snap["countries"].values():
    for f in cv["feeds"]:
        for it in f["items"][:1]:
            check(f"  item has annotation flags ({f['name']})",
                  all(k in it for k in ("is_stub", "is_google_news", "summary_chars",
                                        "published_age_hours", "id")))
            break
        break

# --- 2. Persist ---
print("\n[2] Persisting snapshot")
date = snap["date"]
# Strip _embed_text before persisting (mimics ingest.py main path)
for c in snap["countries"].values():
    for f in c["feeds"]:
        for it in f["items"]:
            it.pop("_embed_text", None)
snap_path = SNAPS / f"{date}.json"
snap_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False))
check("snapshot file exists", snap_path.exists())
check("snapshot file >10KB", snap_path.stat().st_size > 10_000)

# --- 3. Dedup ---
print("\n[3] Running dedup")
if "dedup" in sys.modules:
    importlib.reload(sys.modules["dedup"])
from pipeline import dedup
result = dedup.dedup_snapshot(snap)
print(f"    {result['n_total_items']} items -> {result['n_deduped']} deduped "
      f"(url dupes={result['n_url_dupes']}, title dupes={result['n_title_dupes']})")
check("dedup result has totals", result["n_total_items"] > 0)
check("dedup didn't over-collapse",
      result["n_deduped"] >= 0.7 * result["n_total_items"])

# --- 4. Daily health ---
print("\n[4] Running daily_health on the e2e snapshot")
if "daily_health" in sys.modules:
    importlib.reload(sys.modules["daily_health"])
from pipeline import daily_health
daily_health.SNAPS = SNAPS  # redirect
h, hp = daily_health.health_for(snap_path)
check("health file exists", hp.exists())
check("health has all keys", all(k in h for k in (
    "n_feeds", "n_items", "n_errors", "n_stub_feeds", "n_slow_feeds",
    "items_per_bucket_now", "items_per_bucket_avg7", "bucket_alerts")))
check("n_feeds matches", h["n_feeds"] == 5)

# --- 5. Feed rot check ---
print("\n[5] Running feed_rot_check (only 1 day, should produce empty report)")
if "feed_rot_check" in sys.modules:
    importlib.reload(sys.modules["feed_rot_check"])
from pipeline import feed_rot_check as frc
frc.SNAPS = SNAPS
frc.REVIEW = E2E_DIR / "review"
frc.REVIEW.mkdir(exist_ok=True)
try:
    frc.main(7)
    check("rot_check ran without exception", True)
    rot_files = list(frc.REVIEW.glob("rot_report_*.md"))
    check("rot report file produced", len(rot_files) >= 1)
except Exception as e:
    check("rot_check ran without exception", False, str(e))

# --- 6. Schema validation ---
print("\n[6] Schema validation on persisted JSON")
saved = json.loads(snap_path.read_text(encoding="utf-8"))
check("date in saved snap", "date" in saved)
check("max_items field set", saved.get("max_items") == 10)
check("config_version field set", saved.get("config_version") == "e2e-test")
for ck, cv in saved["countries"].items():
    for f in cv["feeds"]:
        check(f"  {f['name']} has fetch_ms", isinstance(f.get("fetch_ms"), int))
        check(f"  {f['name']} has http_status", "http_status" in f)
        check(f"  {f['name']} has bytes", "bytes" in f)

# --- 7. Verify Cyrillic content actually flowed ---
print("\n[7] Multilingual content check")
ru_titles = []
for f in snap["countries"]["russia_native"]["feeds"]:
    for it in f["items"]:
        ru_titles.append(it["title"])
import re
has_cyrillic = any(re.search(r"[Ѐ-ӿ]", t) for t in ru_titles)
check("Kommersant returned Cyrillic titles", has_cyrillic,
      f"sample: {ru_titles[0] if ru_titles else 'none'}")

# --- 8. Verify rate limiter actually fired ---
# AFP, DW, Dawn, Kommersant, Pravda — all different hosts, no per-host wait
# (5 hosts, 0.5s delay would take >2.5s if all same host; should be <2s here)
check("parallel pull faster than serial would be",
      elapsed < 5.0, f"took {elapsed:.2f}s")

# --- Summary ---
print()
print("=" * 70)
print(f"E2E RESULTS: {passed} passed, {failed} failed")
print("=" * 70)
sys.exit(0 if failed == 0 else 1)
