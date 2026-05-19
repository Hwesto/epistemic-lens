# Epistemic Lens

**Daily framing comparison across mainstream international press.**

Every morning at 07:00 UTC, this project pulls articles from 235 RSS
feeds across 55 country/region buckets, decides which "story" each
article is about (using a multilingual embedding matcher that doesn't
care if the article is in Persian, Arabic, Chinese, or English), and
has Claude write one structured framing analysis per story — showing
how outlets across 55 countries frame the same event differently.

The whole pipeline is unattended, runs on GitHub Actions, and costs
nothing beyond a Claude.ai subscription (used via OAuth, no metered API
spend).

**Front door:** [hwesto.github.io/epistemic-lens](https://hwesto.github.io/epistemic-lens/)
· **Latest analyses:** [api/latest.json](https://hwesto.github.io/epistemic-lens/api/latest.json)
· **Source:** this repo

---

## Scope (what this is, what it isn't)

This is **RSS-discoverable mainstream press**, not "what the populace
sees." Social platforms, video, podcasts, newsletters, and local-TV
broadcasts — which carry the majority of news consumption in most
countries — are out of scope. Outlet selection is biased toward
English-medium availability and persistent feeds; outlets behind
paywalls or anti-scraping defences (Cloudflare 403s) drop out silently.

As of **meta-v9.0.0** (PR2), non-Latin-script articles (Persian,
Arabic, Chinese, Japanese, Korean, Hindi, Hebrew, Russian) reach
briefings via an embedding-based story matcher. Pre-9.0.0 the matcher
was Latin-script regex; non-Latin content silently underflowed. See
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the full calibration
record.

Per-day coverage stats land in `snapshots/<date>_health.json`.

---

## What lands every morning

For each story (typically 10-13 per day), the cron publishes a folder
on GitHub Pages:

```
hwesto.github.io/epistemic-lens/<DATE>/<story_key>/
  briefing.json     ← per-bucket corpus (full bodies, deduped)
  metrics.json      ← LaBSE cosine, divergence, distinctive vocabulary
  analysis.json     ← canonical framing analysis (schema-validated)
  analysis.md       ← human-readable Markdown render
  thread.json       ← X/Threads draft (template, no LLM)
  carousel.json     ← IG/LinkedIn deck (template, no LLM)
  long.json         ← LinkedIn/Substack long-form (Sonnet)
```

Plus per-date `index.json`, a rolling `latest.json` at the API root, and
the static landing page at `/`. JSON Schema specs at `/api/schema/`.

---

## How it works (one paragraph per stage)

The cron runs 9 stages back-to-back. Each is a separate Python module
in either `pipeline/` (data ingest) or `analytical/` (analysis), and
each is independently runnable for local development or replay.

### 1. Ingest — pull every RSS feed in parallel

**`pipeline/ingest.py`** fetches all 235 RSS feeds concurrently (30
workers, per-host rate limit, exponential backoff on 5xx), parses
RSS/Atom/RDF, and writes `snapshots/<DATE>.json` with raw items
including title, link, summary, publish date, and flags like
`is_stub` (title-only feed) and `is_google_news` (proxy URL). Failed
feeds are marked and reported, not retried-to-death. **~10 min.**

### 2. Extract — fetch the full article body

**`pipeline/extract_full_text.py`** follows the article links and uses
Trafilatura to extract the body text (~85% success rate on a typical
day). When the host blocks (paywalls, Cloudflare 403s, anti-bot pages),
falls back to the Wayback Machine. Annotates each snapshot item with
`body_text` + `extraction_status` (`FULL`, `PARTIAL`, `STUB`, `NONE`,
`ERROR`). **~3 min.**

### 3. Deduplicate + health-check

**`pipeline/dedup.py`** canonicalises URLs (strips utm params, m.→www,
GoogleNews proxies) and collapses near-duplicate titles. Maintains
`cross_day_dedup_state.json` so wire-syndicated stories don't recount
across days. **`pipeline/daily_health.py`** writes a health snapshot
with feed status + per-bucket extraction stats; flags `volume_drop`
(bucket items dropped >50% vs trailing 7-day average) and
`low_extraction` alerts. **~1 min total.**

### 4. Embed — convert each article into a vector

**`pipeline/embed_articles.py`** encodes each article's
`title + signal_text[:1500]` with `intfloat/multilingual-e5-large` —
a 1024-dimensional embedding that places articles in any of 16+
languages into the same semantic space. Writes
`snapshots/<DATE>_embeddings.npy` keyed by a versioned article ID
(`sha256(model_id | signal_text_version | feed | link)`) so bumping
the model OR the signal-text extraction version invalidates the cache
loudly. **~12 min on the 2-core Actions runner.**

### 5. Match — assign each article to a canonical story

For each of 15 canonical stories (Ukraine war, China-Taiwan, Iran
nuclear, Hormuz Strait, Israel-Palestine, etc.),
`canonical_stories.json` carries 3-8 anchor sentences describing the
story — including native-script multilingual variants for high-recall
stories.

**`analytical/perception.py`** encodes each story's anchors, mean-pools
to get a centroid, then scores every article against every story
(cosine). It applies softmax across the 15 stories per article, takes
the argmax, and assigns the article to its strongest match — IF the
cosine clears `assignment_floor` (default 0.40) AND the gap between
the argmax and second-best exceeds `cosine_gap` (default 0.02, the
open-world filter that rejects articles equidistant from many stories).

This is what unlocks the non-Latin coverage. A Persian Iran International
article about the Lebanese-Israeli border (cosine ≈ 0.84 against
`lebanon_buffer`'s Persian + Arabic + English anchors) gets correctly
grouped with English coverage from BBC, Al Jazeera, Times of Israel,
etc.

Calibrated against a 343-row Opus silver-labelled eval set (`calibration/`);
e5-large at floor=0.40 achieves macro F1=0.815, with 4-of-5
gate-checkable per-language F1s passing (en 0.90, fa 0.76, ja 0.91,
ru 0.89). See
[`calibration/perception_eval_report.md`](calibration/perception_eval_report.md).

**`analytical/build_briefing.py`** consumes the assignments and writes
`briefings/<DATE>_<story>.json` — one corpus file per story, with up
to 2 articles per bucket (chosen to maximise framing diversity within
the bucket via title-Jaccard novelty filter). Each corpus entry carries
the `match_cosine` and `match_softmax` scores for auditing. **~3 min.**

### 6. Metrics + within-language signals

**`analytical/build_metrics.py`** computes the cross-bucket similarity
matrix per story (LaBSE bucket-mean cosine on original signal_text —
multilingual by construction, no translation pivot), per-bucket
isolation scores, and bucket-exclusive vocabulary (terms appearing in
exactly one bucket above a count threshold). **`within_language_llr.py`**
and **`within_language_pmi.py`** add distinctive-vocab and bigram-association
signals within each language strata. **~3 min.**

### 7. Discover — cluster the leftovers

Articles the matcher didn't assign (typically a few thousand per day)
are the discovery surface for emerging stories the canonical set
doesn't yet cover. **`pipeline/discover_residual.py`** runs HDBSCAN
over the residual vectors and emits
`snapshots/<DATE>_residual_clusters.json` with per-cluster member
article IDs, bucket distribution, and top tokens.

Weekly, **`analytical/persistence_tracker.py`** chains clusters across
days via member-article-ID Jaccard overlap (≥ 0.30 — invariant to
centroid drift in a way that centroid-cosine linkage isn't). Lineages
that persist ≥ 3 days with ≥ 4 buckets are surfaced by
**`analytical/auto_promote.py`** as review notes —
`archive/auto_promoted_<DATE>.md` is a human-decision artefact, never a
silent canonical mutation. **~2 min daily; weekly review.**

### 8. Analyze — Claude writes the framing analyses

For each qualifying story (`n_buckets ≥ 3`), the workflow spawns a
separate Sonnet session via `anthropics/claude-code-action@v1`. Each
session reads ONE briefing + ONE metrics file and writes:

- **`analyses/<DATE>_<story>.json`** — frames identified (2-8, from the
  closed Boydstun/Card 15-frame codebook), supporting quotes (verbatim,
  citation-validated against `corpus[i].signal_text` by index), paradox
  (opposing-bloc convergence, if any), silences, single-outlet
  findings, `tldr`, `bottom_line`.
- **`analyses/<DATE>_<story>_headline.json`** — same shape but operating
  only on titles (used downstream for a sensationalism index).
- **`sources/<DATE>_<story>.json`** — per-quote speaker attribution.

The matrix runs in parallel via GitHub Actions, with `fail-fast: false`
so one story's regression doesn't cancel siblings. Each entry has its
own ~25-min budget; the monolithic-session 60-min cancellations of
v8.x are structurally impossible now.

After the matrix completes, **`analyze_render`** validates every JSON
(`validate_analysis.py` enforces schema + citation grounding + number
reconciliation), augments metrics with population-weighted frame
distribution, computes headline-body divergence, aggregates source
attribution, renders Markdown, runs the longitudinal aggregator, and
commits everything. **~25-40 min for the matrix + ~5 min for render.**

### 9. Render + publish + distribute

- **`publication/render_thread.py`** and **`render_carousel.py`** —
  deterministic templates over the analysis JSON; no LLM. Hook
  priority: paradox > divergence outlier > exclusive vocab > generic.
- **`.claude/prompts/draft_long.md`** runs Sonnet over the analysis to
  write the long-form draft (`long.json`).
- **`publication/build_index.py`** assembles the `api/` tree and
  deploys to GitHub Pages.
- **`distribution/stage.py`** stages drafts to `distribution/pending/`
  for downstream poster bots.

**~10 min for draft + publish + distribute combined.**

---

## Deep dive

Detailed technical documentation:

- [**`docs/ARCHITECTURE.md`**](docs/ARCHITECTURE.md) — system diagram,
  per-script I/O reference, cadence table
- [**`docs/METHODOLOGY.md`**](docs/METHODOLOGY.md) — the analytical
  decisions: cross-lingual similarity (LaBSE), perception layer
  (embedding softmax-argmax + calibration record), discovery layer,
  weighted frame distribution, MC corrections, every pin bump explained
- [**`docs/OPERATIONS.md`**](docs/OPERATIONS.md) — cron setup,
  `CLAUDE_CODE_OAUTH_TOKEN`, manual runs, health alerts, retention
  rollup
- [**`docs/API.md`**](docs/API.md) — public JSON API contract, schemas,
  CORS, polling cadence
- [**`docs/COVERAGE.md`**](docs/COVERAGE.md) — bucket-by-bucket grade
  table + the structural blind spots that survive
- [**`docs/RETENTION.md`**](docs/RETENTION.md) — snapshot/briefing
  archival policy (≥ 90 days bundled into `archive/rollup/`)
- [**`docs/REPLICATION.md`**](docs/REPLICATION.md) — replay any past
  day's analytics from its frozen snapshot

---

## Quick start

```bash
git clone <repo> && cd epistemic-lens
pip install -r requirements.txt

# Run today's deterministic pipeline locally (matches the cron's ingest job)
python -m pipeline.ingest
python -m pipeline.extract_full_text
python -m pipeline.dedup
python -m pipeline.daily_health
python -m pipeline.embed_articles                # downloads ~2GB on first run
python -m analytical.build_briefing
python -m analytical.build_metrics
python -m pipeline.discover_residual

# Test
python -m unittest tests tests_edge tests_calibration tests_perception tests_discovery
python tests_e2e.py                              # full pipeline smoke (live, ~6 s)
```

The analyze + draft + publish stages run via GitHub Actions only; see
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the one-time
`CLAUDE_CODE_OAUTH_TOKEN` setup.

---

## Methodology pin

Every input that affects analytical output (feeds list, stopwords,
canonical-story anchors, prompts, embedding model, schema definitions,
model identifiers) is hashed in `meta_version.json`. Every artifact
(snapshot, briefing, metrics, analysis, draft) carries the active
`meta_version` so longitudinal consumers know which era they're reading.

```bash
python baseline_pin.py --check                       # CI gate
python baseline_pin.py --bump minor --reason "..."   # bumper
```

CI's `meta-check.yml` workflow enforces hash match on every push/PR.

Bump rules: `patch` = no output change, `minor` = forward-compatible
addition, `major` = invalidates longitudinal comparison (e.g. the v8→v9
perception-layer swap). See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)
for the full policy and the per-version changelog.

---

## Coverage

235 feeds across 55 buckets (France bucket added meta-v9.1.0).
~85% body-text extraction success on a typical day. Highlights:

- **Mass-tabloid press**: Daily Mail (UK), Bild (DE), Komsomolskaya Pravda (RU)
- **Right-populist**: Daily Wire / Breitbart (US), Republic World / Aaj Tak (IN), Junge Freiheit (DE), Sky News Australia
- **Native multilingual**: Russian (Russia + diaspora), Hindi (Aaj Tak, Bhaskar), Korean (Chosun, Yonhap), Persian (Iran International, IRNA), Arabic (Al Jazeera, Al Arabiya), Japanese (NHK, Mainichi)
- **Pan-regional**: Middle East Eye, AfricaNews, The Diplomat
- **State-TV / religious**: Vatican News, France 24 AR/ES, Sputnik International, RT Africa

Country-by-country grade table in
[`docs/COVERAGE.md`](docs/COVERAGE.md).

---

## File map

```
epistemic-lens/
├── README.md                         ← you are here
├── meta_version.json                 ← methodology pin (the spine)
├── meta.py                           ← loader / asserter / stamper
├── baseline_pin.py                   ← pin bumper / CI check
├── stopwords.txt                     ← pinned (hashed)
├── canonical_stories.json            ← embedding_anchors + assignment_floor per story (hashed)
├── feeds.json                        ← 235 feeds, 55 buckets (hashed)
│
├── .github/workflows/
│   ├── daily.yml                     ← per-story matrix daily cron (7-stage)
│   ├── weekly.yml                    ← Mondays: CCF + tilt + rollup + persistence
│   ├── golden.yml                    ← Sundays: perception parity check
│   ├── meta-check.yml                ← required check on every PR
│   ├── ci.yml                        ← unit/edge/e2e tests
│   └── weekly_rot.yml                ← Sundays: feed rot report
│
├── .claude/prompts/
│   ├── daily_analysis.md             ← analyze_body (Sonnet, JSON, one story per session)
│   ├── headline_analysis.md          ← analyze_headline (Sonnet, JSON, titles only)
│   ├── source_attribution.md         ← analyze_sources (Sonnet, JSON, per-quote speakers)
│   └── draft_long.md                 ← long-form draft (Sonnet, prose)
│
├── pipeline/                         ← DATA INGEST
│   ├── ingest.py                     ← parallel async RSS fetcher
│   ├── extract_full_text.py          ← trafilatura + Wayback fallback
│   ├── dedup.py                      ← URL canon + title near-dup + cross-day state
│   ├── daily_health.py               ← health snapshot + bucket alerts
│   ├── embed_articles.py             ← e5-large embed cache (PR2 Phase B)
│   ├── discover_residual.py          ← HDBSCAN over unassigned articles (Phase C)
│   ├── rollup.py                     ← weekly snapshot/briefing tarball retention
│   └── feed_rot_check.py             ← weekly rot detection
│
├── analytical/                       ← ANALYSIS
│   ├── perception.py                 ← embedding softmax-argmax matcher (PR2 Phase B)
│   ├── build_briefing.py             ← per-story corpus assembler
│   ├── build_metrics.py              ← LaBSE cosine + divergence + exclusive vocab
│   ├── within_language_llr.py        ← distinctive vocab per language strata
│   ├── within_language_pmi.py        ← bigram associations per language strata
│   ├── validate_analysis.py          ← schema + citation + number reconciliation
│   ├── list_qualifying_stories.py    ← matrix bootstrap (PR1.5)
│   ├── headline_body_divergence.py   ← sensationalism index
│   ├── source_aggregation.py         ← daily rollup per outlet/region
│   ├── longitudinal.py               ← frame-share trajectories per story
│   ├── robustness_check.py           ← day-over-day Jaccard stability
│   ├── cross_outlet_lag.py           ← weekly CCF (who-follows-whom)
│   ├── wire_baseline.py              ← rolling 90-day wire bigram baseline
│   ├── tilt_index.py                 ← per-outlet log-odds vs wire (BH-corrected)
│   ├── persistence_tracker.py        ← residual cluster lineage (Phase C)
│   ├── auto_promote.py               ← token + lineage promotion review notes
│   └── restamp_analyses.py           ← refresh meta_version on agent JSON output
│
├── calibration/                      ← PERCEPTION-LAYER CALIBRATION (PR2 Phase A)
│   ├── eval_set.jsonl                ← 343-row Opus silver-labeled eval set
│   ├── embedding_anchors_draft.json  ← per-story anchor sentences
│   ├── benchmark_models.py           ← three-way LaBSE / e5-large / bge-m3 bench
│   ├── parity_check.py               ← weekly golden cron entry point
│   └── perception_eval_report.md     ← calibration verdict
│
├── publication/                      ← RENDER + DISTRIBUTE
│   ├── render_analysis_md.py         ← analysis JSON → human Markdown
│   ├── render_sources_md.py          ← source aggregate → Markdown
│   ├── render_thread.py              ← analysis JSON → Twitter/Threads template
│   ├── render_carousel.py            ← analysis JSON → IG/LinkedIn carousel template
│   └── build_index.py                ← assemble api/ tree for GitHub Pages
│
├── distribution/                     ← POSTER STAGING
│   └── stage.py                      ← stage drafts to pending/ for downstream bots
│
├── tests.py / tests_edge.py / tests_e2e.py
├── tests_calibration.py
├── tests_perception.py               ← v9 perception layer
├── tests_discovery.py                ← v9 Phase C
│
├── web/                              ← static landing page (served at Pages root)
│   ├── index.html / styles.css / app.js
│
├── snapshots/                        ← daily ingest output (data, grows daily)
├── briefings/                        ← per-story corpora + metrics
├── analyses/                         ← per-story JSON + MD analyses
├── sources/                          ← per-quote speaker attributions
├── drafts/                           ← thread/carousel/long-form drafts
├── coverage/                         ← per-story × per-feed coverage matrix
├── trajectory/                       ← frame-share trajectories per story
│
├── docs/                             ← deep-dive documentation (see "Deep dive" above)
│
├── video/                            ← Remotion + React + 3 Python orchestrators (dormant)
│
└── archive/
    ├── rollup/                       ← snapshot/briefing tarballs >90 days old
    ├── scripts/                      ← retired one-off scripts
    └── review/                       ← per-feed audit decisions (rot history)
```

---

## Help, feedback, issues

- Help with this project: open an issue at
  [github.com/Hwesto/epistemic-lens/issues](https://github.com/Hwesto/epistemic-lens/issues)
- Help with Claude Code (the CLI): `/help` or
  [github.com/anthropics/claude-code/issues](https://github.com/anthropics/claude-code/issues)
