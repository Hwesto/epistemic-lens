# Daily framing analyses

This directory holds **automated** outputs of the daily Claude analysis pass.
Files are written by the `analyze` job in `.github/workflows/daily.yml` and
named `<DATE>_<story_key>.md`.

Pipeline:

  ingest → extract → dedup → build_briefing → build_metrics → claude analysis

Numbers come from `briefings/<DATE>_<story_key>_metrics.json` (precomputed
by `build_metrics.py`). The Claude pass uses them verbatim — it does not
recompute or estimate counts.

Prompt: `.claude/prompts/daily_analysis.md`.

## Spec vs. output

`docs/HORMUZ_CORRELATION.md` is the **specification** — a hand-curated
exemplar of the structure, depth, and style every automated analysis here
should match. It is **not** the first automated output and is kept in
`docs/` to avoid that confusion.

The first true cron-generated analysis will appear here once the daily
`analyze` job runs successfully (requires `CLAUDE_CODE_OAUTH_TOKEN` repo
secret — see `docs/OPERATIONS.md`).
