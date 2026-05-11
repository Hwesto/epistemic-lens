# Epistemic Lens — Remediation Playbook

> **Companion to:** `REVIEW_STRESS_TEST.md` (adversarial red-team) on this branch.
>
> Scope: the best concrete way to fix every flaw the red-team report surfaced. Sequenced by ROI, with file-level changes, dependency choices, version-bump impact, and verification per phase. Written assuming you're choosing **Path (b): keep the measurement claims**. If you choose Path (a) — the curated reader — skip to §10.

---

## 0. The single insight that drives everything

Cross-cultural framing comparison **requires a common semantic space**. There is no defensible way to compare Italian "guerra" buckets against Russian "война" buckets against Chinese "战争" buckets using surface tokens, because surface tokens *are* the language. The pinned `[A-Za-z]{4,}` regex is a symptom; the underlying disease is that the project is doing apples-to-oranges-to-皮 comparisons and calling the difference "framing."

There are exactly two clean fixes, and you should do **both**:

1. **Translate all `signal_text` to a pivot language** (English) → run all lexical metrics on the pivot. This rescues `pairwise_jaccard`, `bucket_exclusive_vocab`, `isolation`. Interpretable, debuggable, comparable.
2. **Replace token-Jaccard primary metric with cross-lingual sentence-embedding similarity** (LaBSE or multilingual-E5). Use as a check on (1) and as the primary similarity metric for clustering and isolation. Embedding similarity is language-agnostic by construction.

Everything else in this document is plumbing for those two.

---

## 1. Triage matrix

| # | Flaw (from red-team) | Fix | Effort | Bump | Phase |
|---|---|---|---|---|---|
| F1 | Tokenizer blind to non-Latin scripts | Translate-to-pivot **before** tokenization; replace regex with Unicode-aware fallback for pivot text | M | **major** | A |
| F2 | English-only stopwords | Replace with NLTK + spaCy stopword union over pivot + per-source-lang lemmatization | S | major | A |
| F3 | Cross-lingual Jaccard is language ID | Translate-to-pivot (F1) + add LaBSE cosine as parallel metric | M | major | A |
| F4 | Methodology pin can't pin LLM weights | Use Anthropic dated snapshot IDs + 8-prompt canary suite + drift dashboard; OR switch open-weight | M | minor | B |
| F5 | Frame re-derivation defeats longitudinal | Adopt Boydstun 15-frame codebook as closed top-level; free-form sub-frames preserved | S | major | B |
| F6 | Geographic-equality fallacy | Per-bucket weight (population × audience) in `meta_version.json`; weighted aggregates | S | minor | C |
| F7 | Non-random extraction failure | Per-outlet `extraction_confidence`; quarantine outlets <50% body rate; Common Crawl fallback for paywalled majors | M | minor | C |
| F8 | Stub-aggregator buckets corrupt vocab | `bucket_quality.tier` field; tier-C buckets excluded from quantitative comparison | S | minor | A |
| F9 | RSS selection bias undocumented | One-off audit (sitemap vs RSS for 5 outlets); document in `COVERAGE.md`; long-term sitemap fallback | M | patch | C |
| F10 | No inter-LLM agreement | Multi-LLM ensemble (Sonnet + Haiku + Llama 3.3 via Groq); Krippendorff α gating | M | minor | B |
| F11 | No test-retest stability | Weekly CI replay; α threshold for publication | S | patch | B |
| F12 | n=5 longitudinal sample | Lower `n_buckets >= 5` to `>= 3`; expand `canonical_stories.json`; auto-promote DBSCAN clusters | S | minor | C |
| F13 | Model-name inconsistency in prompt example | Read model from meta.py at runtime; fix example | XS | patch | A |
| F14 | DBSCAN params unjustified | k-distance plot in `archive/`; switch to HDBSCAN for `min_cluster_size` semantics | M | major | C |
| F15 | Jaccard on sets ignores frequency | Replace with cosine on TF-IDF vectors (after pivot translation) | S | major | A |

**Sequence: A (week 1) → B (weeks 2–3) → C (month 2). End state: `meta_version 3.0.0`.**

---

## 2. Phase A — Make the metrics defensible (week 1)

Fixes F1, F2, F3, F8, F13, F15. This is the work that lets you stop publishing confounded numbers. Bump to **3.0.0 (major)** at the end — explicitly invalidating prior longitudinal claims, which is correct because they were confounded.

### A.1 Translate-to-pivot pipeline

**Where:** new file `pipeline/translate.py`, called from `analytical/build_briefing.py` between corpus assembly and metric build. Input: each `corpus[i]` entry. Output: same dict with new field `signal_text_en` (pivot=English).

**How:**
- Use the LLM you already have. Sonnet 4.6 translates faithfully and you're already paying the per-token cost. Translation prompt:
  > *"Translate the following news article body to English. Preserve named entities verbatim. Preserve quoted speech with quotation marks. Do not summarize. Do not add commentary. Output only the translation."*
- Cache aggressively in `cache/translations/<sha256(signal_text)>.txt` — articles change rarely; cache hit rate after week 1 should be >80%.
- Add `translation_provenance` field to each corpus entry: `{"source_lang": "it", "model": "claude-sonnet-4-6-<snapshot>", "cached_at": "..."}`.
- For articles already in English: skip translation, set `signal_text_en = signal_text`.

**Cost:** ~3,800 articles/day × ~500 tokens × $3/Mtok (Sonnet input+output amortized) = ~**$5–7/day uncached**, ~**$1–2/day** after cache warmup. Acceptable for a measurement instrument; not acceptable for the curated reader path.

**Alternative:** NLLB-200 (Meta's open-weight multilingual translator, 200 languages) self-hosted on CPU. Free, slower (~2 min/article on CPU, fast on GPU), no API dependency. Recommended if you want to also escape API drift on translation itself.

### A.2 Tokenizer simplification

Once `signal_text_en` exists, the tokenizer only needs to handle English. Replace `meta_version.json:13`:

```diff
   "tokenizer": {
-    "regex": "[A-Za-z]{4,}",
+    "regex": "\\p{L}{3,}",
+    "regex_engine": "regex",
     "min_token_length": 3,
     "plural_suffixes": ["ies", "es", "s"],
+    "input_field": "signal_text_en",
     "stopwords_hash": "sha256:..."
   }
```

`min_token_length` drops from 4 to 3 because translated English includes legitimate 3-char content words ("war", "oil", "gas") that the old setting silently dropped. Update `meta.py:102` to use the `regex` library (supports `\p{L}` Unicode property escapes) instead of `re`.

### A.3 Stopwords

Replace `stopwords.txt` with the union of:
- NLTK English stopwords (~180 words)
- spaCy `en_core_web_sm` stopwords (~325 words)
- Domain stopwords: *said, says, saying, told, reported, according, sources, official, officials, statement, spokesperson*.

Generate once with a script in `archive/`, write the result to `stopwords.txt`, hash, pin. ~500 words total. Bumps the stopwords hash → triggers major.

### A.4 Replace Jaccard with cosine on TF-IDF

`analytical/build_metrics.py:50-55` — Jaccard on sets discards frequency. Replace `jaccard()` with TF-IDF cosine:

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def vectorize(vocabs: dict[str, Counter]) -> tuple[list[str], np.ndarray]:
    buckets = sorted(vocabs)
    docs = [" ".join(v.elements()) for v in [vocabs[b] for b in buckets]]
    X = TfidfVectorizer(min_df=1).fit_transform(docs)
    return buckets, cosine_similarity(X)
```

Keep Jaccard as `jaccard_legacy` for one release for diffability. Pin `metrics.method = "tfidf_cosine"`.

### A.5 LaBSE embedding similarity (parallel metric)

Compute per-bucket mean embedding from LaBSE applied to **original** `signal_text` (not translated — LaBSE is cross-lingual by design). Pairwise cosine. Publish as `pairwise_embedding_similarity` alongside `pairwise_jaccard`. The two should track each other when the corpus is well-formed; divergence flags edge cases.

Pin: add `meta_version.json` block:
```json
"cross_lingual_metric": {
  "model": "sentence-transformers/LaBSE",
  "dimensions": 768,
  "agg": "mean_of_article_embeddings"
}
```

### A.6 Bucket quality tiers

New file `bucket_quality.json` (pinned by hash):

```json
{
  "italy":            {"tier": "A", "extraction_floor": 0.7, "stub_ratio_max": 0.2},
  "google_news_reuters": {"tier": "EXCLUDE_QUANT", "reason": "41/50 stubs"},
  "china_global_times":  {"tier": "EXCLUDE_QUANT", "reason": "50/50 stubs"},
  "africa":           {"tier": "C", "extraction_floor": 0.5, "stub_ratio_max": 0.3,
                       "note": "narrative only; not for cross-bucket vocab comparison"}
}
```

In `build_metrics.py`, exclude `EXCLUDE_QUANT` buckets from `pairwise_jaccard` and `bucket_exclusive_vocab`. Tier-C buckets ship with a confidence flag the renderer surfaces visibly.

### A.7 Verification for Phase A

Before bumping to 3.0.0:
1. Replay every cached briefing through the new pipeline. Diff old vs new `pairwise_jaccard` rankings.
2. **Acceptance bar:** for any story where `n_buckets >= 10`, the top-3 most-isolated buckets must change. If they don't, your translator is broken — non-Latin buckets should now have *non-zero* Jaccard with everyone, displacing the structural-zero artifact.
3. The "Italy uniquely uses guerra" finding must disappear. If "guerra" still appears as Italy-exclusive after translation, your translation step is leaking source-language tokens (likely a prompt issue).
4. Update `archive/extraction_test_<date>.md` with new tier-quarantine list.
5. Bump: `python baseline_pin.py --bump major --reason "Phase A: translate-to-pivot pipeline; tokenizer Unicode-aware; LaBSE parallel metric; tier-quarantine; prior longitudinal claims invalidated"`.

---

## 3. Phase B — Make the LLM layer falsifiable (weeks 2–3)

Fixes F4, F5, F10, F11.

### B.1 Pin to dated model snapshot

Anthropic publishes dated snapshot IDs (e.g., `claude-sonnet-4-6-YYYYMMDD`) that are weight-stable. Replace `meta_version.json:64`:

```diff
   "claude": {
-    "model": "claude-sonnet-4-6",
+    "model": "claude-sonnet-4-6-<latest-dated-snapshot>",
+    "model_alias_used": "claude-sonnet-4-6",
     "prompts_hash": "..."
   }
```

This pins weights as far as the API permits. When Anthropic deprecates a snapshot (typically 12 months), bump major and re-baseline.

### B.2 Drift canary

New file `canary/prompts.json` — 8 frozen (article, prompt) pairs covering: a war-framing story, an economic-policy story, a public-health story, a domestic-politics story, an English source, an Italian source, a Chinese source, an Arabic source.

New job `canary/run.py` — runs every cron, ~$0.10/day. Outputs go to `canary/results/<date>.json`. Compute pairwise embedding similarity between today's outputs and the baseline run. Alert (cron job summary) if mean similarity drops below 0.92.

This is your **drift detector**. It catches silent model updates the snapshot ID cannot.

### B.3 Closed frame codebook

Replace the free-form frame-derivation rule with **Boydstun et al.'s Policy Frames Codebook (15 frames)**. New file `frames_codebook.json`:

```json
{
  "version": "1.0",
  "source": "Boydstun, Card, Gross, Resnik, Smith (2014); Card et al. Media Frames Corpus (2015)",
  "frames": [
    {"id": "ECONOMIC", "label": "Economic", "definition": "Costs, benefits, financial implications"},
    {"id": "CAPACITY_RESOURCES", "label": "Capacity and Resources", "definition": "Availability of human, physical, financial resources"},
    {"id": "MORALITY", "label": "Morality", "definition": "Religious or ethical implications, social responsibility"},
    {"id": "FAIRNESS", "label": "Fairness and Equality", "definition": "Equality or inequality of outcomes/treatment"},
    {"id": "LEGALITY", "label": "Legality, Constitutionality, Jurisprudence"},
    {"id": "POLICY", "label": "Policy Prescription and Evaluation"},
    {"id": "CRIME", "label": "Crime and Punishment"},
    {"id": "SECURITY", "label": "Security and Defense"},
    {"id": "HEALTH", "label": "Health and Safety"},
    {"id": "QUALITY_OF_LIFE", "label": "Quality of Life"},
    {"id": "CULTURAL", "label": "Cultural Identity"},
    {"id": "PUBLIC_OPINION", "label": "Public Sentiment"},
    {"id": "POLITICAL", "label": "Political (process / strategy / partisanship)"},
    {"id": "EXTERNAL", "label": "External Regulation and Reputation"},
    {"id": "OTHER", "label": "Other (with justification)"}
  ]
}
```

Pin its hash. Update `daily_analysis.md`:

```diff
- c. Derive 2–8 frames specific to this story by what the corpus actually contains.
+ c. Identify 2-8 PRIMARY frames from the closed codebook in frames_codebook.json.
+    Each frame entry must include `frame_id` (one of the 15 IDs) plus an
+    optional story-specific `sub_frame` label for color. The frame_id is what
+    longitudinal analysis tracks; the sub_frame is human-readable context.
- - Frames are story-specific. Re-derive every time. Do NOT reuse labels.
+ - Frame IDs come from the codebook; sub-frames are story-specific.
```

Update the JSON schema (`docs/api/schema/analysis.schema.json`) to enforce `frame_id` ∈ enum. The validator (`analytical/validate_analysis.py`) gets one new line:

```python
if frame["frame_id"] not in CODEBOOK_IDS:
    fail(f"frame_id {frame['frame_id']} not in codebook")
```

This is the single highest-leverage change in the whole document. It transforms "frame" from prose label into measurable construct, enables longitudinal tracking, and makes inter-LLM agreement (B.4) computable.

### B.4 Multi-LLM ensemble

Run each briefing through **three** models in parallel — pick for diversity, not redundancy:
- **Sonnet 4.6** (current)
- **Haiku 4.5** (cheap, same family — controls for prompt sensitivity)
- **Llama 3.3 70B** via Groq free tier (different family — controls for Anthropic-specific bias)

Compute Krippendorff's α on `frame_id` selection per story (now possible because of the closed codebook in B.3). Publish:

```json
"frame_agreement": {
  "raters": ["sonnet-4-6", "haiku-4-5", "llama-3.3-70b-groq"],
  "krippendorff_alpha": 0.71,
  "frames_with_unanimous_agreement": ["SECURITY", "ECONOMIC"],
  "frames_with_disagreement": ["POLITICAL"]
}
```

**Publication rule:** ship analyses where α ≥ 0.6; flag α 0.4–0.6 as preliminary; suppress α < 0.4. This is the validity gate citation grounding cannot provide.

### B.5 Test-retest CI

New workflow `.github/workflows/retest.yml`, weekly:
- Pick 3 random briefings from past 7 days.
- Re-run the analyze job against each.
- Compute frame_id agreement between original and replay.
- Fail the workflow (red badge) if agreement < 0.7.

Trivial cost. Catches the test-retest failures immediately.

---

## 4. Phase C — Honest coverage and population claims (month 2)

Fixes F6, F7, F9, F12, F14.

### C.1 Bucket weighting

Add to `meta_version.json` and pin:

```json
"bucket_weights": {
  "schema": "population_audience_v1",
  "weights": {
    "usa": {"population_m": 333, "audience_reach": 0.85, "weight": 283.05},
    "italy": {"population_m": 60, "audience_reach": 0.7, "weight": 42.0},
    "africa": {"population_m": 1400, "audience_reach": 0.15, "weight": 210.0,
               "note": "Heavy underrepresentation; absolute floor"}
  }
}
```

Every aggregate (e.g., "67% of buckets framed as Security") becomes population-weighted. Add unweighted version in parentheses for transparency. Surface confidence intervals per bucket based on `n_articles`.

### C.2 Common Crawl + paywall fallback

New file `pipeline/commoncrawl_fallback.py`. When trafilatura + Wayback both fail on an outlet flagged as "paywalled" in `feeds.json`, query Common Crawl News index for the URL. CC-NEWS legitimately archives paywalled content via standard crawl. Adds NYT/WaPo/WSJ/FT/Le Monde/Bild bodies to the corpus. Documented in `docs/COVERAGE.md`.

### C.3 RSS-vs-sitemap audit

One-time experiment — write a script that, for 5 outlets across 5 buckets, fetches their sitemap.xml for one week, intersects with RSS items for the same week, and reports the gap. Document the result in `docs/COVERAGE.md` so claims about "what an outlet published" are bounded by measured RSS coverage.

### C.4 Expand longitudinal base

- Lower `n_buckets >= 5` threshold to `>= 3` in `daily_analysis.md`.
- Add 10 more entries to `canonical_stories.json`: long-running dossiers (Iran nuclear, Ukraine war, China-Taiwan, climate, AI regulation, Israel-Palestine, India-Pakistan, US elections, EU expansion, Africa coups).
- Add an "auto-promote" step: any DBSCAN cluster that appears 3+ days in 7 graduates to a discovered canonical pattern.

This grows n from 5 to ~30+ over 90 days. Now the word "longitudinal" is defensible.

### C.5 HDBSCAN

Replace DBSCAN with HDBSCAN (`pip install hdbscan`). Migrate parameters: `min_cluster_size=3` replaces `min_samples=3`, drop `eps` entirely (HDBSCAN derives density adaptively). Document a k-distance plot in `archive/clustering_calibration_<date>.md` as a one-time artifact justifying the choice.

---

## 5. Final pin: meta_version 3.0.0

After all phases:

```json
{
  "meta_version": "3.0.0",
  "tokenizer": {"regex": "\\p{L}{3,}", "input_field": "signal_text_en"},
  "embedding": {"model": "paraphrase-multilingual-MiniLM-L12-v2"},
  "cross_lingual_metric": {"model": "LaBSE"},
  "clustering": {"method": "HDBSCAN", "min_cluster_size": 3, "metric": "cosine"},
  "metrics": {"jaccard_method": "tfidf_cosine"},
  "translation": {"model": "claude-sonnet-4-6-<snapshot>", "cache": true, "pivot": "en"},
  "claude": {"model": "claude-sonnet-4-6-<snapshot>"},
  "ensemble": {"raters": ["sonnet-4-6", "haiku-4-5", "llama-3.3-70b-groq"], "alpha_min": 0.6},
  "frames_codebook_hash": "sha256:...",
  "bucket_quality_hash": "sha256:...",
  "bucket_weights": {...}
}
```

---

## 6. What can't be fixed inside the current frame

Some critiques cannot be remediated; they require honest disclaimer instead:

- **RSS sample is what RSS is.** Even with sitemap fallback, you don't have what people actually consume — that requires platform telemetry (which Meta/Google have, you don't). The honest disclaimer in `README.md` and on the landing page: *"Epistemic Lens analyzes outlet-published RSS streams, not audience consumption."*
- **Translation is itself an interpretive act.** Translating "guerra" as "war" loses connotation present in Italian register. Phase A makes the metric defensible, not transparent. Note this in the methodology page.
- **n=30+ stories over a year is still tiny vs GDELT.** Don't compete on volume. Compete on frame-codebook validity and α-gated quality.

---

## 7. What NOT to do

- **Don't bump pin to 3.0.0 until A.7 verification passes.** Premature bump locks in artifacts that are still confounded.
- **Don't keep both old and new metrics under the same name** during transition. New cosine metric is `pairwise_tfidf_cosine`, not `pairwise_jaccard`. Renamed metrics force consumers to acknowledge the change.
- **Don't add per-language tokenizers (jieba, MeCab, KoNLPy, farasa)** as a fix. They're correct in isolation but compound the cross-lingual comparability problem — every bucket would tokenize differently, making "exclusive vocab" fundamentally incommensurable across buckets again. Pivot translation is the right answer.
- **Don't try to fix everything in one PR.** Phase A alone is 200–300 LOC across ~10 files. Sequence the bumps.
- **Don't skip the canary suite (B.2)** even after pinning a snapshot ID. Snapshot IDs are eventually deprecated; canary catches the day it happens.

---

## 8. Effort and cost summary

| Phase | Engineering effort | New deps | Recurring cost |
|---|---|---|---|
| A | 3–5 days | `regex`, `sklearn`, `sentence-transformers` (already used), translation cost | +$1–2/day translation (cached) |
| B | 5–7 days | `groq` SDK, no new heavy deps | +$0.10/day canary, +~$0.50/day Haiku rater, Groq Llama free |
| C | 5–10 days | `hdbscan`, Common Crawl fetch | One-off Common Crawl pulls, no recurring |

**Total: ~3 weeks of focused work** to move from "production confounded" to "publishable, gated, longitudinal-defensible." Recurring cost stays under $5/day all-in — the "$0/mo" framing is gone, but you're trading $150/month for measurement validity.

---

## 9. Verification of the whole remediation

When you can answer **yes** to all of these, Epistemic Lens has earned the claims its name makes:

1. After translate-to-pivot, do non-Latin buckets contribute non-zero exclusive vocab? **Yes/No**
2. After LaBSE parallel metric, does Russia-USA cosine ever exceed Russia-China cosine on a story where geopolitics suggests it should? **Yes/No** — if always No, embedding is also confounded.
3. After Boydstun codebook, does inter-LLM α exceed 0.6 on >70% of stories? **Yes/No**
4. After test-retest CI, does same-model 7-day-later replay agree on `frame_id` >70% of the time? **Yes/No**
5. After canary suite, does drift mean-similarity stay above 0.92 over 30 days? **Yes/No**
6. After bucket-quality tiers, are stub-only buckets excluded from every quantitative output? **Yes/No**

Each "No" is a research question, not a defect.

---

## 10. If you choose Path (a) — curated reader

If the answer to "what decision changes because of an Epistemic Lens output?" remains "feeling sophisticated about media bias," the right move is to drop the measurement layer entirely:

- Keep: ingest pipeline, citation-grounded summarization, multilingual coverage, methodology pin for **inputs only**, daily cron, landing page.
- Drop: `pairwise_jaccard`, `bucket_exclusive_vocab`, `isolation`, `paradox`, `silence`, frame-derivation prompt, longitudinal claims.
- Reframe: "*A daily, citation-grounded, cross-country news digest in 16 languages, with full source transparency.*"

This product is honest, useful, defensible, and ships in **one afternoon** of deletion. It also competes against Ground News on a clearer value prop: source transparency rather than left/right scoring. This is the underrated path.

---

*The hardest decision is between Path (a) and Path (b). Don't let sunk cost make it for you. The infrastructure you've built is good either way; the question is which product it should serve.*
