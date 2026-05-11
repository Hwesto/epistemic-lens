# Analytical canary — design

> Status: design only. Not implemented in PR 4. Implement when the
> project has API budget headroom for the per-pin-bump cost model
> below.

## Why an analytical canary exists alongside the model-drift canary

`canary/run.py` is the **model-drift canary**: 8 frozen synthetic
articles, one frame-classification task each, daily baseline diff
against `canary/baseline/`. It catches "Anthropic served a different
Sonnet snapshot today than yesterday."

That coverage is narrow. It does not catch:

1. **Prompt-edit-induced behavior change** that hashes correctly.
   PR 1's `prompts_hash` in `meta.assert_pinned()` does catch
   unannounced prompt edits, but only at the file-content level. A
   human re-bumping the pin can ship a prompt edit they thought was
   semantically equivalent but isn't.
2. **Schema-edit-induced output drift**. `schemas_hash` catches the
   contract change; it doesn't catch whether the analyzer actually
   conforms to the new contract under representative inputs.
3. **Codebook drift**. Editing `frames_codebook.json` rebumps
   `frames_codebook_hash` — but the model's behavior on a borderline
   article when frame X was renamed or its description tightened is
   only knowable by re-running.
4. **Briefing-pipeline drift**. Changes to tokenization, stopwords,
   signal-text fallback chain — all hash-tracked, all currently
   *uncalibrated* against real-corpus output.

The analytical canary closes this gap by running the **four production
prompts** (body analyze, headline analyze, source attribution,
draft_long) over a small fixed corpus and stamping the result on every
pin bump. Pin bumps that change output beyond a documented tolerance
require a written reason.

## Corpus design

**Size:** 50 articles. Smaller than that and 4-pass output variance
swamps the signal; larger and the per-bump cost becomes prohibitive.

**Language mix:** 5 languages × 10 articles each. English, Italian,
Spanish, French, German. Cover the headline three Latin-script
non-English source languages plus English itself (most common in the
real corpus).

**Content categories (10 articles each across the 5 languages = 5 of
each category):**

- War / security
- Public health
- Economic policy
- Political election / coalition
- Civil-rights / legal

This matches the framing genres the daily pipeline encounters and
gives each LLM pass at least 2 articles per (language × genre) cell
for variance estimation.

**Source:** synthetic, not real news. The model-drift canary's
existing rationale applies: synthetic avoids copyright complications,
gives stable inputs that don't decay as the open web changes, and
keeps the baseline reproducible. Each article is 200-400 words —
long enough to exercise the body-analyze pass's frame-extraction
logic, short enough to keep per-call token cost predictable.

**Storage:** `canary/analytical_corpus.json` — one JSON file with
all 50 articles, each item bearing `id`, `lang`, `genre`,
`signal_text`, plus pre-computed `bucket` / `outlet` placeholders so
the corpus can be drop-in to each pass's expected input shape.

## Per-pass design

Each LLM pass takes different inputs. The canary builds the
minimum-viable input for each pass from the corpus.

### 1. Body analysis

- **Input:** synthesize a single-day briefing from corpus items in
  the same genre across languages (so 5 articles in, one per
  language). Use the actual `analytical/build_briefing.py` to
  produce the briefing — that way briefing-pipeline drift is in
  scope too.
- **Pass:** invoke `.claude/prompts/daily_analysis.md` against the
  briefing.
- **Output to record:** the entire analysis JSON (frames, evidence,
  isolation_top, bottom_line). Validate against `analysis.schema.json`.

### 2. Headline analysis

- **Input:** ten article titles + summaries from the corpus,
  matching one body-analysis target's genre. The headline pass
  reads headlines not bodies.
- **Pass:** `.claude/prompts/headline_analysis.md`.
- **Output to record:** the headline analysis JSON; validate
  against `headline.schema.json` once that schema lands (PR 5+).

### 3. Source attribution

- **Input:** 10 corpus articles that contain at least one direct
  quote. The synthetic corpus authors quotes deliberately —
  named-speaker, unnamed-spokesperson, civilian — to exercise
  every `speaker_type` and `speaker_affiliation_bucket` enum
  value at least once.
- **Pass:** `.claude/prompts/source_attribution.md`.
- **Output to record:** the sources JSON; validate against
  `sources.schema.json` (PR 3).

### 4. Long-form draft

- **Input:** the body analysis from pass 1 (same input → chained
  output).
- **Pass:** `.claude/prompts/draft_long.md`.
- **Output to record:** the long draft; validate against
  `long.schema.json`. Compute a length-stable summary
  (paragraph count, source-citation count, word count, set of
  bucket citations) — full text comparison is too noisy.

## Baseline file format

`canary/analytical_baseline/<meta_version>.json`:

```json
{
  "meta_version": "8.3.0",
  "stamped_at": "2026-05-11T12:00:00Z",
  "model": "claude-sonnet-4-6",
  "corpus_hash": "sha256:...",
  "results": {
    "body_analysis": {
      "<corpus_target_id>": {
        "frames": [{"label": "...", "buckets": [...], "evidence": [...]}],
        "isolation_top": [...],
        "bottom_line": "..."
      }
    },
    "headline_analysis": {"<id>": {...}},
    "source_attribution": {"<id>": {"sources": [...]}},
    "draft_long": {
      "<id>": {
        "paragraph_count": 5,
        "source_citation_count": 12,
        "word_count": 850,
        "buckets_cited": ["italy", "germany", "spain", "usa", "iran_state"]
      }
    }
  }
}
```

One file per pin version. New version starts from scratch; comparison
is `<new_version>` against the previous pinned baseline.

## Gate semantics

On every pin bump, the canary must run before the bump can be tagged
as the new baseline. Comparison against the immediately prior baseline:

- **Body analysis:** frame_id set agreement ≥ 90% per article; primary
  frame_id (the highest-isolation-weighted) match required for at least
  9 of 10 articles per genre.
- **Headline analysis:** sentiment agreement ≥ 90%; framing-tone agreement
  ≥ 80%.
- **Source attribution:** speaker count drift ≤ ±2 per article; speaker
  type distribution within ±10pp.
- **Draft long:** paragraph count within ±2; bucket citation set Jaccard
  ≥ 0.7.

Failing any gate does **not** automatically block the bump. It writes
to `canary/analytical_drift_<meta_version>.md` and requires the bump
reason to explicitly address the drift. Drift is a signal, not a
defect — Anthropic snapshot rollovers, intentional prompt tightening,
and bucket-set additions will all legitimately cause drift. The gate
exists to make drift loud, not to gate-keep.

## Cost model

Per pin bump, on Sonnet:

- 50 articles × 4 passes = 200 LLM calls
- Average input ~800 tokens, output ~600 tokens per call
- Sonnet cost ≈ ($3/$15 per Mtok × 800 + $15/$15 per Mtok × 600) / 1M
  ≈ $0.011 per call
- **Per-bump cost ≈ $2.20**

At 1-2 pin bumps per week during active development, ~$200/year. At
1-2 bumps per month after stabilization, ~$40/year. Compared to the
daily-cron LLM spend, marginal.

The model used for the canary MUST match `meta.CLAUDE["model"]` in
the pin being baselined — otherwise the canary measures the wrong
thing. v8 currently has a deliberate temporary swap to Haiku for the
daily cron; the canary should run on Sonnet because Sonnet is the
production model.

## Run frequency

- **Per pin bump (required):** baseline against immediately prior pin.
- **Weekly (recommended):** re-run against the current pin's baseline.
  Catches mid-week Anthropic-side rollovers without waiting for the
  next bump.
- **NOT daily:** would duplicate the existing model-drift canary and
  cost ~$15/month with diminishing returns.

## CI integration

Two GitHub Actions steps:

1. `canary-analytical-bump.yml` — triggered on every commit that
   modifies `meta_version.json`'s `meta_version` field. Runs
   `python -m canary.analytical_run --bump-mode`. Fails the PR if
   the baseline file is missing from the bump commit.
2. `canary-analytical-weekly.yml` — Sunday cron. Runs against the
   current pin's baseline. Posts drift report as an issue if any
   gate trips.

## Implementation skeleton

```
canary/
├── ANALYTICAL_DESIGN.md           # this file
├── analytical_corpus.json         # 50 articles (build first, once)
├── analytical_run.py              # the runner
├── analytical_baseline/
│   ├── 8.3.0.json
│   ├── 8.4.0.json
│   └── ...
└── analytical_drift_<version>.md  # auto-written when gates trip
```

The runner shares logic with the existing `canary/run.py` (Anthropic
client construction, dry-run handling, baseline IO patterns) but is a
separate module — the model-drift canary stays simple and fast; the
analytical canary is the slower, more expensive one.

## Open implementation questions

1. **Bucket placeholders in the corpus.** The body-analyze pass
   expects each corpus article to have a `bucket` field that maps to
   `feeds.json`. Should the canary corpus use real buckets (which
   change as feeds get added/removed) or synthetic ones (which would
   require `validate_drafts.py` and other consumers to accept
   `canary_<id>` as a bucket)? Lean: real buckets, with the canary's
   corpus_hash including the bucket-set hash at the time of baseline.

2. **Draft-long stability.** Long-form drafts are deliberately
   creative; even with temperature=0 they have high run-to-run
   variance on prose. The summary-statistic comparison (paragraph
   count, citation set Jaccard) is the right shape, but the
   ±-thresholds need calibration against an actual variance study
   (run the canary 5× on the same baseline; record the natural
   variance; set thresholds at 2σ).

3. **Source attribution determinism.** Source attribution is more
   deterministic than draft-long (it has a closed-enum output and a
   substring-grounding constraint), so tighter gates apply. But
   speaker-name normalization is fragile — "Trump" vs "Donald Trump"
   are the same speaker but different strings. The corpus should
   pre-commit to canonical name forms per article and the gate
   should match on canonical forms.

4. **Cross-language sampling.** With only 10 articles per language
   the natural per-pass-per-language variance may exceed the gate
   thresholds. Either pool the language gate or scale thresholds by
   N. Lean: pool to one language-aggregate gate per pass.

5. **Corpus refresh.** When a new genre appears in the live corpus
   (e.g. AI regulation became a frequent story type in 2026), the
   analytical canary's coverage stales. Schedule: review corpus
   coverage every 6 months; add new articles as a minor canary
   version bump (not a meta_version bump — the corpus_hash captures
   it).
