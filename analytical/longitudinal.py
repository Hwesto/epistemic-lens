"""longitudinal.py — frame-share trajectory per story over time.

Walks `analyses/<DATE>_<story_key>.json`, groups by story_key, and emits
`trajectory/<story_key>.json` with per-day frame share. Phase 1 closes the
"missing centerpiece": the project has been emitting daily snapshots without
ever publishing the longitudinal arc.

Frame schema dual support: pre-7.0.0 analyses use `frame.label`; post-7.0.0
use `frame.frame_id`. Both are honoured; the trajectory groups by whichever
is present.

Continuity flags:
 - `meta_version_segments`: contiguous date-runs sharing the same pin.
   Trajectories that span a major bump should be read with caution.
 - `bucket_set_signature`: sha256 of sorted bucket list. Multiple distinct
   signatures within a trajectory mean the contributing-feed set changed
   (feeds.json edit, bucket added/removed); flagged for the consumer.

Output: `trajectory/<story_key>.json`:

    {
      "story_key": "...",
      "story_title": "...",
      "window_start": "YYYY-MM-DD",
      "window_end":   "YYYY-MM-DD",
      "n_days_with_analysis": int,
      "meta_version_segments": [
        {"meta_version", "from_date", "to_date", "n_days"}
      ],
      "bucket_set_signatures": [
        {"signature", "from_date", "to_date", "n_buckets", "buckets"}
      ],
      "daily_summaries": [
        {"date", "meta_version", "n_buckets", "n_articles", "n_frames",
         "bucket_set_signature"}
      ],
      "frame_trajectories": {
        "<frame_id_or_label>": [
          {"date", "n_buckets_carrying", "n_buckets_total", "share",
           "meta_version"}
        ]
      }
    }

Usage:
  python -m analytical.longitudinal                      # all stories, all dates
  python -m analytical.longitudinal --story hormuz_iran  # one story
  python -m analytical.longitudinal --window 30          # last 30 days only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
ANALYSES = ROOT / "analyses"
TRAJECTORY = ROOT / "trajectory"

# analyses/<YYYY-MM-DD>_<story_key>.json
ANALYSIS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)\.json$")


def _frame_key(frame: dict) -> str:
    """Schema-tolerant frame identifier — `frame_id` (>=7.0.0) or `label`."""
    return (frame.get("frame_id") or frame.get("label") or "UNLABELED").strip()


def _bucket_set_signature(buckets: list[str]) -> str:
    """Deterministic short hash over the sorted bucket list."""
    s = ",".join(sorted(buckets))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def collect_analyses(story_key: str | None = None,
                      analyses_dir: Path = ANALYSES,
                      window_days: int | None = None,
                      today: str | None = None) -> dict[str, list[Path]]:
    """Group analysis paths by story_key, sorted by date."""
    cutoff: str | None = None
    if window_days is not None:
        today_d = date.fromisoformat(today) if today else date.today()
        cutoff = (today_d - timedelta(days=window_days)).isoformat()
    by_story: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for p in analyses_dir.glob("*.json"):
        m = ANALYSIS_RE.match(p.name)
        if not m:
            continue
        d, sk = m.group(1), m.group(2)
        if story_key and sk != story_key:
            continue
        if cutoff and d < cutoff:
            continue
        by_story[sk].append((d, p))
    return {sk: [p for _, p in sorted(items)] for sk, items in by_story.items()}


BRIEFINGS = ROOT / "briefings"


def _load_briefing_for(analysis_path: Path) -> dict | None:
    """Load the sibling briefing for an analysis path, or None if missing.

    Phase 3i + 3j: the bucket_feed_set_hashes and canonical_stories_hash
    are stamped on the BRIEFING (build_briefing.py); longitudinal needs
    to surface them per-day to detect drift across the trajectory."""
    m = ANALYSIS_RE.match(analysis_path.name)
    if not m:
        return None
    d, sk = m.group(1), m.group(2)
    bp = BRIEFINGS / f"{d}_{sk}.json"
    if not bp.exists():
        return None
    try:
        return json.loads(bp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
        print(f"FAIL: {bp}: {e}", file=sys.stderr)
        return None


def build_trajectory(paths: list[Path]) -> dict:
    """Read N analysis JSONs (already date-sorted) and emit one trajectory."""
    if not paths:
        return {}
    daily_summaries: list[dict] = []
    frame_traj: dict[str, list[dict]] = defaultdict(list)
    story_title: str | None = None
    story_key: str | None = None
    bucket_set_runs: list[dict] = []
    last_signature: str | None = None
    last_run_buckets: list[str] = []
    meta_version_runs: list[dict] = []
    last_meta_version: str | None = None
    # Phase 3i: per-bucket feed-set drift segments — keyed by bucket, each
    # value is a list of {feed_set_hash, from_date, to_date}.
    feed_set_runs: dict[str, list[dict]] = defaultdict(list)
    last_feed_set_hash: dict[str, str] = {}
    # Phase 3j: canonical_stories pattern drift segments.
    pattern_runs: list[dict] = []
    last_pattern_hash: str | None = None

    for p in paths:
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
            print(f"FAIL: {p}: {e}", file=sys.stderr)
            continue
        d = a.get("date") or ANALYSIS_RE.match(p.name).group(1)
        story_title = story_title or a.get("story_title")
        story_key = story_key or a.get("story_key") or ANALYSIS_RE.match(p.name).group(2)
        analysis_meta = str(a.get("meta_version") or "?")

        # Sibling briefing carries Phase 3i/3j hashes.
        briefing = _load_briefing_for(p) or {}
        bucket_feed_set_hashes = briefing.get("bucket_feed_set_hashes") or {}
        pattern_hash = briefing.get("canonical_stories_hash") or "?"

        # Buckets in this analysis: union over frames.
        buckets: list[str] = []
        for f in a.get("frames") or []:
            for b in f.get("buckets") or []:
                if b not in buckets:
                    buckets.append(b)
        signature = _bucket_set_signature(buckets)
        n_buckets_total = max(1, len(buckets))

        # Per-frame share for the day
        for f in a.get("frames") or []:
            fk = _frame_key(f)
            n_carrying = len(f.get("buckets") or [])
            frame_traj[fk].append({
                "date": d,
                "n_buckets_carrying": n_carrying,
                "n_buckets_total": len(buckets),
                "share": round(n_carrying / n_buckets_total, 3),
                "meta_version": analysis_meta,
            })

        daily_summaries.append({
            "date": d,
            "meta_version": analysis_meta,
            "n_buckets": len(buckets),
            "n_articles": int(a.get("n_articles") or 0),
            "n_frames": len(a.get("frames") or []),
            "bucket_set_signature": signature,
            "canonical_stories_hash": pattern_hash,
        })

        # Track meta_version runs (contiguous date-segments)
        if analysis_meta != last_meta_version:
            meta_version_runs.append(
                {"meta_version": analysis_meta, "from_date": d, "to_date": d, "n_days": 1}
            )
            last_meta_version = analysis_meta
        else:
            meta_version_runs[-1]["to_date"] = d
            meta_version_runs[-1]["n_days"] += 1

        # Track bucket-set signature runs
        if signature != last_signature:
            bucket_set_runs.append({
                "signature": signature,
                "from_date": d,
                "to_date": d,
                "n_buckets": len(buckets),
                "buckets": list(buckets),
            })
            last_signature = signature
            last_run_buckets = buckets
        else:
            bucket_set_runs[-1]["to_date"] = d
            # Buckets identical by definition since signature matches.

        # Phase 3i: per-bucket feed-set drift. For each bucket appearing
        # in this day's analysis, compare its feed-set hash to the last
        # observed value; open a new run on change.
        for b in buckets:
            cur = bucket_feed_set_hashes.get(b)
            if not cur:
                continue
            if last_feed_set_hash.get(b) != cur:
                feed_set_runs[b].append({
                    "feed_set_hash": cur, "from_date": d, "to_date": d,
                })
                last_feed_set_hash[b] = cur
            else:
                feed_set_runs[b][-1]["to_date"] = d

        # Phase 3j: canonical_stories pattern hash runs
        if pattern_hash != last_pattern_hash:
            pattern_runs.append({
                "canonical_stories_hash": pattern_hash,
                "from_date": d, "to_date": d, "n_days": 1,
            })
            last_pattern_hash = pattern_hash
        else:
            pattern_runs[-1]["to_date"] = d
            pattern_runs[-1]["n_days"] += 1

    # Phase 3i + 3j: surface drift summaries so consumers can hedge claims
    # spanning a feed-set change or a canonical-stories pattern change.
    bucket_feed_set_drift = {
        b: runs for b, runs in feed_set_runs.items() if len(runs) > 1
    }
    return {
        "story_key": story_key,
        "story_title": story_title,
        "window_start": daily_summaries[0]["date"] if daily_summaries else None,
        "window_end": daily_summaries[-1]["date"] if daily_summaries else None,
        "n_days_with_analysis": len(daily_summaries),
        "meta_version_segments": meta_version_runs,
        "bucket_set_signatures": bucket_set_runs,
        "canonical_stories_pattern_segments": pattern_runs,
        "bucket_feed_set_segments": dict(feed_set_runs),
        "bucket_feed_set_drift": bucket_feed_set_drift,
        "daily_summaries": daily_summaries,
        "frame_trajectories": dict(frame_traj),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--story", default=None,
                    help="Build trajectory for one story_key only (default: all).")
    ap.add_argument("--window", type=int, default=None,
                    help="Days back to consider (default: all available).")
    ap.add_argument("--out-dir", default=str(TRAJECTORY))
    ap.add_argument("--analyses-dir", default=str(ANALYSES))
    args = ap.parse_args()

    analyses_dir = Path(args.analyses_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    grouped = collect_analyses(args.story, analyses_dir=analyses_dir,
                                window_days=args.window)
    if not grouped:
        print("No analyses matched.", file=sys.stderr)
        return 0

    n_written = 0
    for sk, paths in sorted(grouped.items()):
        traj = build_trajectory(paths)
        if not traj:
            continue
        traj = meta.stamp(traj)
        out_path = out_dir / f"{sk}.json"
        out_path.write_text(json.dumps(traj, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        n_written += 1
        n_segments = len(traj.get("meta_version_segments") or [])
        n_bucket_runs = len(traj.get("bucket_set_signatures") or [])
        flag = ""
        if n_segments > 1:
            flag += f"  (spans {n_segments} pins)"
        if n_bucket_runs > 1:
            flag += f"  ({n_bucket_runs} bucket-set changes)"
        print(f"  {sk:35s} {traj['n_days_with_analysis']:>3d} days  "
              f"frames={len(traj.get('frame_trajectories') or {}):>2d}{flag}")
    print(f"wrote {n_written} trajectory files to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
