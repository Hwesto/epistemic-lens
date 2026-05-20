# Phase C — Honest Coverage Plan

> **Companion to:** `REVIEW_STRESS_TEST.md`, `REMEDIATION_PLAN.md`. Phase A (translate-to-pivot) and Phase B (codebook + ensemble + canary + retest) plus the Phase A residuals (TF-IDF cosine, LaBSE parallel, bucket-quality tiers, Unicode tokenizer) all landed in `meta_version 5.0.0`.
>
> Phase C closes the **coverage** chapter — the part of the red-team report that is not about how we measure, but about what we measure on. This document is a planning artifact, not implementation. It exists to make the next decisions concrete enough to execute without re-litigating scope.

---

## Where we are after 5.0.0

The methodology layer is now defensible:

| Layer | Status |
|---|---|
| Cross-lingual lexical metric | TF-IDF cosine on English pivot (translated). Confound F1/F3 closed. |
| Cross-lingual semantic metric | LaBSE on originals. Optional parallel check. |
| Frame taxonomy | Closed Boydstun/Card codebook with `frame_id` enum. |
| Inter-LLM agreement | Sonnet + Haiku ensemble (+ Llama via Groq if `GROQ_API_KEY` set), Krippendorff α gate. |
| Drift detection | 8-prompt canary suite, daily, soft-fail to job summary. |
| Test-retest stability | Weekly `retest.yml` workflow. |
| Stub-only buckets | Quarantined from quantitative metrics via `bucket_quality.json`. |
| LLM weight pin | Dated snapshot ID with canary backstop. |

What remains is the part the red-team report described as **coverage / data integrity** — the questions that begin with "what corpus is this?" rather than "how did we score this?".

---

## Phase C scope (5 work items, ranked by ROI)

Sequence-independent unless noted. Each item is sized to land as one PR with its own pin bump.

### C.1 — Population-and-audience-weighted bucket aggregates

**Closes:** F6 (geographic-equality fallacy).

The current pipeline treats one Italy bucket (60M people, 4 outlets) as numerically equivalent to one "Africa" bucket (1.4B people across 50+ countries, 6 feeds). Any aggregate ("67% of buckets framed this as SECURITY_DEFENSE") is dominated by Western European overrepresentation.

**Concrete deliverable:**
- `bucket_weights.json` — pinned, hashed, containing per-bucket `population_m` (population in millions) and `audience_reach` (estimate of share of population that consumes news from these outlets, 0–1). Sources: World Bank for population, Reuters Digital News Report 2025 / Pew for reach where available; document defaults and confidence bands inline.
- New helper `meta.bucket_weight(bucket)` returns the product `population_m * audience_reach` (default 1.0 if missing — fail loud, not silently).
- New aggregate functions in `analytical/build_metrics.py`:
  - `weighted_frame_distribution(analysis)` — per `frame_id`, sum bucket weights that carry it, divided by total weight. Published as `metrics.weighted_frame_share` per analysis.
  - Same for paradoxes and silences.
- Update `daily_analysis.md` prompt to instruct: aggregate claims must use the weighted share, with the unweighted share in parentheses.
- Renderer adds a "Population-weighted view" section to each `analysis.md`.

**Acceptance bar:**
- Unit test: a synthetic 3-bucket corpus where 1 bucket weighs 100× the others and carries `SECURITY_DEFENSE`. Weighted share for `SECURITY_DEFENSE` should be ≥0.95; unweighted should be ~0.33. Current behaviour is unweighted only.
- Existing renderer outputs continue to validate.

**Pin impact:** minor (forward-compatible — adds new fields; doesn't remove).

**Effort:** ~2 days.

---

### C.2 — Common Crawl News fallback for paywalled majors

**Closes:** F7 (extraction failure is non-random; corpus biased toward easy-to-scrape long tail).

Trafilatura + Wayback fail systematically on outlets with aggressive paywalls or anti-bot defenses (NYT, WaPo, WSJ, FT, Le Monde, Bild). 12% ERROR + 14% PARTIAL extraction is not noise — those are the same 26% of outlets every day, and they are the ones *most* likely to define mainstream framing. The current corpus is therefore a study of the long tail of journalism, not the consensus.

**Concrete deliverable:**
- `pipeline/commoncrawl_fallback.py` — when an outlet flagged as `paywalled: true` in `feeds.json` returns `extraction_status == "ERROR"` from trafilatura and the Wayback fallback, query the [Common Crawl News](https://commoncrawl.org/blog/news-dataset-available) WARC index for the URL within ±7 days. CC-NEWS legitimately archives paywalled outlets via standard crawl headers.
- Add `paywalled: bool` field to each entry in `feeds.json` for the Western majors and any outlet with documented systemic 403/extraction failure.
- Add `extraction_via_commoncrawl: bool` flag per article so the renderer can attribute the fallback transparently.
- Document the legal basis (fair-use crawl by an established public dataset) in `docs/COVERAGE.md`.

**Acceptance bar:**
- Re-run extraction over the 2026-05-06 baseline (the one with 14% PARTIAL + 12% ERROR). Gross success rate improves to ≥85% FULL on paywalled-flagged outlets specifically.
- The 6 named majors (NYT, WaPo, WSJ, FT, Le Monde, Bild) produce body extraction at ≥60% FULL when their articles are present in Common Crawl.

**Pin impact:** minor (changes which articles have bodies, not the methodology).

**Effort:** ~3 days. Risk: Common Crawl has a 1–2 week ingestion lag. The fallback only helps for articles older than that. For "today's news" the long-tail bias persists; we should be honest about that in `COVERAGE.md`.

---

### C.3 — RSS-vs-sitemap selection-bias audit

**Closes:** F9 (RSS feeds are themselves algorithmically curated; "what an outlet emits via RSS" ≠ "what an outlet publishes").

This is research, not infrastructure. The question is: how big is the gap between an outlet's RSS feed and its actual publication output? We don't know, and our claims live or die on whether the gap is small.

**Concrete deliverable:**
- `archive/rss_vs_sitemap_audit_<date>.md` — one-shot audit. For 5 representative outlets across 5 buckets (e.g., BBC News, ANSA, Bild, Yomiuri, Al Jazeera), fetch one week's `sitemap.xml` and `rss.xml`. Intersect by URL. Compute: % of sitemap items that appear in RSS, % of RSS items that appear in sitemap, distribution of categories in the gap.
- New script `pipeline/sitemap_diff.py` (~150 LOC) that does the diff for any outlet given its sitemap URL.
- Document the gap prominently in `docs/COVERAGE.md` with the per-outlet numbers.

**Acceptance bar:**
- Audit document published; concrete numbers per outlet.
- If any outlet's gap is >40%, the renderer adds a footnote on stories where that outlet contributes a frame.

**Pin impact:** patch (audit document + new optional script; no methodology change).

**Effort:** ~2 days research + 1 day infrastructure.

---

### C.4 — Expand longitudinal base (n=5 → n=30+)

**Closes:** F12 (longitudinal sample is too small for the project's claims).

Right now the only "longitudinal" thing tracked is 5 hardcoded canonical patterns. Two months of operation × 5 stories = a case study, not a dataset. The codebook from Phase B unlocks longitudinal frame tracking, but only if there are enough stories to track.

**Concrete deliverable:**
- Add 10 long-running dossier patterns to `canonical_stories.json` covering: Iran nuclear, Ukraine war, China-Taiwan, climate policy, AI regulation, Israel-Palestine, India-Pakistan, US 2028 election cycle, EU expansion, African coups. Each with 3–5 regex patterns.
- Lower the `n_buckets >= 5` floor in `daily_analysis.md` to `>= 3` — the codebook makes small-bucket claims defensible (frame_id is a discrete category, not a vocabulary distribution).
- New step in `analytical/build_briefing.py`: **auto-promote** clusters that appear ≥3 days in any 7-day rolling window. Promoted clusters become discovered canonical stories with their dominant tokens as patterns. Manual review via `archive/auto_promoted_<date>.md`.
- Update `docs/METHODOLOGY.md` with the new threshold and auto-promote rule.

**Acceptance bar:**
- After 30 days post-deployment, ≥30 distinct stories have ≥7 days of consecutive analysis under `meta_version 5.x`. (Counted from the day Phase C lands.)
- Auto-promoted stories outnumber hardcoded ones within 60 days.

**Pin impact:** minor (added stories are forward-compatible per existing policy).

**Effort:** ~2 days for patterns + auto-promote logic.

---

### C.5 — HDBSCAN with a documented k-distance plot

**Closes:** F14 (DBSCAN's `eps=0.35, min_samples=3` are unjustified magic numbers).

HDBSCAN is to DBSCAN what `min_cluster_size` is to `eps + min_samples` — density-adaptive, no unjustified threshold, exposes cluster stability scores. With 3–5 stories/day under DBSCAN, we are clustering almost nothing meaningful; the canonical patterns do most of the work. HDBSCAN would let the discovered stories carry their own weight.

**Concrete deliverable:**
- Replace DBSCAN with HDBSCAN (`pip install hdbscan`) in `pipeline/ingest.py` (or wherever clustering lives).
- Pin parameters: `min_cluster_size=3`, `metric='cosine'`, `cluster_selection_method='eom'`.
- One-time calibration artifact: `archive/clustering_calibration_<date>.md` with the k-distance plot for 30 days of historical embeddings, justifying the chosen `min_cluster_size`.
- Surface cluster stability scores in `snapshots/<date>_convergence.json` so downstream consumers can filter out unstable clusters.

**Acceptance bar:**
- HDBSCAN finds ≥1.5× more stable clusters per day than DBSCAN at default parameters on the 2026-05-06 baseline.
- Cluster stability scores correlate with how often a cluster recurs the next day (rank correlation ≥0.5).

**Pin impact:** major (clustering is a methodology pin; pre-bump cluster IDs are not comparable to post-bump).

**Effort:** ~1 day swap + 1–2 days calibration.

---

## Recommended sequence

1. **C.4 first.** Cheapest, biggest immediate effect on the "longitudinal" claim. Two days.
2. **C.1 next.** Geographic-equality fallacy is the most-cited red-team flaw still open. Two days.
3. **C.5 next.** Methodology-pin major; do it before any longitudinal study so the cluster ID space is stable.
4. **C.2 + C.3 last.** Coverage research; the audit (C.3) informs how aggressive to be with the Common Crawl integration (C.2). Five days combined.

Total estimated effort: **~12 working days** for Phase C, landing as 4–5 PRs. Ends at `meta_version 6.0.0` (the major bump being C.5 — the others fold in as minor/patch under 5.x until C.5 ships).

---

## What stays open after Phase C

These are not failures of Phase C; they are honest disclaimers:

- **RSS sample is what RSS is.** Even with sitemap fallback, you don't have what people actually consume — that requires platform telemetry (Facebook, Google, X, TikTok). Document this; do not pretend.
- **Translation is itself an interpretive act.** `analytical/translate.py` makes the metric defensible, not transparent. The translator may regularize idioms or smooth register; the analysis says English even when no English speaker would use the source words. The methodology page should retain the disclaimer added at 3.0.0.
- **n=30 over a year is still tiny vs GDELT.** Don't compete on volume; compete on codebook validity, α-gated quality, and citation grounding — the things you have that GDELT doesn't.
- **Single-rater human review.** The PR-review step is one person. It's not feasible to run inter-rater on Prolific without a research budget. The multi-LLM ensemble + α gating is the engineering substitute; acknowledge it is not a replacement for human content-analytic standards.

---

## Decision points before C.1 starts

These are the questions worth resolving with one short message before any C work starts:

1. **Bucket-weight provenance.** World Bank population numbers are uncontroversial; audience-reach is judgment. Are you comfortable shipping with editor-judgment defaults plus a `confidence: low|medium|high` field, or do you want to source every reach number from Reuters Digital News Report 2025 first (longer)?
2. **Common Crawl latency.** CC-NEWS has a 1–2 week lag. Acceptable for retroactive analysis; insufficient for "yesterday's news." OK to scope C.2 to retroactive enrichment only?
3. **Auto-promote bias.** Auto-promoting from DBSCAN clusters to canonical stories embeds the clustering's biases into the longitudinal base. Acceptable, or should auto-promotion require manual review of `auto_promoted_<date>.md` before going live?

None of these are blocking — they're scope questions that affect the size of each PR.

---

*Phase C ends the remediation work the red-team report prescribed. After it lands, the project is defensible on the four axes the report attacked: idea / problem fit, methodology rigor, data / coverage integrity, results validity. What remains beyond Phase C is product strategy, not measurement integrity.*
