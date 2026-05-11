#!/usr/bin/env python3
"""validate_drafts.py — schema-validate every draft JSON for a date.

Runs as a post-hoc gate in daily.yml after the agent (long.json) and the
template renderers (thread.json, carousel.json) have committed their
outputs. Per-file isolation — one bad draft doesn't block reporting on
the others. Uses meta.validate_schema so Stage 14's schemas_hash gate
applies (a hand-edited schema not paired with a pin bump fails CI here).

Usage:
  python -m publication.validate_drafts                     # all today's drafts
  python -m publication.validate_drafts --date 2026-05-08
  python -m publication.validate_drafts FILE.json [...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
DRAFTS = ROOT / "drafts"

# Maps the trailing `_thread.json` / `_carousel.json` / `_long.json` to its
# schema name. Anything else under drafts/ is ignored.
_FMT_RE = re.compile(r"_(thread|carousel|long)\.json$")


def _kind_of(path: Path) -> str | None:
    m = _FMT_RE.search(path.name)
    return m.group(1) if m else None


def validate_one(path: Path) -> tuple[int, list[str]]:
    """Returns (exit_code, errors). 0 = clean / skipped, 1 = errors found."""
    kind = _kind_of(path)
    if kind is None:
        return 0, []  # not a recognised draft kind
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return 1, [f"corrupt JSON: {e}"]
    except OSError as e:
        return 1, [f"unreadable: {e}"]
    try:
        meta.validate_schema(draft, kind)
    except ValueError as e:
        return 1, [str(e)]
    return 0, []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD. Default: today UTC. Ignored if files given.")
    args = ap.parse_args()

    if args.files:
        targets = list(args.files)
    else:
        date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        targets = sorted(DRAFTS.glob(f"{date}_*.json"))
        if not targets:
            print(f"No drafts to validate for {date}.")
            return 0

    total_errors = 0
    n_checked = 0
    for t in targets:
        if _kind_of(t) is None:
            continue  # silently skip files that aren't a recognised draft kind
        n_checked += 1
        rc, errs = validate_one(t)
        if rc == 0:
            print(f"  OK  {t.name}")
        else:
            print(f"  FAIL  {t.name}")
            for e in errs:
                print(f"    - {e}")
                # GitHub Actions annotation so failures surface in PR/job UI.
                print(f"::error file={t}::schema fail: {e}")
            total_errors += len(errs)

    if total_errors:
        print(f"\n{total_errors} validation error(s) across {n_checked} draft(s).",
              file=sys.stderr)
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
