"""Phase 0 baseline — pin pre-refactor state for later A/B comparison.

Saves:
  baseline/2026-05-02_baseline.json    copy of latest snapshot
  baseline/feed_stats.json             per-feed (uptime, avg_items, avg_summary_chars, status)
  baseline/cluster_stats.json          per-day (n_clusters, max_country_count, mean_sim)
"""
from __future__ import annotations
import json, shutil
from collections import Counter
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).parent
SNAPS = ROOT / "snapshots"
BASE = ROOT / "baseline"
BASE.mkdir(exist_ok=True)

# Latest day
dates = sorted(p.stem for p in SNAPS.glob("[0-9]*.json")
               if not p.stem.endswith(("_convergence", "_similarity", "_prompt")))
latest = dates[-1]
shutil.copy(SNAPS / f"{latest}.json", BASE / f"{latest}_baseline.json")
shutil.copy(SNAPS / f"{latest}_convergence.json", BASE / f"{latest}_convergence_baseline.json")
shutil.copy(SNAPS / f"{latest}_similarity.json", BASE / f"{latest}_similarity_baseline.json")

# Per-feed stats over all 39 days
feed_stats = {}
for d in dates:
    snap = json.loads((SNAPS / f"{d}.json").read_text(encoding="utf-8"))
    for ck, cv in snap["countries"].items():
        for f in cv["feeds"]:
            key = f"{ck} | {f['name']}"
            rec = feed_stats.setdefault(key, {
                "country_bucket": ck, "name": f["name"], "lang": f.get("lang"),
                "lean": f.get("lean", ""), "days": 0, "live_days": 0,
                "items_total": 0, "summary_chars_total": 0, "summary_n": 0,
            })
            rec["days"] += 1
            n = f.get("item_count", 0)
            rec["items_total"] += n
            if n > 0:
                rec["live_days"] += 1
            for it in f.get("items", []):
                s = it.get("summary") or ""
                rec["summary_chars_total"] += len(s)
                rec["summary_n"] += 1

for rec in feed_stats.values():
    rec["uptime_pct"] = round(100 * rec["live_days"] / rec["days"], 1) if rec["days"] else 0.0
    rec["avg_items_per_day"] = round(rec["items_total"] / rec["days"], 2) if rec["days"] else 0.0
    rec["avg_summary_chars"] = round(rec["summary_chars_total"] / rec["summary_n"], 1) if rec["summary_n"] else 0.0
    del rec["summary_chars_total"], rec["summary_n"]

(BASE / "feed_stats.json").write_text(
    json.dumps(sorted(feed_stats.values(),
                      key=lambda x: (x["country_bucket"], x["name"])),
               indent=2, ensure_ascii=False)
)

# Per-day cluster stats
cluster_stats = []
for d in dates:
    conv = json.loads((SNAPS / f"{d}_convergence.json").read_text(encoding="utf-8"))
    if not conv:
        cluster_stats.append({"date": d, "n_clusters": 0})
        continue
    cluster_stats.append({
        "date": d,
        "n_clusters": len(conv),
        "max_country_count": max(c["country_count"] for c in conv),
        "mean_sim_top10": round(mean(c["mean_similarity"]
                                     for c in sorted(conv, key=lambda c: -c["country_count"])[:10]), 3),
        "total_articles": sum(c["article_count"] for c in conv),
    })
(BASE / "cluster_stats.json").write_text(json.dumps(cluster_stats, indent=2))

print(f"Baseline pinned for {latest}")
print(f"  feeds tracked: {len(feed_stats)}")
print(f"  days tracked:  {len(cluster_stats)}")
print(f"  total feeds @100% uptime: {sum(1 for r in feed_stats.values() if r['uptime_pct']==100)}")
print(f"  total dead feeds (0% uptime): {sum(1 for r in feed_stats.values() if r['uptime_pct']==0)}")
print(f"  total items in latest snapshot: {sum(r['avg_items_per_day'] for r in feed_stats.values()):.0f}")
