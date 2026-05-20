"""list_qualifying_stories.py — emit JSON array of stories ready for analysis.

PR1. Used by the `analyze_bootstrap` step in `.github/workflows/daily.yml`
to populate the per-story matrix for the analyze_body / analyze_headline /
analyze_sources jobs. Replaces the previous one-big-Sonnet-session
architecture where all stories shared a single context window and a
single 60-min budget.

Reads `briefings/<DATE>_*.json`, excludes the sibling artefacts
(`_metrics.json`, `_within_lang_llr.json`, `_within_lang_pmi.json`),
and keeps stories whose matching `_metrics.json` reports
`n_buckets >= min_buckets` (default 3 — the long-standing gate from
`build_briefing.py`).

Output: a JSON array of `story_key` strings printed to stdout (single
line, suitable for piping into `$GITHUB_OUTPUT`).

Usage:
  python -m core.briefing.qualifying --date 2026-05-19
  python -m core.briefing.qualifying --date 2026-05-19 --min-buckets 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import core.meta as meta

BRIEFINGS = meta.BRIEFINGS_DIR

# Sibling artefact suffixes the build pipeline writes alongside each
# briefing. None of these are themselves story briefings; filter them out
# of the matrix bootstrap.
SIBLING_SUFFIXES = (
    "_metrics",
    "_within_lang_llr",
    "_within_lang_pmi",
)


def list_qualifying(date: str, min_buckets: int = 3) -> list[str]:
    """Return sorted list of story_keys with briefings for the given date
    whose n_buckets passes the gate."""
    stories: list[str] = []
    for path in sorted(BRIEFINGS.glob(f"{date}_*.json")):
        name = path.stem
        if any(name.endswith(sfx) for sfx in SIBLING_SUFFIXES):
            continue
        # name = "<date>_<story_key>"
        story_key = name[len(date) + 1:]
        if not story_key:
            continue
        metrics_path = BRIEFINGS / f"{date}_{story_key}_metrics.json"
        if not metrics_path.exists():
            continue
        try:
            m = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        n = m.get("n_buckets")
        if isinstance(n, int) and n >= min_buckets:
            stories.append(story_key)
    return stories


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True,
                    help="Date in YYYY-MM-DD format.")
    ap.add_argument("--min-buckets", type=int, default=3,
                    help="Minimum n_buckets gate (default 3).")
    args = ap.parse_args()
    stories = list_qualifying(args.date, args.min_buckets)
    # Compact JSON on a single line — GitHub Actions `$GITHUB_OUTPUT`
    # expects single-line key=value pairs.
    print(json.dumps(stories, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
