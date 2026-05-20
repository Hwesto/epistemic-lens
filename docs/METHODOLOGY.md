# Methodology — Epistemic Lens (v10)

This document explains *how* Epistemic Lens computes what it computes,
and the methodology pin that keeps those computations stable across
days.

> **v10 is a clean break.** v9 matched articles against a fixed list of
> 15 `canonical_stories.json` narratives via an embedding softmax-argmax
> matcher. v10 retires the canonical set entirely: stories emerge from
> daily clustering. The "perception layer" and "discovery layer" of v9
> no longer exist as separate stages — there is one clustering pass over
> every article. The project is a prototype with no external API
> consumers, so the v9 → v10 transition carries no longitudinal-continuity
> promise; longitudinal claims simply start fresh at v10.

## The methodology pin

### Why it exists

Epistemic Lens makes longitudinal claims: "this outlet uniquely uses
*guerra* for this story," "this cluster spanned 14 countries on day 1,
6 by day 7." Such claims are defensible only if the **way** the numbers
were computed is stable. Change the tokenizer mid-week and "uniquely
uses *guerra*" becomes a measurement artifact, not a finding.

The pin makes drift impossible-by-accident: every input that affects
analytical output is hashed in `core/config/meta_version.json`, every
artifact is stamped with its `meta_version`, and CI fails any push
where the declared hashes no longer match the live files.

### What is pinned

`meta_version.json` declares hashes for:

| Input | Hash key | Why it matters |
|---|---|---|
| `core/config/feeds.json` | `feeds.hash` | Adding/removing feeds changes which outlets contribute and what clusters. |
| `core/config/stopwords.txt` | `tokenizer.stopwords_hash` | Words that survive filtering are the entire signal in exclusive-vocab metrics. |
| `core/config/frames_codebook.json` | `frames_codebook_hash` | The closed frame taxonomy the LLM must use. |
| `core/analyze/prompts/*.md` | `claude.prompts_hash` | LLM analyses are downstream of these prompts word-for-word. |
| `publish/api/schemas/*.json` | `schemas_hash` | The contract every artifact is validated against. |

It also records — without hashing — the structural constants:

- **Embedding model** — `intfloat/multilingual-e5-large`, used both to
  vectorise articles for clustering and to key the embedding cache.
- **Clustering** — HDBSCAN, `min_cluster_size = 3`, `metric =
  "euclidean"` over unit-normed vectors (≈ cosine),
  `cluster_selection_method = "eom"`.
- **Tokenizer** — Unicode-aware regex `\p{L}{4,}`, plural normalisation
  (`ies`, `es`, `s`), multilingual stopword union. Operates on original
  `signal_text` in its source language; used for exclusive vocabulary.
- **Cross-outlet similarity** — LaBSE per-outlet-mean cosine on original
  `signal_text` (no translation pivot — LaBSE is multilingual by
  construction).
- **Signal text fallback** — body if ≥500 chars, else summary if ≥60
  chars, else title; capped at 2500 chars.
- **Claude model** — `claude-sonnet-4-6` for the analysis passes.

### How to change something

Pick the bump level that matches the impact, run `python
scripts/baseline_pin.py --bump <level> --reason "..."`, commit, tag.

- **patch** — no output change (refactor, comment, logging, doc fix).
- **minor** — forward-compatible addition (a new feed, a new optional
  field on an artifact).
- **major** — longitudinal-breaking change (swapped embedding model,
  changed the clusterer, changed the similarity formula, edited the
  frame codebook). Requires `--reason`.

```bash
python scripts/baseline_pin.py --bump major --reason "swapped embedding model"
git add core/config/meta_version.json
git commit -m "meta: bump to 11.0.0 — embedding model change"
git tag meta-v11.0.0 && git push --follow-tags
```

The repo tag lets anyone re-run analyses under the old config later.

### How CI enforces it

`baseline_pin.py --check` is a required status check (`meta-check.yml`)
on every push and PR. It re-hashes the live files and compares to
`meta_version.json`; on drift it fails with a message naming the file
that changed and the bump level that fits. It runs in seconds with no
dependency beyond the standard library and cannot be silently bypassed.

### How artifacts are stamped

Every artifact (snapshot, briefing, metrics, analysis, draft, api
index) carries `"meta_version"` at its top level, written by
`meta.stamp()`. Downstream consumers branch on it to know which era
they're reading.

## The v10 pipeline, stage by stage

### Dynamic clustering

`core/cluster/cluster_daily.py` runs **HDBSCAN** over the embedding
vector of *every* article in the day's snapshot. HDBSCAN is a
density-based clusterer: it groups points that are dense neighbours and
leaves the rest as "noise" — no article is forced into a cluster. A
typical day yields ~50–200 clusters.

This is the central v10 design choice. v9 asked "which of these 15
pre-defined stories is this article about?" — which fossilised the
story set (a story named for a one-week event stayed in the list
forever) and discarded the ~95% of articles that matched nothing. v10
asks "what is actually being talked about today?" and lets the answer
emerge. Because the clusterer operates on multilingual meaning-vectors,
a cluster spans languages natively: the Persian, Arabic, and English
coverage of one event land together with no per-story anchor.

Each cluster records its member article IDs, the country / outlet /
language distributions, the most common title tokens, and HDBSCAN's
per-cluster stability score.

### Salience ranking

50–200 clusters are too many to analyse. `core/cluster/salience.py`
scores each:

```
salience = n_articles
         × min(1.0, n_countries / total_countries_today)
         × (1.0 + lang_bonus)        # +0.5 if the cluster spans ≥2 languages
         × stability                  # HDBSCAN persistence, default 1.0
```

and keeps the top N (default 15). The formula rewards exactly what the
project is for: broad cross-country coverage of one event, with a bonus
when that coverage crosses language spheres. The top-N cap is
deliberate — beyond ~15 stories the editorial focus dilutes and the LLM
cost balloons without proportional value.

### Cross-day lineage

A story that persists should keep one identity. `core/cluster/lineage.py`
(weekly) walks the last 7 days of `<date>_clusters.json` and links
clusters across days by the **Jaccard overlap** of their member article
IDs — if today's cluster shares ≥0.30 of its combined member set with a
prior day's cluster, they are the same lineage.

Member-ID Jaccard is used rather than centroid cosine because HDBSCAN
centroids drift day to day as the article pool changes; the *set of
articles* re-clustering is a far more stable signal than the centroid's
position. Each lineage gets a stable `lineage_id` (a hash of its
first-appearance day + cluster id). `core/briefing/build.py` stamps
that `lineage_id` onto the briefing filename, so a long-running story
keeps one ID across weeks while a one-off breaking story gets its own.

### Outlets, not buckets

v9 aggregated 235 outlets into 55 country/region "buckets" and computed
bucket-mean similarity. That forced a geographic mental model onto data
that often diverges along ideological / ownership / language lines, and
it hid intra-bucket variation (a centrist and a partisan outlet in the
same country averaged together).

v10 makes the **outlet** the atomic unit. Each briefing corpus entry
carries `outlet` plus `country`, `lang`, `lean`, and `section` tags, so
any downstream comparison can group by whichever dimension the question
needs — not just geography. `core/config/outlets.json` is the flat
source of truth (235 outlets); `core/config/feeds.json` remains the
nested ingest config.

### Cross-lingual similarity

Cross-bucket findings involving non-Latin scripts used to be confounded
with language identification rather than framing. v10 (like v9 ≥ 7.0.0)
encodes article meaning with a multilingual sentence-embedding model
that places 16+ languages into one shared cosine space by
construction. Cross-lingual similarity is read directly from the
vectors — no translation pivot, no metered API call. Citation grounding
always operates on the original-language `corpus[i].signal_text`.

## Analytical methods

### Cross-outlet metrics

`core/metrics/cross_bucket.py` measures how differently outlets cover a
story:

- **Pairwise similarity** — average LaBSE cosine between outlets'
  per-outlet-mean vectors. LaBSE is used here (separate from the
  clustering model) for its speed on the small per-outlet computation.
- **Isolation** — which outlet sits furthest from everyone else: an
  outlier, possibly framing the story uniquely.
- **Outlet-exclusive vocabulary** — tokens appearing in exactly one
  outlet's coverage (`doc_freq ≤ 1 AND count ≥ 3`). The analyzer prompt
  is told to flag terms that look like language artefacts rather than
  story-specific vocabulary.

### Within-language LLR

The exclusive-vocab heuristic above is crude — it can surface a term as
"distinctive" merely because one outlet publishes in a language no
other outlet shares. `core/metrics/within_language_llr.py` corrects for
this with Dunning's **log-likelihood ratio** per term, scored against
the *same-language cohort* (every other outlet sharing the term's
dominant language). Output per term: counts, rates, `llr` (χ²
statistic), `log_ratio` (effect size), `p_value`. Default filters:
`min_term_count = 5`, `p_threshold = 0.001` (the test fires over
thousands of terms per language; the threshold is conservative).

### Within-language PMI / log-odds bigrams

`core/metrics/within_language_pmi.py` extends the within-language layer
to adjacent token pairs. Each bigram is scored against the same-language
cohort with **log-odds under a Jeffreys prior (α = 0.5)** plus a
Z-score from the variance estimate (Monroe, Colaresi & Quinn 2008,
"Fightin' Words").

Log-odds, not raw PMI: PMI rewards rare co-occurrence over magnitude — a
bigram seen once in one outlet and never elsewhere scores infinitely
high. The variance-corrected log-odds penalises low-N bigrams properly.
Default filters: `min_count = 2`, `z_threshold = 1.96`.

### Headline-body divergence

A second LLM pass (`core/analyze/prompts/headline_analysis.md`) runs the
same 15-frame analysis on **titles only**. `core/analyze/divergence.py`
then compares it to the body pass: per outlet, find the dominant frame
in each and report agreement. The output's `agreement_rate` and
`highest_diverging_outlets` are a sensationalism index — outlets whose
headline framing departs from their own body framing.

### Cross-outlet lag — CCF, not Granger

`core/compare/lag.py` (weekly) computes the cross-correlation function
at integer lags 0–7 days for curated outlet pairs (wire ↔ flagship,
flagship ↔ follower). At this project's N, Granger causality tests give
spurious results — the asymptotic assumptions don't hold. CCF gives the
same signal ("B correlates with A at lag k") in an honest framing ("B
follows A by k days on this story") without claiming causality. The
script self-skips with `insufficient_history` below 30 days of coverage
data.

### Wire baseline + tilt index

`core/compare/wire_baseline.py` (weekly) builds a rolling 90-day bigram
counter from the `wire_services` outlet group. `core/compare/tilt.py`
then scores every outlet's bigrams as log-odds (same Jeffreys-prior
apparatus as the PMI module) against that wire baseline.

The output is descriptive — "log-odds vs wire" — **not a normative
claim**. Without an editorial commitment that the wires are "neutral",
tilt is best read as "distance from the most-replicated low-effort
framing", not "tilt from neutral". Multiple-testing correction is
applied via Benjamini-Hochberg (`core/compare/mc_correction.py`); at the
comparison counts involved, Bonferroni would push the z-critical past 5
and kill all signal.

### Robustness check

`core/compare/robustness.py` computes per-story frame-set Jaccard across
consecutive day-pairs:

```
stability = mean( jaccard(frame_set_t, frame_set_{t+1}) )
```

Range 0–1; `low_stability` flag below 0.5. This catches *frame-allocation
instability* — the analyzer assigning different frames to similar inputs
across days. It does **not** catch model drift (same prompt + same input
→ different output), which would require re-running the LLM against past
briefings.

### Bootstrap CIs on weighted frame share

`weighted_frame_distribution` resamples outlets with replacement (1000
iterations, fixed seed) and emits 5/95 percentiles per frame. With a few
dozen outlets per analysis, a single-point share claim ("frame X covers
14%") is fragile; the interval ("[2%, 27%]") is the honest version. The
bootstrap parameters are recorded in the output so reproducibility is
verifiable.

### Longitudinal aggregator

`core/compare/longitudinal.py` walks `data/analyses/` across dates,
groups by `lineage_id`, and emits per-lineage frame-share trajectories.
Because a `lineage_id` is stable across days, a persistent story's
trajectory is a single coherent series. Trajectories still carry
`meta_version` segment boundaries so a consumer can mark where the
underlying methodology changed.

## The frame codebook and its limits

The LLM assigns each story 2–8 frames from a **closed 15-frame codebook**
(`core/config/frames_codebook.json`) — Boydstun & Card's published
Policy Frames Codebook (ECONOMIC, MORALITY, FAIRNESS, SECURITY_DEFENSE,
etc.). A fixed vocabulary across all stories is what makes longitudinal
and cross-story comparison possible.

Known limits:

- **Codebook coarseness.** 15 policy frames smooth real per-event
  variation; a framing that fits none collapses onto its nearest
  neighbour. The free-text `sub_frame` field is the escape valve.
- **Cross-cultural validity.** Boydstun, Card & Gross (2014) derived
  the codebook from US domestic-political coverage. The categories are
  *stretched* (not invalid, but stretched) on foreign-policy stories
  framed in non-US registers. Treat per-frame shares as more reliable
  on US/Anglo coverage and as suggestive-only on non-Anglo framing
  until a cross-cultural validation study lands.
- **HDBSCAN cluster contamination.** The density clusterer occasionally
  merges two distinct same-day events that share vocabulary. The
  per-cluster `stability` score lets a consumer flag low-confidence
  clusters; full disambiguation needs manual curation.

## Corrections and methodology challenges

The project ships two intake channels with deliberately different SLAs:

- **Corrections** — factual errors (a hallucinated quote, a wrong
  number). 24-hour SLA; logged and fixed.
- **Methodology challenge** — disagreement with a framing call. Not
  retracted; logged as a candidate for the next codebook revision.

Conflating them would treat editorial disagreement as if it were a
fact error; they need different remedies.

## What is NOT pinned

- **Article body content** — the open web changes; we extract what we
  can.
- **Cluster IDs** — HDBSCAN labels are run-dependent. Reference a story
  by its `lineage_id`, never by `cluster_id` across days.
- **Render output** — Markdown, cards, and HTML are downstream artefacts
  regenerable from the pinned data + code.

## When to bump versus when to leave alone

A useful test: **could a reasonable reader, looking at two artifacts
under the same `meta_version`, expect them to be analytically
comparable?** If yes, no bump. If "comparable" needs a caveat, bump.
When in doubt, bump higher — a spurious major bump is cheap; a missed
one corrupts longitudinal credibility.
