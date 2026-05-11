"""rollup.py — monthly archive rollup for retention.

Daily artefacts accumulate. Without a retention policy, the live repo is
1–2 GB by year 2 and clones become painful. Phase 2 introduces a monthly
rollup:

  - Snapshots ≥ 90 days old → `archive/rollup/snapshots-YYYY-MM.tar.gz`
  - Briefings ≥ 90 days old → `archive/rollup/briefings-YYYY-MM.tar.gz`
  - Rolled-up files removed from live tree (kept in tarball + git history).

Live tree continues to keep:
  - analyses/   (small JSONs; useful for git-blame on framing decisions)
  - trajectory/ (small JSONs; rolling output)
  - coverage/   (small JSONs; rolling output)
  - meta_version.json + ancestry

The tarball can be optionally attached to a GitHub Release for cold storage
that survives a fresh clone — that step requires `gh` CLI auth and is left
to a human (see human.md). Default behaviour: just bundle locally.

Usage:
  python -m pipeline.rollup --dry-run                      # list candidates
  python -m pipeline.rollup                                # bundle + remove
  python -m pipeline.rollup --window-days 180              # custom retention
  python -m pipeline.rollup --no-remove                    # bundle only, keep originals

Cron: monthly (1st of each month). Idempotent — re-running on already-rolled
months is a no-op.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
SNAPS = ROOT / "snapshots"
BRIEFINGS = ROOT / "briefings"
ROLLUP = ROOT / "archive" / "rollup"

DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _file_date(path: Path) -> date | None:
    m = DATE_RE.match(path.stem)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def find_candidates(window_days: int = 90, today: str | None = None,
                     snaps_dir: Path = SNAPS,
                     briefings_dir: Path = BRIEFINGS) -> dict[str, dict[str, list[Path]]]:
    """Return {category: {YYYY-MM: [path, ...]}} for files older than window_days.

    Categories: 'snapshots', 'briefings'. Months keyed YYYY-MM.
    """
    today_d = date.fromisoformat(today) if today else date.today()
    cutoff = today_d - timedelta(days=window_days)

    out: dict[str, dict[str, list[Path]]] = {
        "snapshots": defaultdict(list),
        "briefings": defaultdict(list),
    }

    if snaps_dir.is_dir():
        for p in sorted(snaps_dir.glob("*.json")):
            d = _file_date(p)
            if d and d < cutoff:
                out["snapshots"][f"{d.year:04d}-{d.month:02d}"].append(p)

    if briefings_dir.is_dir():
        for p in sorted(briefings_dir.glob("*.json")):
            d = _file_date(p)
            if d and d < cutoff:
                out["briefings"][f"{d.year:04d}-{d.month:02d}"].append(p)

    return out


def bundle(month_key: str, paths: list[Path], category: str,
            out_dir: Path = ROLLUP) -> Path:
    """Bundle a list of paths into archive/rollup/<category>-<YYYY-MM>.tar.gz."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = out_dir / f"{category}-{month_key}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for p in paths:
            arcname = f"{category}/{p.name}"
            tar.add(p, arcname=arcname)
    # Stamp a sidecar manifest for quick listing without untarring
    manifest = {
        "category": category,
        "month": month_key,
        "n_files": len(paths),
        "files": sorted(p.name for p in paths),
        "meta_version_at_bundle": meta.VERSION,
    }
    (out_dir / f"{category}-{month_key}.manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return tar_path


def remove_originals(paths: list[Path]) -> int:
    n = 0
    for p in paths:
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--window-days", type=int, default=90,
                    help="Files older than this become rollup candidates (default: 90).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report candidates; do not bundle or remove.")
    ap.add_argument("--no-remove", action="store_true",
                    help="Bundle into tarball but keep originals (idempotent re-runs).")
    ap.add_argument("--today", default=None,
                    help="Override 'today' (YYYY-MM-DD); useful for testing.")
    args = ap.parse_args()

    candidates = find_candidates(window_days=args.window_days, today=args.today)
    n_total = sum(len(paths) for cat in candidates.values() for paths in cat.values())
    if n_total == 0:
        print(f"No files older than {args.window_days} days. Nothing to roll up.")
        return 0

    print(f"Candidates older than {args.window_days} days: {n_total} files")
    for category, by_month in candidates.items():
        for month_key, paths in sorted(by_month.items()):
            print(f"  {category}/{month_key}: {len(paths)} files")
            if args.dry_run:
                for p in paths[:3]:
                    print(f"    - {p.name}")
                if len(paths) > 3:
                    print(f"    ... and {len(paths) - 3} more")

    if args.dry_run:
        print("(dry-run — no changes)")
        return 0

    n_bundled = 0
    n_removed = 0
    for category, by_month in candidates.items():
        for month_key, paths in sorted(by_month.items()):
            tar_path = bundle(month_key, paths, category)
            n_bundled += len(paths)
            print(f"  bundled → {tar_path}")
            if not args.no_remove:
                removed = remove_originals(paths)
                n_removed += removed

    print(f"\nrollup complete: {n_bundled} files bundled into {ROLLUP}/")
    if not args.no_remove:
        print(f"  {n_removed} originals removed from live tree")
    print("\nNext step (human): attach tarballs to a GitHub Release for cold storage.")
    print("  See docs/RETENTION.md for the gh CLI command.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
