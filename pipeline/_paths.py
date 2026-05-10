"""Snapshot path conventions — single source for the
`YYYY-MM-DD.json without sidecars` filter.

Every pipeline stage (extract, dedup, daily_health) and the analytical
build_briefing all need to find the latest canonical snapshot, ignoring
sidecar files that share the date prefix (`_convergence`, `_similarity`,
`_health`, `_pull_report`, etc.). Each used to maintain its own
hardcoded denylist; this module centralises the rule as a positive
include pattern (stem must be exactly an ISO date).
"""
from __future__ import annotations

import re
from pathlib import Path

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_snapshot(path: Path) -> bool:
    """True for canonical snapshot files (`YYYY-MM-DD.json`).

    Sidecars whose stem extends the date with an underscore suffix
    (`2026-05-09_health.json`, etc.) return False.
    """
    return path.suffix == ".json" and bool(_DATE_RE.match(path.stem))


def list_snapshots(snaps_dir: Path) -> list[Path]:
    """All canonical snapshots in the directory, sorted chronologically
    (which matches lex-sort because the stem is ISO date)."""
    return sorted(p for p in snaps_dir.glob("[0-9]*.json") if is_snapshot(p))


def latest_snapshot(snaps_dir: Path) -> Path | None:
    """Most recent canonical snapshot, or None if the directory is empty."""
    cands = list_snapshots(snaps_dir)
    return cands[-1] if cands else None
