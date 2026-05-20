"""distribution/stage.py — stage today's drafts to distribution/pending/.

PR 6: approval-gate transformation. The daily cron no longer
auto-fires x_poster.py or youtube_shorts.py. Instead, this script
produces one "pending envelope" per (story, target-platform) at
distribution/pending/<date>/<story>_<platform>.json. A human (or a
separate workflow) calls `python -m distribution.publish --approve
<id>` to move an envelope to distribution/approved/, where the
actual posting can pick it up.

Rationale: schema validation, canary, and meta_version stamping
verify the *artifact* but they can't catch the failure mode where a
defensible JSON analysis reads badly compressed to a 280-char tweet
or 60 seconds of narration. The compression to social copy is where
embarrassment lives, not in the analysis itself. The cron stays
zero-touch for the analytical pipeline (which IS the load-bearing
claim); the public-channels surface is opt-in.

Usage:
  python -m distribution.stage                         # today
  python -m distribution.stage --date 2026-05-08
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
DRAFTS = ROOT / "drafts"
VIDEOS = ROOT / "videos"
PENDING_BASE = ROOT / "distribution" / "pending"

# Target-platform → (suffix glob in drafts/, paths to record on the envelope)
PLATFORMS: dict[str, dict] = {
    "x": {
        "draft_suffix": "_thread.json",
        "draft_kind": "thread",
    },
    "youtube_shorts": {
        "draft_suffix": "_long.json",
        "draft_kind": "long",
        "media_dir": VIDEOS,
        "media_suffix": ".mp4",
    },
}


def _envelope(date: str, story_key: str, platform: str, draft_path: Path,
              media_path: Path | None = None) -> dict:
    env = meta.stamp({
        "id": f"{date}_{story_key}_{platform}",
        "date": date,
        "story_key": story_key,
        "target_platform": platform,
        "draft_kind": PLATFORMS[platform]["draft_kind"],
        "draft_path": str(draft_path.relative_to(ROOT)),
        "stage_status": "pending",
        "staged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "approved_at": None,
        "approved_by": None,
    })
    if media_path and media_path.exists():
        env["media_path"] = str(media_path.relative_to(ROOT))
    return env


def _decided_elsewhere(date: str, env_name: str) -> bool:
    """Check whether this envelope was already approved / rejected /
    published. If so, re-staging must not recreate a pending entry —
    the operator already decided."""
    for sibling in ("approved", "rejected", "published"):
        if (PENDING_BASE.parent / sibling / date / env_name).exists():
            return True
    return False


def stage_for_date(date: str) -> list[Path]:
    """Stage every (story, platform) draft on `date` to distribution/pending/.

    Returns the list of pending-envelope paths written. Idempotent:
    existing pending envelopes are overwritten (re-stamps `staged_at`).
    Envelopes already moved to approved/, rejected/, or published/ are
    NOT re-created — the operator already decided.
    """
    out_dir = PENDING_BASE / date
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for platform, cfg in PLATFORMS.items():
        suffix = cfg["draft_suffix"]
        for draft_path in sorted(DRAFTS.glob(f"{date}_*{suffix}")):
            story_key = draft_path.stem[len(date) + 1:-len(suffix.removesuffix(".json"))]
            media_path = None
            if "media_dir" in cfg:
                cand = cfg["media_dir"] / f"{date}_{story_key}{cfg['media_suffix']}"
                if cand.exists():
                    media_path = cand
            env_name = f"{story_key}_{platform}.json"
            env_path = out_dir / env_name
            if _decided_elsewhere(date, env_name):
                print(f"  skip {env_name}: already decided")
                continue
            env = _envelope(date, story_key, platform, draft_path, media_path)
            try:
                meta.validate_schema(env, "distribution_pending")
            except ValueError as e:
                print(f"FAIL: {env_path}: {e}", file=sys.stderr)
                continue
            env_path.write_text(
                json.dumps(env, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            written.append(env_path)
            print(f"  staged {env_path.name}")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD; default: today UTC.")
    args = ap.parse_args()
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Staging distribution drafts for {date}")
    written = stage_for_date(date)
    if not written:
        print(f"  no new drafts to stage")
    print(f"\n{len(written)} envelope(s) written to {PENDING_BASE / date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
