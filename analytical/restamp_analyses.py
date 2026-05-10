#!/usr/bin/env python3
"""restamp_analyses.py — refresh meta_version on analysis JSON files.

The agent's prompt asks it to set `meta_version` from the current
`meta_version.json`, but historically agents copied it from
`briefing.meta_version`, which preserves whatever pin was in effect
when the briefing was first generated. This script ensures every
analysis JSON for a given date carries the current pin.

Idempotent. No-op when already stamped correctly.

Usage:
  python restamp_analyses.py                     # all today's analyses
  python restamp_analyses.py --date 2026-05-08   # specific date
  python restamp_analyses.py FILE.json [...]     # specific file(s)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
ANALYSES = ROOT / "analyses"


def restamp(p: Path) -> bool:
    """Set p's meta_version to current pin. Return True if changed.

    Re-validates the file against analysis.schema.json after restamp so
    stamp drift doesn't mask other shape drift; warns and skips on
    schema mismatch rather than raising (defense-in-depth: the
    workflow's validate_analysis step is the load-bearing gate).
    """
    a = json.loads(p.read_text(encoding="utf-8"))
    old = a.get("meta_version")
    if old == meta.VERSION:
        return False
    a["meta_version"] = meta.VERSION
    try:
        meta.validate_schema(a, "analysis")
    except ValueError as e:
        print(f"  ! {p.name}: post-restamp schema mismatch — {e}",
              file=sys.stderr)
        return False
    p.write_text(
        json.dumps(a, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  re-stamped {p.name}: {old} -> {meta.VERSION}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    if args.files:
        targets = list(args.files)
    else:
        date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        targets = sorted(ANALYSES.glob(f"{date}_*.json"))
        if not targets:
            print(f"No analyses for {date}.")
            return 0

    n_changed = 0
    for t in targets:
        if t.suffix != ".json":
            continue
        if restamp(t):
            n_changed += 1
    if n_changed == 0:
        print(f"All {len(targets)} analyses already stamped with meta_version {meta.VERSION}.")
    else:
        print(f"\n{n_changed} of {len(targets)} files re-stamped to {meta.VERSION}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
