#!/usr/bin/env python3
"""replay.py — reconstruct the deterministic post-ingest pipeline for a past date.

Re-runs every pipeline + analytical step that does NOT require live network
or LLM, against an existing snapshot file, so that analytical output can be
regenerated under a (possibly different) methodology pin. Useful for:

  - Methodology backfills: bumped the pin, want to recompute metrics under
    the new pin without waiting for the next cron.
  - Reproducibility checks: external reviewer asked "show me you'd get the
    same answer if I ran this myself."
  - Bug-fix forensics: a step changed; replay it and diff the artefacts.

What replay DOES re-run (deterministic):
  - pipeline.dedup
  - pipeline.coverage_matrix          (Phase 1)
  - pipeline.daily_health
  - analytical.build_briefing
  - analytical.build_metrics
  - analytical.longitudinal           (Phase 1; reads analyses/, no LLM)

What replay DOES NOT re-run:
  - pipeline.ingest                   (network — not deterministic)
  - pipeline.extract_full_text        (network — not deterministic)
  - analyze                           (LLM — not deterministic, requires OAuth)
  - draft (long-form)                 (LLM — same)
  - publication.render_thread/carousel (deterministic, but driven by analyses;
                                       run separately if needed)

Usage:
  python replay.py --date 2026-05-08
  python replay.py --date 2026-05-08 --pin meta-v7.1.0   # warn if mismatched
  python replay.py --date 2026-05-08 --steps dedup,coverage_matrix
  python replay.py --date 2026-05-08 --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
SNAPS = ROOT / "snapshots"

# Step name → list of CLI commands to run. Order matters: each step writes
# artefacts the next step depends on. Steps marked `network=True` are NOT
# included here — replay is deterministic by definition.
STEPS = [
    ("dedup",            ["python", "-m", "pipeline.dedup", "{snapshot}"]),
    ("coverage_matrix",  ["python", "-m", "pipeline.coverage_matrix",
                          "--snapshot", "{snapshot}"]),
    ("daily_health",     ["python", "-m", "pipeline.daily_health",
                          "--snapshot", "{snapshot}"]),
    ("build_briefing",   ["python", "-m", "analytical.build_briefing",
                          "--date", "{date}"]),
    ("build_metrics",    ["python", "-m", "analytical.build_metrics",
                          "--date", "{date}"]),
    ("longitudinal",     ["python", "-m", "analytical.longitudinal"]),
]


def resolve_snapshot(date: str) -> Path:
    p = SNAPS / f"{date}.json"
    if not p.exists():
        raise FileNotFoundError(f"No snapshot found at {p}")
    return p


def run_step(name: str, cmd_template: list[str], context: dict[str, str],
             dry_run: bool) -> tuple[bool, str]:
    """Execute one step. Returns (success, output_or_reason)."""
    cmd = [c.format(**context) for c in cmd_template]
    if dry_run:
        return True, f"would run: {' '.join(cmd)}"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            return True, (r.stdout or "").strip().splitlines()[-1] if r.stdout else "ok"
        return False, f"exit {r.returncode}: {(r.stderr or r.stdout)[:300]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", required=True, help="YYYY-MM-DD; snapshot must exist on disk.")
    ap.add_argument("--pin", default=None,
                    help="Optional `meta-vX.Y.Z` to verify against current pin.")
    ap.add_argument("--steps", default=None,
                    help="Comma-separated subset (default: all).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print commands; don't execute.")
    args = ap.parse_args()

    # Pin check
    current = "meta-v" + meta.VERSION
    if args.pin and args.pin != current:
        print(f"⚠ pin mismatch: current is {current}, replay requested {args.pin}",
              file=sys.stderr)
        print(f"  Replay will run under {current}; output will not match {args.pin}.",
              file=sys.stderr)
    else:
        print(f"replay under {current}")

    # Snapshot
    try:
        snap_path = resolve_snapshot(args.date)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    context = {"date": args.date, "snapshot": str(snap_path)}
    requested = set(args.steps.split(",")) if args.steps else None
    selected = [(n, c) for n, c in STEPS if not requested or n in requested]
    if not selected:
        print(f"error: no steps matched {args.steps}", file=sys.stderr)
        return 1

    print(f"running {len(selected)} step(s) for {args.date}:")
    n_ok = 0
    n_fail = 0
    for name, cmd in selected:
        ok, msg = run_step(name, cmd, context, args.dry_run)
        marker = "✓" if ok else "✗"
        print(f"  {marker} {name:18s} {msg}")
        if ok:
            n_ok += 1
        else:
            n_fail += 1

    print(f"\nreplay {'(dry-run) ' if args.dry_run else ''}complete: "
          f"{n_ok} ok, {n_fail} failed")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
