"""coverage_warnings.py — surface dead-bucket coverage from daily_health.

Reads `snapshots/<date>_health.json` and returns per-bucket records for
the bucket-alert types that represent structural silence — i.e. the
bucket had zero qualifying items today because every feed in it 403'd /
timed out / returned empty. Downstream consumers (build_briefing,
render_analysis_md, the daily-analysis prompt) use these to distinguish:

  - **Structural silence**: bucket dead today (no items at all). Reported
    as `coverage_caveats[]` in the briefing and analysis JSON.
  - **Editorial silence**: bucket had qualifying items but chose a
    different angle. Reported in `silences[]` by the LLM analyze pass.

Without this split, an LLM looking at "lebanon_buffer corpus has no
Lebanese press today" infers editorial silence ("Lebanon is staying
quiet on the southern strikes") when the truth is "every Lebanese feed
403'd". Fixed for May 12, when Lebanon/Saudi/Jordan/Palestine were 100%
dead and analyses called out their "silence" as if it were a choice.
"""
from __future__ import annotations

import json
from pathlib import Path

import meta

SNAPS = meta.REPO_ROOT / "snapshots"


def coverage_warnings_for(date: str,
                            snap_dir: Path = SNAPS,
                            min_avg7: float = 2.0) -> list[dict]:
    """Return structural-silence records for `date`.

    Returns a list of `{bucket, alert_type, now, avg7, drop_pct,
    reason}` dicts for buckets where:
      - alert_type == "volume_drop" AND now == 0 AND avg7 >= min_avg7

    `min_avg7` filters out historically-thin buckets that report 0 items
    today not because of feed failure but because they never had many
    items to begin with. Default 2.0 — i.e. only flag a bucket as
    "structurally silent" if it carries ≥ 2 items/day on the rolling
    7-day average.

    Empty list when the health file is missing (cron hasn't run yet) or
    when no buckets meet the criteria. Used by build_briefing.py to
    stamp briefing.coverage_caveats and by render_analysis_md.py to
    render the Coverage Caveats markdown section.
    """
    health_path = snap_dir / f"{date}_health.json"
    if not health_path.exists():
        return []
    try:
        health = json.loads(health_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: list[dict] = []
    for alert in health.get("bucket_alerts") or []:
        if alert.get("alert_type") != "volume_drop":
            continue
        if alert.get("now", -1) != 0:
            continue
        if alert.get("avg7", 0) < min_avg7:
            continue
        out.append({
            "bucket": alert["bucket"],
            "alert_type": "structural_silence",
            "now": 0,
            "avg7": alert["avg7"],
            "drop_pct": alert.get("drop_pct"),
            "reason": (
                "bucket carried 0 items today (rolling 7-day avg "
                f"{alert['avg7']:.1f}). Feeds 403'd / timed out / returned "
                "empty. Treat absence as structural, not editorial."
            ),
        })
    out.sort(key=lambda r: r["bucket"])
    return out
