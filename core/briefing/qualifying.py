"""qualifying.py — emit JSON array of lineage_ids ready for analysis (v10).

Used by the `analyze_bootstrap` step in `.github/workflows/daily.yml` to
populate the per-cluster matrix for the analyze_body / analyze_headline
/ analyze_sources jobs. Reads `data/briefings/<DATE>_<lineage_id>.json`,
excludes sibling artefact files, and keeps briefings whose `n_outlets`
clears a minimum (default 3 — the long-standing gate from build.py).

Output: a JSON array of `lineage_id` strings printed to stdout (single
line, suitable for piping into `$GITHUB_OUTPUT`).

What changed from v9:
  - Iterates lineage_ids (L<hash>) not canonical story_keys
  - Reads `n_outlets` (v10) instead of `n_buckets` (v9)
  - Briefing files are self-describing — no separate _metrics.json
    needed for the gate check

Usage:
  python -m core.briefing.qualifying --date 2026-05-19
  python -m core.briefing.qualifying --date 2026-05-19 --min-outlets 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import core.meta as meta

BRIEFINGS = meta.BRIEFINGS_DIR

SIBLING_SUFFIXES = (
    "_metrics",
    "_within_lang_llr",
    "_within_lang_pmi",
    "_headline",
)


def list_qualifying(date: str, min_outlets: int = 3) -> list[str]:
    """Return sorted list of lineage_ids with briefings for the given date
    whose n_outlets passes the gate."""
    lineage_ids: list[str] = []
    for path in sorted(BRIEFINGS.glob(f"{date}_*.json")):
        name = path.stem
        if any(name.endswith(sfx) for sfx in SIBLING_SUFFIXES):
            continue
        # name = "<date>_<lineage_id>"  → e.g. "2026-05-20_Le4f8a39c1d"
        lineage_id = name[len(date) + 1:]
        if not lineage_id:
            continue
        try:
            b = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        n = b.get("n_outlets")
        if isinstance(n, int) and n >= min_outlets:
            lineage_ids.append(lineage_id)
    return lineage_ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--min-outlets", type=int, default=3)
    args = ap.parse_args()
    ids = list_qualifying(args.date, args.min_outlets)
    print(json.dumps(ids, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
