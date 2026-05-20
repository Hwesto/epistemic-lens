"""distribution/publish.py — approval CLI for staged distribution drafts.

PR 6: the approval gate between cron-staged drafts and actual public
posting. Reads `distribution/pending/<date>/`, lists envelopes, and
moves them to `distribution/approved/` or `distribution/rejected/`
on operator command.

This script does NOT post. It just changes the status of an envelope
on disk. Actual posting is the responsibility of a separate workflow
(or human) that reads `distribution/approved/` and uses the platform
secrets to publish. Decoupling keeps the OAuth surface narrow:
approval can happen from any clone of the repo (no secrets needed);
posting only happens where the secrets live.

Usage:
  python -m distribution.publish --list                # all pending
  python -m distribution.publish --list --date 2026-05-08
  python -m distribution.publish --approve <id>        # → approved/
  python -m distribution.publish --reject <id>         # → rejected/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
DIST = ROOT / "distribution"
PENDING = DIST / "pending"
APPROVED = DIST / "approved"
REJECTED = DIST / "rejected"


def _all_pending(date: str | None = None) -> list[Path]:
    if date:
        return sorted((PENDING / date).glob("*.json")) if (PENDING / date).is_dir() else []
    if not PENDING.is_dir():
        return []
    out: list[Path] = []
    for sub in sorted(PENDING.iterdir()):
        if sub.is_dir():
            out.extend(sorted(sub.glob("*.json")))
    return out


def cmd_list(date: str | None) -> int:
    envs = _all_pending(date)
    if not envs:
        scope = f"for {date}" if date else "(all dates)"
        print(f"No pending envelopes {scope}.")
        return 0
    print(f"{'ID':<55} {'PLATFORM':<15} {'STAGED':<22}")
    for p in envs:
        try:
            env = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"FAIL: {p}: {e}", file=sys.stderr)
            continue
        print(f"{env.get('id', p.stem):<55} {env.get('target_platform', '?'):<15} "
              f"{env.get('staged_at', '?'):<22}")
    return 0


def _find_envelope(envelope_id: str) -> Path | None:
    """Locate a pending envelope by id across all date subdirs."""
    if not PENDING.is_dir():
        return None
    for sub in PENDING.iterdir():
        if not sub.is_dir():
            continue
        for p in sub.glob("*.json"):
            try:
                env = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if env.get("id") == envelope_id:
                return p
    return None


def _move(env_path: Path, status: str, dest_base: Path) -> Path:
    env = json.loads(env_path.read_text(encoding="utf-8"))
    env["stage_status"] = status
    env["approved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    env["approved_by"] = os.environ.get("USER") or os.environ.get("USERNAME") or "?"
    date = env.get("date") or env_path.parent.name
    dest_dir = dest_base / date
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / env_path.name
    dest_path.write_text(
        json.dumps(env, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    env_path.unlink()
    return dest_path


def cmd_approve(envelope_id: str) -> int:
    src = _find_envelope(envelope_id)
    if not src:
        print(f"No pending envelope with id {envelope_id!r}.", file=sys.stderr)
        return 1
    dest = _move(src, "approved", APPROVED)
    print(f"approved → {dest.relative_to(ROOT)}")
    return 0


def cmd_reject(envelope_id: str) -> int:
    src = _find_envelope(envelope_id)
    if not src:
        print(f"No pending envelope with id {envelope_id!r}.", file=sys.stderr)
        return 1
    dest = _move(src, "rejected", REJECTED)
    print(f"rejected → {dest.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--list", action="store_true")
    grp.add_argument("--approve", metavar="<id>")
    grp.add_argument("--reject", metavar="<id>")
    ap.add_argument("--date", default=None,
                    help="Restrict --list to a specific date.")
    args = ap.parse_args()
    if args.list:
        return cmd_list(args.date)
    if args.approve:
        return cmd_approve(args.approve)
    if args.reject:
        return cmd_reject(args.reject)
    return 1


if __name__ == "__main__":
    sys.exit(main())
