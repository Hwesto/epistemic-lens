"""Phase 9: weekly feed-rot check.

Scans the last N daily _health.json files (default 7) and surfaces:
  - feeds with persistent errors (>=4/7 days)
  - feeds that have been stub-only for >=4/7 days
  - feeds with declining item counts (downward trend)

Emits review/rot_report_<date>.md so a human can decide whether to drop
or replace each flagged feed.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from meta import REPO_ROOT as ROOT
SNAPS = ROOT / "snapshots"
REVIEW = ROOT / "review"
REVIEW.mkdir(exist_ok=True)


def main(n_days: int = 7):
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

    report = [f"# Feed Rot Report — {today} (last {len(health_files)} days)\n"]
    report.append("## Persistent error feeds (>=4/7 days)\n")
    for (b, n), c in sorted(err_streaks.items(), key=lambda x: -x[1]):
        if c >= 4:
            report.append(f"- {b} | {n} — errored {c}/{len(health_files)} days")

    report.append("\n## Persistent stub-only feeds (>=4/7 days)\n")
    for (b, n), c in sorted(stub_streaks.items(), key=lambda x: -x[1]):
        if c >= 4:
            report.append(f"- {b} | {n} — stub {c}/{len(health_files)} days")

    report.append("\n## Declining-item-count feeds (last vs first day)\n")
    declining = []
    for (b, n), seq in items_by_feed.items():
        if len(seq) >= 4 and seq[0] >= 5 and seq[-1] < 0.5 * seq[0]:
            declining.append((b, n, seq))
    for b, n, seq in sorted(declining, key=lambda x: -x[2][0])[:20]:
        report.append(f"- {b} | {n} — {seq[0]} -> {seq[-1]} items ({seq})")

    out = REVIEW / f"rot_report_{today}.md"
    out.write_text("\n".join(report))
    print(f"Wrote {out}")
    print(f"Persistent errors: {sum(1 for v in err_streaks.values() if v >= 4)}")
    print(f"Persistent stubs:  {sum(1 for v in stub_streaks.values() if v >= 4)}")
    print(f"Declining feeds:   {len(declining)}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
