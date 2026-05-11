"""robustness_check.py — day-over-day frame-allocation stability per story.

Reads `trajectory/<story>.json` (Phase 1) and computes how stable each
story's frame distribution is across consecutive days. Output:
`robustness/<story>.json` with per-story stability index + the
day-over-day frame-set Jaccard similarities that contribute to it.

**Honest scope note.** This catches *frame-allocation* instability — the
analyzer assigning different frame_ids on similar inputs across days, or
the bucket set changing under the analyzer. It does NOT catch *model
drift*: same prompt, same input, different output across snapshots. That
honest robustness check requires re-running the analyzer (LLM call) on
past briefings, which is OAuth-metered Phase 4+ work and explicitly
out-of-scope here.

Stability index per story:
  stability = mean(jaccard(frame_set_t, frame_set_{t+1}))
              over all consecutive day pairs
where frame_set_t = set of frame_ids in the analysis on day t.

Range: 0.0 (no overlap any day) → 1.0 (perfect stability).

Threshold: stability < 0.5 is flagged as "low_stability" — the analyzer
is reaching for different frame categories from one day to the next on
the same story. This is consistent with a fundamentally unstable story
(news cycle in flux), an unstable feed set under that bucket, or a
codebook that's coarse for the story's real variation. The flag does
NOT distinguish among those causes; it just alerts the consumer.

Cron: daily, after `analytical.longitudinal`. Skips with `no_trajectories`
when no trajectory files yet exist.

Usage:
  python -m analytical.robustness_check
  python -m analytical.robustness_check --story hormuz_iran
  python -m analytical.robustness_check --threshold 0.4
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
TRAJECTORY = ROOT / "trajectory"
ROBUSTNESS = ROOT / "robustness"


def jaccard(a: set, b: set) -> float | None:
    """Jaccard similarity. Returns None when both sets empty (undefined)."""
    if not a and not b:
        return None
    union = a | b
    if not union:
        return None
    return len(a & b) / len(union)


def frame_set_per_day(trajectory: dict) -> dict[str, set]:
    """Walk the trajectory's frame_trajectories and return {date: set of frame_ids}."""
    by_day: dict[str, set] = {}
    for fid, entries in (trajectory.get("frame_trajectories") or {}).items():
        for e in entries:
            d = e.get("date")
            if not d:
                continue
            by_day.setdefault(d, set()).add(fid)
    return by_day


def compute_robustness(trajectory: dict, threshold: float = 0.5) -> dict:
    """Stability index over consecutive day pairs."""
    days = frame_set_per_day(trajectory)
    sorted_days = sorted(days.keys())
    if len(sorted_days) < 2:
        return {
            "skipped": True,
            "reason": "insufficient_history",
            "n_days": len(sorted_days),
        }
    pairs: list[dict] = []
    sims: list[float] = []
    for d_curr, d_next in zip(sorted_days, sorted_days[1:]):
        sim = jaccard(days[d_curr], days[d_next])
        pairs.append({
            "from_date": d_curr,
            "to_date": d_next,
            "from_frames": sorted(days[d_curr]),
            "to_frames": sorted(days[d_next]),
            "jaccard": (round(sim, 3) if sim is not None else None),
        })
        if sim is not None:
            sims.append(sim)
    if not sims:
        return {
            "skipped": True, "reason": "all_pairs_undefined",
            "n_days": len(sorted_days),
        }
    stability = sum(sims) / len(sims)
    return {
        "skipped": False,
        "n_days": len(sorted_days),
        "n_consecutive_pairs": len(pairs),
        "stability": round(stability, 3),
        "low_stability": stability < threshold,
        "threshold": threshold,
        "consecutive_pairs": pairs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--story", default=None,
                    help="Limit to one story_key (default: all).")
    ap.add_argument("--threshold", type=float, default=0.5,
                    help="Stability threshold below which low_stability=true.")
    ap.add_argument("--out-dir", default=str(ROBUSTNESS))
    ap.add_argument("--trajectory-dir", default=str(TRAJECTORY))
    args = ap.parse_args()

    traj_dir = Path(args.trajectory_dir)
    if not traj_dir.is_dir():
        print(f"no_trajectories: {traj_dir} doesn't exist. "
              "Run `python -m analytical.longitudinal` first.")
        return 0
    targets = sorted(p for p in traj_dir.glob("*.json")
                      if p.stem != "index"
                      and (not args.story or p.stem == args.story))
    if not targets:
        print(f"no_trajectories: no trajectory files in {traj_dir}.")
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n_written = 0
    for p in targets:
        try:
            traj = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
            print(f"FAIL: {p}: {e}", file=sys.stderr)
            continue
        rob = compute_robustness(traj, threshold=args.threshold)
        out = meta.stamp({
            "story_key": traj.get("story_key") or p.stem,
            "story_title": traj.get("story_title"),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            **rob,
        })
        out_path = out_dir / f"{p.stem}.json"
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        n_written += 1
        if rob.get("skipped"):
            print(f"  - {p.stem:40s} skipped: {rob['reason']}")
        else:
            flag = " ⚠ low_stability" if rob.get("low_stability") else ""
            print(f"  ✓ {p.stem:40s} stability={rob['stability']} "
                  f"({rob['n_consecutive_pairs']} pairs){flag}")
    print(f"\nwrote {n_written} robustness artefacts to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
