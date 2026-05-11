# Three-branch integration plan

## Why this exists

Epistemic Lens has three live branches that need to converge:

- `main` — meta-v2.0.1, the shipped baseline (one LLM pass, Jaccard
  metrics, ad-hoc frame labels, 4 schemas, ~50 tests).
- `claude/review-branch-commercial-MFTEU` — meta-v2.9.0, the
  hardening branch. Same analytical surface as main but with
  `schemas_hash` discipline, 11 pinned schemas, per-file error
  isolation, `stamp_long_drafts.py`, 122 tests, and the Stage 15
  `feed_rot` fix.
- `claude/review-stress-test-06asX` — meta-v8.0.0, the analytical
  branch. LaBSE cosine replaces Jaccard, 4 LLM passes (body + headline
  + sources + draft_long), closed Boydstun/PFC frames codebook,
  HDBSCAN with DBSCAN fallback, cross-day dedup, longitudinal
  aggregator, cross-outlet lag, tilt index, robustness check,
  coverage matrix, replication harness, distribution channels.

The integration goal is to merge v8's analytical capabilities under
the audit branch's hardening discipline. Neither branch ships alone:
v8 carries `main`'s `feed_rot` bug and 7+ uncontracted artifact types;
the audit branch never measured anything new.

All work lands on `claude/merge-analytics-integration-xdbJs`.

## Non-negotiables

These must survive the merge or the result has known regressions.
They are not design choices; each is a correctness fix or a
load-bearing discipline.

1. **Stage 15 `feed_rot` fix.** Both `main` and v8 have inverted
   decline-detection — the code flags *growing* feeds as declining.
   The audit branch has the fix plus 4 regression tests covering
   both directions. Cherry-pick from the audit branch.
2. **`schemas_hash` retrofit.** v8 ships 7+ new artifact types with
   no schemas. Without `schemas_hash` in `meta.check_drift()`, schema
   edits silently bypass CI. Write the 11 missing schemas; add
   `schemas_hash`; require `meta_version` on every artifact.
3. **Generalize `stamp_long_drafts.py`.** v8 produces 5+ new unstamped
   artifact types (headline analyses, divergence, sources, robustness,
   lag, tilt, baseline). Same gap the audit fixed for long-form drafts.
4. **Per-file error isolation in v8's new modules.** `cross_outlet_lag`,
   `tilt_index`, `headline_body_divergence`, `robustness_check`, etc.
   Pattern: narrow `except` to
   `(json.JSONDecodeError, OSError, ValueError, KeyError)`; print
   `FAIL` per file; attempt all targets; non-zero exit if any failed.
5. **`json.loads(path.read_text(...))` everywhere.** v8 has
   `json.load(open(...))` in new modules. ResourceWarning hygiene.
6. **`TestBuildIndex` extension.** v8 added 7 new `copy_*()` functions
   in `build_index.py`. The audit's `TestBuildIndex` (5 tests) must
   grow to cover them.
7. **Stage 12 `latest.json` fix preserved.** The audit's fix reads
   from disk, not from the invocation list; verify v8's new
   `copy_*()` calls didn't reintroduce the regression on
   `build_index --date <older>`.

## Resolved design decisions

Six open questions came out of the handoff. Decisions and rationale:

### 1. Analytical canary

**Decision: build it. Sonnet. 50-article frozen corpus, all 4 passes,
stamped per pin bump.**

Without a canary, `schemas_hash` proves inputs are pinned but never
proves outputs reproduce. The canary uses the same model as
production because otherwise it doesn't prove what ships. Production
will return to Sonnet after the haiku cost-testing window, so the
canary is Sonnet.

Cost is real (~50 articles × 4 passes per bump). Mitigation: the
canary only re-runs passes whose `prompts_hash` actually changed,
gated by inspecting the diff in `meta_version.json`.

### 2. Distribution channels — auto-fire or approval-gate?

**Decision: approval-gate, scripted.**

The cron stages drafts to `distribution/pending/<date>/`; a one-liner
`python -m distribution.publish --approve <id>` posts to X or
uploads to YouTube. Schema validation and the canary verify the
artifact, but they don't catch the failure mode where a defensible
JSON analysis reads badly compressed to 280 chars or 60 seconds of
narration. The compression to social copy is where embarrassment
lives.

If approval-gating becomes a chore, revisit. The default is
defensibility over throughput on the public-channels surface only.
The analytical pipeline itself stays zero-touch.

### 3. Article-level provenance in longitudinal

**Decision: add it. 10pp movement threshold.**

When frame share moves day-over-day, `trajectory.json` records
which article URLs drove the movement. Without it, every interesting
finding generates an unanswerable "which articles?" follow-up.

Threshold caps bloat: only record drivers when `|Δshare| > 10pp`
on that day-pair. Schema extension is backward-compatible
(`drivers` is optional).

### 4. Tilt-index anchor

**Decision: pair `wire` with `bucket_mean`. Deferrable to PR 7.**

Single-anchor "tilt vs wire" privileges Reuters/AFP/AP as a hidden
truth-baseline. Two anchors triangulate. Cost is two columns in
the rendered output instead of one.

### 5. HDBSCAN swap timing

**Decision: parallel diagnostic for one week post-merge, then decide.**

The diagnostic runs DBSCAN alongside HDBSCAN, recording cluster
count, silhouette, and a sample of stories where they disagree.
Zero production impact. HDBSCAN can be reverted at the next minor
bump if the numbers don't support it.

Not a merge blocker.

### 6. Boydstun codebook caveat

**Decision: add a three-sentence `## Codebook limitations` section
to METHODOLOGY.md.**

The PFC 15-frame set was derived from US domestic-political
coverage. It maps cleanly there; it's stretched (not invalid, but
stretched) on, e.g., Italian Vatican stories or Japanese diplomatic
coverage. The free-text `sub_frame` is the escape valve, but
naming the gap is cheap honesty.

## Withdrawn proposals

Two earlier proposals were retracted in conversation; recording
them so they don't get re-litigated:

- **Jaccard alongside LaBSE.** Cross-language Jaccard on raw tokens
  measures language identity, not framing. Italian *guerra* vs
  English *war* registers as low similarity regardless of editorial
  framing. The correct decomposition is what v8 already has: LaBSE
  for cross-language semantic similarity, within-language LLR/PMI
  for same-language lexical distinctness.
- **Three-way body/headline/social divergence.** The thread and
  carousel drafts are deterministic templates over the body
  analysis JSON. Social framing ≈ body framing by construction.
  Three-way only works if the third view is independently produced
  (a third LLM pass), which is not on the table. Stick with v8's
  body↔headline two-way divergence.

## PR plan

| PR | Content | Pin bump | Risk |
|---|---|---|---|
| 0 | Stage 15 `feed_rot` fix + ResourceWarning sweep + per-file isolation in v8's new modules | patch | zero analytical risk |
| 1 | `schemas_hash` retrofit + 11 new schemas + `meta.check_drift` extension + `TestSchemaCorpus` + `meta_version` backfill on unstamped artifacts | minor | zero analytical change |
| 2 | 4-state coverage matrix (extend v8's binary `coverage_matrix.py` by joining with daily health to derive silence / dark / errored) | minor | adds derived metric |
| 3 | Source attribution enum enrichment: add `speaker_affiliation_bucket`, `speaker_affiliation_kind` to the prompt + schema | minor | small prompt change |
| 4 | Analytical canary — **design doc only** (`canary/ANALYTICAL_DESIGN.md`). Implementation deferred: ~$2.20 per pin bump on Sonnet × ~50 articles × 4 passes. v8's existing `canary/run.py` model-drift canary continues to cover Anthropic snapshot drift; PR 1's `prompts_hash` + `schemas_hash` cover prompt/schema edits at the file level. The analytical canary closes the gap of *hash-clean but behavior-different* edits and is ready to implement when API budget allows. | docs | docs-only |
| 5 | Article-level provenance in `longitudinal.py` (drivers with 10pp threshold) | patch | extends existing artifact |
| 6 | Distribution approval-gate (`distribution/pending/` + `publish --approve` CLI) | none | editorial-policy change |
| 7 | Tilt-index second anchor (`bucket_mean` alongside `wire`) | minor | honest-naming improvement |
| 8 | Boydstun caveat in METHODOLOGY.md + HDBSCAN parallel diagnostic harness | patch | docs + diagnostic only |

### PR 0 — Foundation hardening

**Scope:** cherry-pick the `feed_rot` fix; sweep `json.load(open(...))`
→ `json.loads(Path.read_text(...))` in v8's new modules; apply the
audit's per-file isolation pattern to `cross_outlet_lag`,
`tilt_index`, `headline_body_divergence`, `robustness_check`,
`coverage_matrix`, and the longitudinal aggregator.

**Files:** `pipeline/feed_rot_check.py`, plus v8's new analytical
modules. Add the 4 audit regression tests for `feed_rot`.

**Exit:** all existing tests pass; `feed_rot` regression suite green;
no `ResourceWarning` from the v8 modules under `python -W error`.

**Dependencies:** none. Start here.

### PR 1 — Schema discipline

**Scope:** write schemas for coverage, trajectory, sources,
sources_aggregate, lag, baseline, tilt, robustness, headline,
divergence, corrections. Add `schemas_hash` to
`meta.check_drift()`. Require `meta_version` on every artifact
schema. Extend `TestSchemaCorpus` to cover the new schemas.
Generalize `stamp_long_drafts.py` to stamp all new artifact types
that lack `meta_version`.

**Files:** `docs/api/schema/*.json` (new), `meta.py`,
`pipeline/stamp_long_drafts.py` (rename/generalize), `tests/`.

**Exit:** `meta.check_drift()` fails any uncommitted schema edit;
every produced artifact carries `meta_version`; `TestSchemaCorpus`
covers all 22 artifact types.

**Dependencies:** PR 0.

### PR 2 — Coverage matrix derivation

**Scope:** v8 has a binary covered/not matrix. Join with the daily
health output to derive the 4-state matrix: `covered` / `silent`
(no story this bucket today) / `dark` (feed not reached) /
`errored` (feed reached, parse failed).

**Files:** `analytical/coverage_matrix.py`, `coverage.schema.json`,
frontend rendering.

**Exit:** today's coverage section on the site distinguishes
silence from feed errors.

**Dependencies:** PR 1 (needs `coverage.schema.json`).

### PR 3 — Source attribution enum enrichment

**Scope:** add `speaker_affiliation_bucket`
(`state / political / civilian / wire / corporate / academic / NGO`)
and `speaker_affiliation_kind` (free) to the source-attribution
prompt and schema. Re-stamp `prompts_hash`.

**Files:** `.claude/prompts/source_attribution.md`,
`docs/api/schema/sources.schema.json`, `meta_version.json`.

**Exit:** new fields appear on the per-story Voices page; LLR
distinctiveness can be computed at the affiliation-bucket level
in PR 5+.

**Dependencies:** PR 1.

### PR 4 — Analytical canary

**Scope:** freeze a 50-article, 5-language corpus to
`canary/corpus/<sha>.jsonl`. Build `canary/run.py` that executes
all 4 LLM passes on the corpus using whatever model
`meta_version.json` declares (Sonnet under normal production).
Stamp output to `canary/<meta_version>_result.json`. CI gate:
any pin bump that changes `prompts_hash` or schema content must
either include a fresh canary result or fail.

**Files:** `canary/` (new directory), `.github/workflows/canary.yml`,
`meta.py` (canary verification helper).

**Exit:** running `python -m canary.run` reproduces the stamped
result for the current pin bit-exact (within LLM nondeterminism
tolerance — record temperature=0 and seed where supported).

**Dependencies:** PR 1.

### PR 5 — Article-level provenance

**Scope:** extend `trajectory.schema.json` with optional
`drivers: [{url, frame_id, weight, direction}]` per day-pair entry.
Populate drivers only when `|Δshare| > 10pp` on that day-pair.
Render in the trajectory section of the site.

**Files:** `analytical/longitudinal.py`, `trajectory.schema.json`,
frontend.

**Exit:** any trajectory finding with significant movement is
clickable to the articles that drove it.

**Dependencies:** PR 1.

### PR 6 — Distribution approval-gate

**Scope:** strip auto-invocation of `x_poster.py` and
`youtube_shorts.py` from the cron. Cron emits
`distribution/pending/<date>/<id>.{thread,short}.json`. New CLI
`python -m distribution.publish` with `--list`, `--approve <id>`,
`--reject <id>`.

**Files:** `distribution/`, `.github/workflows/daily.yml`,
`distribution/publish.py` (new).

**Exit:** cron produces drafts but never posts; explicit approval
required for any public emission.

**Dependencies:** PR 0 (hardening) and PR 1 (schemas — the pending
drafts need a contract).

### PR 7 — Tilt-index second anchor

**Scope:** extend `tilt.schema.json` with
`anchor: "wire" | "bucket_mean"`. Emit both per-outlet rows.
Render side-by-side.

**Files:** `analytical/tilt_index.py`, `tilt.schema.json`, frontend.

**Exit:** every per-outlet tilt is shown against both anchors; no
implicit truth-baseline.

**Dependencies:** PR 1.

### PR 8 — Honesty pass

**Scope:** add `## Codebook limitations` to METHODOLOGY.md
(3 sentences, citing Boydstun & Card 2014, noting cross-cultural
stretch). Add `pipeline/cluster_diagnostic.py` running DBSCAN
alongside HDBSCAN, writing `diagnostic/<date>_cluster_compare.json`.
No production impact.

**Files:** `docs/METHODOLOGY.md`, `pipeline/cluster_diagnostic.py`
(new), `.github/workflows/daily.yml` (diagnostic step).

**Exit:** after one week of diagnostic data, the cluster algorithm
choice can be confirmed or reverted with evidence.

**Dependencies:** none on PRs 0–7 strictly, but lands last.

## Pre-merge verification

Before PR 0 lands, run the verification pass to confirm the
handoff's factual claims about the three branches:

```bash
git fetch origin main claude/review-branch-commercial-MFTEU claude/review-stress-test-06asX
git log --oneline origin/main..origin/claude/review-branch-commercial-MFTEU
git log --oneline origin/main..origin/claude/review-stress-test-06asX
git diff --stat origin/main..origin/claude/review-branch-commercial-MFTEU
git diff --stat origin/main..origin/claude/review-stress-test-06asX
```

Also: let the next `claude-haiku-4-5` cron complete end-to-end on
the v8 branch. That is the live evidence v8 actually works. PRs 0
and 1 then ride on a known-working baseline with zero analytical
risk.
