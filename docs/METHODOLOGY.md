# Methodology pin policy

## Why this exists

Epistemic Lens makes longitudinal claims: "Italy uniquely uses *guerra*
for this story," "Hormuz had 14 buckets day 1, 6 by day 7," "Saudi
outlets cover Egypt's response, not Iran's." These claims are
defensible only if the **way** we computed them is stable across days.
Change the tokenizer mid-week and "Italy uniquely uses *guerra*"
becomes a measurement artifact, not a finding.

The methodology pin makes drift impossible-by-accident: every input
that affects analytical output is hashed in `meta_version.json`, every
artifact is stamped with `meta_version`, and CI fails any PR where the
declared hashes no longer match the live files.

## What is pinned

`meta_version.json` declares hashes for:

| File | Hash key | Why it matters |
|---|---|---|
| `feeds.json` | `feeds.hash` | Adding/removing feeds changes bucket vocabularies and which stories are detected. |
| `stopwords.txt` | `tokenizer.stopwords_hash` | Words that survive filtering are the entire signal in bucket-exclusive vocab metrics. |
| `canonical_stories.json` | `canonical_stories_hash` | Patterns that decide which articles cluster into a "story." |
| `.claude/prompts/*.md` | `claude.prompts_hash` | LLM analyses are downstream of these prompts word-for-word. |

It also declares (without hashing) the structural constants:

- **Embedding model** — `paraphrase-multilingual-MiniLM-L12-v2` (clustering)
- **Clustering** — HDBSCAN over cosine distance, min_cluster_size=3
  (legacy DBSCAN params kept in the pin as a fallback)
- **Tokenizer** — Unicode-aware regex `\p{L}{4,}`, plural normalization
  `("ies", "es", "s")`, multilingual stopwords union (NLTK + spaCy).
  Operates on original `signal_text` in its source language; used for
  bucket-exclusive vocabulary only.
- **Cross-bucket similarity** — LaBSE bucket-mean cosine on original
  `signal_text` (no translation pivot — LaBSE is multilingual by
  construction). Surfaced as `pairwise_similarity` and `isolation`
  with `mean_similarity` per bucket. Bucket-exclusive vocab uses the
  pinned tokenizer with `doc_freq <= 1 AND count >= 3`; the analyzer
  is instructed to flag language-confounded distinctive terms.
- **Signal text fallback** — body if ≥500 chars, summary if ≥60 chars,
  title otherwise; max 2500 chars
- **Extraction** — top 20 clusters + 3 per feed, 4000 char body cap,
  15s timeout, Wayback fallback, Common Crawl News fallback for
  paywalled feeds
- **Claude model** — `claude-sonnet-4-6` (daily analysis pass)

## How to change something

Choose the level of bump that matches the impact, run `baseline_pin.py
--bump <level>`, commit, tag.

### Patch (1.0.0 → 1.0.1)

For changes that **don't affect output**: refactors, comments, logging,
renamed variables, doc fixes.

```bash
python baseline_pin.py --bump patch
git add meta_version.json
git commit -m "meta: bump to 1.0.1 — refactor"
```

No tag needed; patch bumps don't affect longitudinal data.

### Minor (1.0.0 → 1.1.0)

For **forward-compatible** changes: a new canonical story, an added
feed, a new metric appended to the metrics output, an added stopword.
Existing artifacts remain valid; new artifacts contain more.

```bash
python baseline_pin.py --bump minor --reason "added 'gaza_ceasefire' canonical story"
git add meta_version.json canonical_stories.json
git commit -m "meta: bump to 1.1.0 — added gaza_ceasefire story"
git tag meta-v1.1.0
git push --follow-tags
```

### Major (1.0.0 → 2.0.0)

For **longitudinal-breaking** changes: switching the embedding model,
swapping the cross-bucket similarity (e.g. the v7.0.0 transition from
TF-IDF on translated pivot to LaBSE cosine on originals), removing
buckets, rewriting prompts, removing stopwords, lowering
`min_body_chars_for_body`. After a major bump, claims that span pre-
and post-bump data must explicitly say so.

```bash
python baseline_pin.py --bump major --reason "switched to BGE multilingual embedding"
git add meta_version.json
git commit -m "meta: bump to 2.0.0 — embedding model change"
git tag meta-v2.0.0
git push --follow-tags
```

The repo tag (`meta-v2.0.0`) lets anyone re-run analyses under the
old config later.

## How CI enforces it

`baseline_pin.py --check` is a required status check on every push to
`main` and every PR. It re-hashes the live files and compares to
`meta_version.json`. If they drift, the check fails with a message
telling you which file changed and which level of bump fits.

The `validate-meta` job runs in ~10 seconds with no Python deps beyond
the standard library. It cannot be silently bypassed: the branch
ruleset for `main` makes it required.

## How artifacts are tagged

Every artifact (snapshot, briefing, metrics, analysis, draft,
api/index, api/latest) carries `"meta_version": "1.0.0"` at its top
level. This is added by `meta.stamp()` at write time. Downstream
consumers (the longitudinal aggregator, the static-card renderer,
external API readers) can branch on it:

```python
art = json.load(open("briefings/2026-05-06_hormuz_iran.json"))
if art["meta_version"].split(".")[0] != "1":
    raise ValueError("incompatible meta version")
```

## Where to read the live values

```python
import meta
print(meta.VERSION)               # "1.0.0"
print(meta.EMBEDDING["model"])    # "paraphrase-multilingual-MiniLM-L12-v2"
print(meta.fingerprint())         # one-line summary for logs
meta.assert_pinned()              # raises if drift
```

`python -m meta` prints the fingerprint and exits 0 if the pin is
consistent — useful as a sanity check after pulling.

## Day-zero state

The repo was first pinned on **2026-05-07** at `meta_version 1.0.0`,
covering 235 feeds across 54 buckets, 5 canonical stories, and the
four `.claude/prompts/*.md` files used by the daily LLM jobs. This is
the baseline against which all longitudinal claims are made.

## Cross-lingual similarity (7.0.0)

Versions ≤ 2.x computed bucket vocabularies directly on
`title + signal_text` in the source language with an ASCII-only
tokenizer, so any cross-bucket finding involving non-Latin scripts
(Cyrillic, Han, Kana, Hangul, Arabic, Devanagari, Hebrew, Greek, Thai)
was confounded with language identification rather than framing.

3.0.0 attempted to fix this with a Claude-powered English-pivot
translation step, which restored cross-bucket comparability but
introduced a metered API cost (~200 calls/day) and another model in
the pinned dependency graph.

**7.0.0 retires the translation pivot** in favour of LaBSE
(`sentence-transformers/LaBSE`), a multilingual sentence-embedding
model that places 16+ languages into a shared cosine space by
construction. The bucket-mean cosine over original `signal_text`
gives a cross-lingual similarity score directly, no translation
needed. The pipeline is now:

```
ingest → extract_full_text → dedup → daily_health
       → build_briefing
       → build_metrics       (LaBSE bucket-mean cosine on originals)
       → analyze (Claude)    (cites originals verbatim, as always)
```

Citation grounding continues to operate on `corpus[i].signal_text`
exactly as before. Bucket-exclusive vocabulary still runs on the
pinned tokenizer + multilingual stopwords union, surfaced for
narrative color; the analyzer prompt instructs it to flag terms that
look like language artefacts rather than story-specific vocabulary.

Longitudinal claims that span the 6.x → 7.0.0 boundary must
acknowledge that the primary similarity formula changed (TF-IDF on
translated pivot → LaBSE cosine on originals). Replay against 7.0.0
to recover prior findings under the new metric.

## Section operationalisation (7.1.0)

Phase 1 introduces a per-item `section` field with values `news`, `opinion`,
or `wire`. The default is `news`; the wire-services bucket and the
opinion-magazines bucket get their entire feed list tagged at the feed level
(`section` field in `feeds.json`). Three individual feeds — *War on the
Rocks*, *Asia Times*, *Al Jazeera Arabic* — are flagged opinion despite
sitting in news buckets, per the data audit. URL-pattern overrides catch
opinion items that appear in news-tagged feeds: paths matching
`/opinion/`, `/editorial/`, `/op-ed/`, `/leader/`, `/commentary/`,
`/columnist/`, `/comment/`, `/blog/` (and pluralised variants) get
`section: "opinion"` regardless of the feed-level default.

Downstream consumers (frame distributions, coverage matrix `coverage_pct_news`)
use this to filter opinion contamination by default. The opinion subset
remains queryable so the suppression is not a removal.

## Coverage matrix (7.1.0)

`pipeline/coverage_matrix.py` emits `coverage/<DATE>.json` with the
deterministic per-(story × feed) answer to "who covered what today." Pure
regex-match against `canonical_stories.json` patterns (the same matcher
`analytical/build_briefing.py` uses); no LLM, no embedding, no translation.
Output schema: per-story rows of `{feed_name, bucket, section, n_matching,
first_match_rank, first_match_body_chars, first_match_age_hours,
first_match_url, first_match_title}` plus a `summary` block (n_feeds_covered,
n_buckets_covered, coverage_pct_news, median_age_hours).

Coverage matrix is the most defensible product the system ships: every cell
traces directly to a real article URL with a real timestamp; nothing is
inferred. It is the audit's "headline product."

## Longitudinal aggregator (7.1.0)

`analytical/longitudinal.py` walks `analyses/<DATE>_<story>.json` across all
dates, groups by `story_key`, and emits `trajectory/<story>.json` with
per-day frame share and continuity flags. Schema-tolerant on the frame
identifier: pre-7.0.0 used `frame.label`; post-7.0.0 uses `frame.frame_id`;
both are honoured.

Continuity flags the consumer **must** read before plotting:

- `meta_version_segments` — each contiguous run of analyses sharing the
  same pin. Trajectories spanning a major bump (e.g. 6.x → 7.0.0 swapped
  TF-IDF on translated text for LaBSE on originals) are not directly
  comparable; the segment boundary marks where to caveat.
- `bucket_set_signatures` — sha256 of the sorted bucket list per analysis,
  truncated to 16 chars. Multiple distinct signatures within one trajectory
  mean the contributing-feed set changed (a `feeds.json` edit, an outlet
  added or removed); the consumer should mark the boundary.

The aggregator is forward-compatible: adding a story is a minor bump (new
trajectory file appears); changing patterns is a major bump (existing
trajectory loses continuity).

## Bootstrap CIs on weighted frame share (7.1.0)

`analytical.build_metrics.weighted_frame_distribution` now resamples buckets
with replacement (1000 iterations, seed=42, `bucket_resample_with_replacement`
method) and emits 5/95 percentiles as `weighted_share_ci_lo` /
`weighted_share_ci_hi` per frame. The bootstrap parameters are recorded in
the output's `bootstrap` block so reproducibility is verifiable. Numpy is
required; if unavailable the analysis still ships without CIs (the
`bootstrap.skipped=true` flag is set).

The CI hedges against bucket-set sampling error: with N≈30 buckets per
analysis, per-frame share has non-trivial variance and a single-point claim
("frame X covers 14% of the population-weighted corpus") is fragile. The
CI ("[2%, 27%]") is the legitimate version of that claim.

## Within-language LLR (7.2.0)

Phase 1's `bucket_exclusive_vocab` heuristic (`count≥3, doc_freq≤1`) is
crude: it surfaces terms unique to a bucket without controlling for
language identity. A French-only bucket scored "français" as distinctive
because it appeared nowhere else; that's language identification, not
framing.

7.2.0 introduces `analytical/within_language_llr.py` which runs Dunning's
log-likelihood ratio per term per (bucket, language) against the
**same-language cohort** (the union of all other buckets sharing this
bucket's dominant language). Output (`<DATE>_<story>_within_lang_llr.json`)
includes per term: `count_in_bucket`, `count_in_cohort`,
`rate_in_bucket`, `rate_in_cohort`, `llr` (chi-squared statistic),
`log_ratio` (effect size), `p_value`. Default filters: `min_term_count=5`,
`p_threshold=0.001` (Bonferroni-conservative; the test fires over thousands
of terms per language).

The `bucket_exclusive_vocab` heuristic is **not removed** — it ships
alongside the LLR output as a fast-path for downstream renderers and as a
fallback when LLR isn't applicable (e.g. only one bucket in a language).
Both are stamped with the same pin.

## Within-language PMI / log-odds bigrams (7.2.0)

`analytical/within_language_pmi.py` extends the within-language layer to
adjacent token pairs. For each (bucket, language), score every bigram
against the same-language cohort using **log-odds with Jeffreys prior
(α=0.5)** and a Z-score derived from the variance estimate (Monroe,
Colaresi & Quinn 2008, "Fightin' Words").

Why log-odds, not raw PMI? PMI rewards rare-co-occurrence over magnitude:
a bigram with `count_in_bucket=1, count_in_cohort=0` scores infinitely
high. Log-odds with the variance correction penalises low-N bigrams
appropriately. Output: `<DATE>_<story>_within_lang_pmi.json` per term:
`bigram` (2-tuple), `count_in_bucket`, `count_in_cohort`, `log_odds`,
`z_score`, `lift` (raw rate ratio for human readability).

Default filters: `min_count=2`, `z_threshold=1.96` (~p<0.05).

## Headline-body divergence (7.2.0)

`.claude/prompts/headline_analysis.md` is a second LLM pass that operates
on **titles only** (`corpus[i].title`), producing
`analyses/<DATE>_<story>_headline.json` with the same 15-frame schema as
the body pass. `analytical/headline_body_divergence.py` then compares the
two: per bucket, find the dominant `frame_id` in each pass and report
agreement.

The output (`<DATE>_<story>_divergence.json`) carries
`agreement_rate` ∈ [0,1] and a `highest_diverging_buckets` list naming
buckets whose headline framing departs from their body framing — the
sensationalism index.

Cron cost: ~3-5 LLM calls/day, well within OAuth Pro limits. Wire to
analyze job after the body pass; runs unconditionally as of 7.2.0.

## Cross-outlet lag — CCF, not Granger (7.2.0)

`analytical/cross_outlet_lag.py` computes the cross-correlation function
at integer lags 0..7 days for a curated subset of bucket pairs (wire ↔
flagship, flagship ↔ follower per region). Output:
`lag/<bucket_a>__<bucket_b>.json` with peak lag + correlation strength
per story.

**CCF, not Granger.** At our N (~30 days × ~15 stories ≈ 450 bucket-day
samples), Granger causality tests give spurious results — the asymptotic
distribution assumptions don't hold. CCF gives the same signal ("B is
correlated with A at lag k") in a more honest framing ("B follows A by k
days when both cover this story") without claiming causality. If a future
phase has 1000+ days of accumulated history, Granger may become honest;
until then, CCF is the right tool.

The script self-skips with `insufficient_history` when fewer than 30 days
of `coverage/<DATE>.json` files are on disk. Wired to a **weekly** cron
(`.github/workflows/weekly.yml`, Mondays 09:00 UTC) — there's no signal
in re-running CCF daily.

## Replication + retention (7.2.0)

- `replay.py` reconstructs the deterministic post-ingest pipeline (dedup,
  coverage, build_briefing, build_metrics, longitudinal) for any past date
  from its snapshot. See `docs/REPLICATION.md`.
- `pipeline/rollup.py` rolls snapshots + briefings ≥ 90 days old into
  `archive/rollup/<category>-<YYYY-MM>.tar.gz`. See `docs/RETENTION.md`.
- Live tree keeps small JSONs (analyses, trajectories, coverage) for
  `git-blame` and quick clones; rolled-up tarballs stay in the repo
  short-term and migrate to GitHub Releases when they grow.

## Distribution channels (7.2.0)

- **X / Twitter**: `distribution/x_poster.py` reads thread drafts; cron
  step is secret-gated (`X_*` secrets), exits cleanly when missing. See
  `docs/OPERATIONS.md`.
- **YouTube Shorts**: `distribution/youtube_shorts.py` uploads videos as
  unlisted Shorts; secret-gated (`YT_*`). User flips public after review.

Both channels are **code-only at v7.2.0** — the OAuth dance is recorded in
`human.md` and `docs/OPERATIONS.md`. Once secrets land, the cron's
`distribute` job auto-activates.

## Known limitations (7.1.0)

- **HDBSCAN cluster contamination across similar-topic events.** The
  density-adaptive clusterer occasionally merges two distinct events sharing
  vocabulary (e.g. two unrelated Iran-related stories on the same day). The
  per-cluster stability score (`cluster_topics.last_stability_scores`) lets
  the consumer flag low-confidence clusters; full disambiguation requires
  per-event manual curation, out of scope.
- **Boydstun/Card 15-frame codebook coarseness.** A closed codebook of 15
  policy frames smooths real per-event variation; framings that don't fit
  any of the 15 categories collapse onto the closest neighbour. The
  trade-off is interpretability and longitudinal comparability vs.
  expressive precision. Phase 4 validation will measure the gap quantitatively
  (per-frame F1 vs. hand-coded ground truth).

## What's NOT pinned

- **Article body content** — the open web changes; we extract what we
  can and accept that.
- **Cluster IDs** — DBSCAN labels are run-dependent. Don't reference
  them across days.
- **Wire-service representative titles** — the choice of "rep" article
  per cluster is order-dependent. Use the cluster's `articles[]`
  list, not just the rep.
- **Render output** — videos, cards, and rendered HTML are downstream
  artifacts that can be regenerated from the pinned data + code.

## When to bump versus when to leave alone

A useful test: **could a reasonable reader, looking at two artifacts
under the same `meta_version`, expect them to be analytically
comparable?** If yes, no bump needed. If "comparable" requires
caveats, bump.

Adding an English stopword that should have been there from day one
is a minor bump. Removing one is a major bump (terms that used to be
filtered out will now appear in vocab counts). Adding a French
stopword set is a major bump (changes which French articles' tokens
survive). Adding a story to `canonical_stories.json` is a minor bump
(it just makes a new briefing detectable; existing briefings are
unchanged).

When in doubt, bump higher. A spurious major bump is cheap; a missed
one corrupts longitudinal credibility.
