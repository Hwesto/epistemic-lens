# Replication

Reconstruct the analytical output of any past day from its snapshot file
under any methodology pin. This is what makes the project's "longitudinal
comparability" claim falsifiable — anyone can re-run the deterministic
pipeline locally and check the published numbers.

## Quick start

```bash
python replay.py --date 2026-05-08
```

This re-runs every deterministic step (dedup, coverage matrix, daily health,
briefing builder, metrics, longitudinal aggregator) against
`snapshots/2026-05-08.json` and writes the artefacts to disk under the
**current** methodology pin. Compare to the originals via `git diff`.

## What replay does and doesn't run

**Does run** (deterministic, no network, no LLM):

| Step | Module | Inputs | Outputs |
|---|---|---|---|
| dedup | `pipeline.dedup` | `snapshots/<DATE>.json` | annotated snapshot, `<DATE>_dedup.json`, `cross_day_dedup_state.json` |
| coverage_matrix | `pipeline.coverage_matrix` | snapshot + `canonical_stories.json` + `feeds.json` | `coverage/<DATE>.json` |
| daily_health | `pipeline.daily_health` | snapshot | `<DATE>_health.json` |
| build_briefing | `analytical.build_briefing` | snapshot + `canonical_stories.json` | `briefings/<DATE>_<story>.json` |
| build_metrics | `analytical.build_metrics` | briefings | `briefings/<DATE>_<story>_metrics.json` |
| longitudinal | `analytical.longitudinal` | analyses (all dates) | `trajectory/<story>.json` |

**Does NOT run** (non-deterministic):

- `pipeline.ingest` — RSS pull is network-dependent and time-dependent.
- `pipeline.extract_full_text` — article fetch is network-dependent.
- `analyze` — LLM call (OAuth required, model output non-deterministic across snapshots).
- `draft` (long-form) — LLM call.

To replay an analysis, you'd need an `analyses/<DATE>_<story>.json` produced
by an LLM pass. That's a separate (non-replayable) artefact. Replay computes
metrics, coverage, and trajectories — the deterministic surrounding layer.

## Pin-mismatched replay

If the current pin differs from the one used to produce the original
artefacts, replay warns:

```bash
python replay.py --date 2026-05-08 --pin meta-v7.0.0
# ⚠ pin mismatch: current is meta-v7.1.0, replay requested meta-v7.0.0
#   Replay will run under meta-v7.1.0; output will not match meta-v7.0.0.
```

Replay does **not** time-travel the pin. To replay under a past pin,
`git checkout` the commit that carried that pin first:

```bash
git checkout meta-v7.0.0
python replay.py --date 2026-05-08
```

## Selecting a subset of steps

```bash
python replay.py --date 2026-05-08 --steps coverage_matrix,build_metrics
```

Useful when only one step changed and you want to verify its output
isolation.

## Dry run

```bash
python replay.py --date 2026-05-08 --dry-run
```

Prints the commands that would run; exits 0 without executing. Cheap pre-flight.

## Diffing replayed vs. original artefacts

```bash
python replay.py --date 2026-05-08
git status briefings/ coverage/ snapshots/
git diff briefings/2026-05-08_*_metrics.json
```

A clean diff (`git diff` empty) is the canonical "this pin reproduces"
result. A non-empty diff means the pinned inputs (including code) have
drifted from when the original artefacts were produced — which `git
checkout meta-vX.Y.Z` should resolve.

## When to use replay

- **CI-gated bump verification.** After `baseline_pin.py --bump <level>`,
  run `replay.py` against representative dates to confirm the bump's
  output change is exactly what was expected.
- **External replication.** A reviewer asks "show your working" — replay
  + diff is the audit trail.
- **Forensics on a regression.** A metric value looks wrong in today's
  artefact; replay against yesterday's snapshot under today's pin tells
  you whether the bug is in the pipeline or in the input data.

## Limitations

- Replay needs the snapshot file. Snapshots ≥ 90 days old are eventually
  rolled into release archives (see `docs/RETENTION.md`); replaying a
  rolled-up date requires downloading the archive first.
- Replay assumes the pinned dependencies are installed. `pip install -r
  requirements.txt` before running.
- Replay does not regenerate analyses; those require LLM access.
