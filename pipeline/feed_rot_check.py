"""Phase 9: weekly feed-rot check.

Scans the last N daily _health.json files (default from meta.FEED_ROT)
and surfaces:
  - feeds with persistent errors (>=error_days_min within the window)
  - feeds with persistent stub-only days (>=stub_days_min)
  - feeds with declining item counts (last/first below decline_factor)

All windows + thresholds are pinned in meta_version.json under "feed_rot".

Emits review/rot_report_<date>.md so a human can decide whether to drop
or replace each flagged feed.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import meta
from meta import REPO_ROOT as ROOT
SNAPS = ROOT / "snapshots"
REVIEW = ROOT / "review"
REVIEW.mkdir(exist_ok=True)

_WINDOW_DAYS = int(meta.FEED_ROT["window_days"])
_ERROR_DAYS_MIN = int(meta.FEED_ROT["error_days_min"])
_STUB_DAYS_MIN = int(meta.FEED_ROT["stub_days_min"])
_DECLINE_FACTOR = float(meta.FEED_ROT["decline_factor"])
_DECLINE_MIN_BASELINE = int(meta.FEED_ROT["decline_min_baseline"])
_DECLINE_MIN_HISTORY = int(meta.FEED_ROT["decline_min_history"])
_TOP_N_DECLINING = int(meta.FEED_ROT["top_n_declining"])


def main(n_days: int = _WINDOW_DAYS):
    today = datetime.now(timezone.utc).date()
    health_files = []
    for i in range(n_days):
        d = (today - timedelta(days=i)).isoformat()
        p = SNAPS / f"{d}_health.json"
        if p.exists():
            health_files.append(json.loads(p.read_text(encoding="utf-8")))
    if not health_files:
        print("No daily health files found. Run daily_health.py first.")
        return

    err_streaks = defaultdict(int)
    stub_streaks = defaultdict(int)
    items_by_feed: dict[str, list[int]] = defaultdict(list)
    for h in health_files:
        for e in h.get("errors", []):
            err_streaks[(e["bucket"], e["feed"])] += 1
        for s in h.get("stub_feeds", []):
            stub_streaks[(s["bucket"], s["feed"])] += 1

    # items-per-feed history: requires loading raw snapshots
    for h in health_files:
        d = h["date"]
        snap_p = SNAPS / f"{d}.json"
        if not snap_p.exists():
            continue
        try:
            snap = json.loads(snap_p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for ck, cv in snap["countries"].items():
            for f in cv["feeds"]:
                items_by_feed[(ck, f["name"])].append(f.get("item_count", 0))

    n_window = len(health_files)
    report = [f"# Feed Rot Report — {today} (last {n_window} days)\n"]
    report.append(f"## Persistent error feeds (>={_ERROR_DAYS_MIN}/{n_window} days)\n")
    for (b, n), c in sorted(err_streaks.items(), key=lambda x: -x[1]):
        if c >= _ERROR_DAYS_MIN:
            report.append(f"- {b} | {n} — errored {c}/{n_window} days")

    report.append(f"\n## Persistent stub-only feeds (>={_STUB_DAYS_MIN}/{n_window} days)\n")
    for (b, n), c in sorted(stub_streaks.items(), key=lambda x: -x[1]):
        if c >= _STUB_DAYS_MIN:
            report.append(f"- {b} | {n} — stub {c}/{n_window} days")

    report.append("\n## Declining-item-count feeds (last vs first day)\n")
    declining = []
    for (b, n), seq in items_by_feed.items():
        if (len(seq) >= _DECLINE_MIN_HISTORY
                and seq[0] >= _DECLINE_MIN_BASELINE
                and seq[-1] < _DECLINE_FACTOR * seq[0]):
            declining.append((b, n, seq))
    for b, n, seq in sorted(declining, key=lambda x: -x[2][0])[:_TOP_N_DECLINING]:
        report.append(f"- {b} | {n} — {seq[0]} -> {seq[-1]} items ({seq})")

    out = REVIEW / f"rot_report_{today}.md"
    out.write_text("\n".join(report))
    print(f"Wrote {out}")
    print(f"Persistent errors: {sum(1 for v in err_streaks.values() if v >= _ERROR_DAYS_MIN)}")
    print(f"Persistent stubs:  {sum(1 for v in stub_streaks.values() if v >= _STUB_DAYS_MIN)}")
    print(f"Declining feeds:   {len(declining)}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else _WINDOW_DAYS)
