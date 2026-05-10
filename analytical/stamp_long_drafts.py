#!/usr/bin/env python3
"""stamp_long_drafts.py — set meta_version on long-form draft JSON files.

The agent's prompt at .claude/prompts/draft_long.md asks for a fixed
required-fields list but doesn't (and can't) reliably call meta.stamp()
in Python before writing. Every other artifact in the pipeline —
briefings, metrics, analyses, thread + carousel drafts — IS stamped at
write time. This script closes the gap for long-form drafts by
re-stamping every `drafts/<date>_*_long.json` after the agent writes
its outputs and before the workflow's schema validator runs.

Idempotent. No-op when already stamped correctly. Re-validates against
long.schema.json after stamping so stamp drift can't mask other shape
drift.

Usage:
  python stamp_long_drafts.py                     # all today's long drafts
  python stamp_long_drafts.py --date 2026-05-08
  python stamp_long_drafts.py FILE.json [...]
  python stamp_long_drafts.py --all               # every long draft on disk
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


def stamp(p: Path) -> bool:
    """Set p's meta_version to current pin. Return True if changed.

    Re-validates after stamp so a malformed draft surfaces immediately
    rather than masking shape drift behind a stamp-only diff. Warns and
    skips on schema mismatch — the workflow's validator step is the
    load-bearing gate.
    """
    d = json.loads(p.read_text(encoding="utf-8"))
    old = d.get("meta_version")
    if old == meta.VERSION:
        return False
    d["meta_version"] = meta.VERSION
    try:
        meta.validate_schema(d, "long")
    except ValueError as e:
        print(f"  ! {p.name}: post-stamp schema mismatch — {e}",
              file=sys.stderr)
        return False
    p.write_text(
        json.dumps(d, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  stamped {p.name}: {old} -> {meta.VERSION}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--date", default=None)
    ap.add_argument("--all", action="store_true",
                    help="Stamp every *_long.json on disk (one-off backfill).")
    args = ap.parse_args()

    if args.files:
        targets = list(args.files)
    elif args.all:
        targets = sorted(DRAFTS.glob("*_long.json"))
    else:
        date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        targets = sorted(DRAFTS.glob(f"{date}_*_long.json"))
        if not targets:
            print(f"No long-form drafts for {date}.")
            return 0

    n_changed = 0
    for t in targets:
        if t.suffix != ".json":
            continue
        if stamp(t):
            n_changed += 1
    if n_changed == 0:
        print(f"All {len(targets)} long drafts already stamped with meta_version {meta.VERSION}.")
    else:
        print(f"\n{n_changed} of {len(targets)} files stamped to {meta.VERSION}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
