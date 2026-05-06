"""Phase 3: build the v0.4.0 feeds.json from candidates + existing feeds.

Rules:
  - Drop the 4 known-dead feeds (Press TV, Tasnim, Fars News, TRT World)
  - Keep all existing feeds at their original URLs (those work on prod IP)
  - Add ACCEPT, ACCEPT_STUB, RETRY_FROM_PROD candidates with the URL that
    won the probe (alternates already merged in probe_results.json)
  - Status field becomes machine-derived: 'OK' | 'STUB' | 'RETRY' | 'DEAD'
  - Bump meta.version
"""
from __future__ import annotations
import json, shutil
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent
EXISTING = json.loads((ROOT / "feeds.json").read_text(encoding="utf-8"))
CANDS = json.loads((ROOT / "candidates.json").read_text(encoding="utf-8"))
PROBE = json.loads((ROOT / "review" / "probe_results.json").read_text(encoding="utf-8"))

# Index probe by (bucket, name) -> winning URL + decision
probe_idx = {(r["bucket"], r["name"]): r for r in PROBE}

DEAD_FEED_NAMES = {"Press TV", "Tasnim English", "Fars News EN", "TRT World"}
DEAD_FEED_URL_PATTERNS = ["tasnimnews.com", "farsnews.ir", "rsshub.app/presstv/en", "trtworld.com/rss"]

def is_dead_feed(f) -> bool:
    if f["name"] in DEAD_FEED_NAMES:
        return True
    for pat in DEAD_FEED_URL_PATTERNS:
        if pat in f["url"]:
            return True
    return False

# 1) Carry forward existing feeds, dropping dead ones
new_countries = {}
kept = 0
dropped = 0
for ckey, cval in EXISTING["countries"].items():
    kept_feeds = []
    for f in cval["feeds"]:
        if is_dead_feed(f):
            dropped += 1
            continue
        # Re-stamp status based on what we know
        nf = dict(f)
        nf["status"] = "OK"
        kept_feeds.append(nf)
        kept += 1
    if kept_feeds:
        new_countries[ckey] = {"label": cval["label"], "feeds": kept_feeds}
        if "note" in cval:
            new_countries[ckey]["note"] = cval["note"]

# 2) Merge in accepted candidates
added = 0
for ckey, cval in CANDS["countries"].items():
    label = cval["label"]
    out_bucket = ckey
    # Some candidate buckets ('turkey_extra', 'iran_state_extra', 'us_extra',
    # 'wire_extra') should merge into existing buckets, not create new ones.
    bucket_remap = {
        "turkey_extra": "turkey",
        "iran_state_extra": "iran_state",
        "us_extra": "usa",
        "wire_extra": "wire_services",
        "france_direct": "wire_services",  # merge French direct into wire bucket
    }
    out_bucket = bucket_remap.get(ckey, ckey)
    if out_bucket not in new_countries:
        new_countries[out_bucket] = {"label": label, "feeds": []}
    for f in cval["feeds"]:
        key = (ckey, f["name"])
        pr = probe_idx.get(key)
        if pr is None or pr["decision"] == "REJECT":
            continue
        url = pr["url"]  # use the URL that won the probe
        decision_to_status = {
            "ACCEPT": "OK",
            "ACCEPT_STUB": "STUB",  # title-only — usable but flagged
            "RETRY_FROM_PROD": "RETRY",  # 403/429 from container, may work on prod
        }
        status = decision_to_status.get(pr["decision"], "UNKNOWN")
        nf = {
            "name": f["name"],
            "url": url,
            "lang": f["lang"],
            "lean": f.get("lean", ""),
            "status": status,
        }
        # Avoid duplicate names within a bucket
        if any(x["name"] == nf["name"] for x in new_countries[out_bucket]["feeds"]):
            continue
        new_countries[out_bucket]["feeds"].append(nf)
        added += 1

# 3) Build new meta
new_meta = {
    "project": "epistemic-lens",
    "version": "0.4.0",
    "last_updated": str(date.today()),
    "notes": (
        "v0.4.0 expansion: ~3x feed count covering Pakistan, Lebanon, Iraq, "
        "Egypt, UAE, Ukraine, Germany direct, Indonesia, Philippines, Mexico, "
        "Argentina, Australia/NZ, Taiwan/HK, North Korea, South Africa, Kenya, "
        "plus Russian-language Russian outlets. Status flags: OK | STUB "
        "(title-only) | RETRY (403/429 from container, retest from prod IP) | "
        "DEAD (dropped)."
    ),
}

# Backup the old feeds.json
shutil.copy(ROOT / "feeds.json", ROOT / "feeds.json.bak")

new_feeds = {"meta": new_meta, "countries": new_countries}
(ROOT / "feeds.json").write_text(json.dumps(new_feeds, indent=2, ensure_ascii=False) + "\n")

# Summary
total = sum(len(c["feeds"]) for c in new_countries.values())
print(f"Built feeds.json v0.4.0:")
print(f"  Buckets: {len(new_countries)}")
print(f"  Total feeds: {total}")
print(f"  Existing kept: {kept}")
print(f"  Existing dropped (dead): {dropped}")
print(f"  Candidates added: {added}")
print()
print("Per-bucket counts:")
for ckey in sorted(new_countries):
    n = len(new_countries[ckey]["feeds"])
    statuses = {}
    for f in new_countries[ckey]["feeds"]:
        statuses[f.get("status","?")] = statuses.get(f.get("status","?"),0)+1
    s = " ".join(f"{k}={v}" for k, v in sorted(statuses.items()))
    print(f"  {ckey:<22} {n:>3}  ({s})")
