# Retention policy

Daily artefacts accumulate. Without retention, the live repo crosses 1 GB
in year 1 and clones become painful for new contributors. The retention
policy keeps the live tree to small, frequently-edited artefacts and rolls
older ingest data into compressed archives.

## What stays in the live tree (forever)

| Path | Why it stays |
|---|---|
| `analyses/` | Small JSONs (~10 KB each); benefit from `git-blame` on framing decisions. The canonical analytical artefact. |
| `trajectory/` | Small JSONs; rolling output; consumed by frontend. |
| `coverage/` | Small JSONs (~50 KB/day); rolling output; consumed by frontend. |
| `meta_version.json` + ancestry | The pin file; tiny; the project's spine. |
| `feeds.json`, `canonical_stories.json`, `bucket_quality.json`, `bucket_weights.json`, `frames_codebook.json`, `stopwords.txt` | Pinned inputs; small; edited deliberately. |
| `cross_day_dedup_state.json` | 30-day rolling state; bounded size. |
| Code (`pipeline/`, `analytical/`, `publication/`, `web/`, `distribution/`) | Source. |
| `archive/` (excluding `archive/rollup/`) | Historical baselines + planning docs. |

## What gets rolled up (and removed from live tree)

| Path | Why it rolls | Window |
|---|---|---|
| `snapshots/<YYYY-MM-DD>.json` (and `_health`, `_dedup`, `_convergence`, `_similarity`, `_prompt` siblings) | Large (~5–20 MB each). The canonical raw-RSS artefact for the day; needed for replay but rarely after 90 days. | ≥ 90 days old |
| `briefings/<YYYY-MM-DD>_<story>.json` and `_metrics.json` | Medium (~50–500 KB each); per-story corpus + computed metrics. Replayable from snapshot. | ≥ 90 days old |

Rolled-up files become:

```
archive/rollup/
  snapshots-YYYY-MM.tar.gz
  snapshots-YYYY-MM.manifest.json
  briefings-YYYY-MM.tar.gz
  briefings-YYYY-MM.manifest.json
```

The tarballs stay in the live tree (small enough — typical month-of-snapshots
≈ 100 MB compressed). The manifest sidecar lists what's inside so a reader
doesn't need to untar to know.

## Cold storage (optional, off-repo)

For projects with year-3+ data the tarballs themselves get heavy.
Recommended:

1. Attach each `archive/rollup/*.tar.gz` to a GitHub Release named
   `data-YYYY-MM`, then remove the tarball from the repo (keep the
   manifest sidecar).
2. Reverse step (download tarball before replay) is documented inline:

   ```bash
   # Replay a rolled-up date
   gh release download data-2025-01 --pattern 'snapshots-2025-01.tar.gz'
   tar -xzf snapshots-2025-01.tar.gz -C snapshots/
   python replay.py --date 2025-01-15
   ```

This step is **manual** — `gh release create` requires `gh` CLI auth which
is best handled outside the cron. See `human.md`.

## Running the rollup

```bash
# Dry-run: list candidates without bundling
python -m pipeline.rollup --dry-run

# Default: bundle ≥90-day-old files into archive/rollup/, remove originals
python -m pipeline.rollup

# Custom retention window (e.g. 180 days for stricter retention)
python -m pipeline.rollup --window-days 180

# Bundle without removing originals (idempotent; useful for testing)
python -m pipeline.rollup --no-remove
```

Cron: monthly, 1st of month, after the regular daily ingest. The current
`.github/workflows/daily.yml` does not run rollup directly; recommended is
a separate `monthly-rollup.yml` workflow:

```yaml
# .github/workflows/monthly-rollup.yml
name: Monthly Rollup
on:
  schedule:
    - cron: '0 8 1 * *'  # 1st of month, 08:00 UTC
  workflow_dispatch:
jobs:
  rollup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt
      - run: python -m pipeline.rollup
      - run: |
          set -e
          git config user.name "epistemic-lens-bot"
          git config user.email "bot@epistemic-lens"
          git add archive/rollup/ snapshots/ briefings/
          if git diff --cached --quiet; then exit 0; fi
          git commit -m "monthly rollup: archive snapshots+briefings ≥ 90 days old"
          git push
```

The cron is **optional** — the rollup module also runs cleanly from a
local checkout. Adding the workflow is left as a follow-up.

## Limitations

- `replay.py` against a rolled-up date requires un-tarring the archive
  first (the README example above shows the gh-fetch + tar -xzf pattern).
- The rollup is one-way: re-tarring after un-tarring may produce a
  different bytes-identical archive (file ordering, gzip metadata). Use
  the manifest sidecar's `files` list as the authoritative content
  declaration.
- Cross-day dedup state (`cross_day_dedup_state.json`) is bounded by its
  own 30-day window and not subject to rollup.
