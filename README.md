# Epistemic Lens

**Daily framing comparison across mainstream international press.**

Every morning, this project pulls articles from 235 RSS feeds across 55
countries, clusters the day's articles into the stories actually being
covered (using an AI that understands articles in Persian, Arabic,
Chinese, and English equally well), and has Claude write one structured
framing analysis per top story — showing how outlets across those
countries frame the same event differently.

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

The clusterer works across non-Latin scripts (Persian, Arabic, Chinese,
Japanese, Korean, Hindi, Hebrew, Russian) by encoding article meaning as
a numerical vector — articles about the same topic land close together
in vector space regardless of their language. So a Persian Iran
International article about southern Lebanon ends up in the same
briefing as a BBC English piece about the same border conflict.

There is no fixed list of stories. Whatever the day's outlets are
actually talking about is what surfaces — so coverage isn't pinned to a
pre-defined set that goes stale.

Per-day coverage stats land in `data/snapshots/<date>_health.json`.

---

## What lands every morning

For each top story (the day's ~15 highest-salience clusters), the cron
publishes a folder on GitHub Pages, keyed by a stable cross-day
`lineage_id`:

```
hwesto.github.io/epistemic-lens/<DATE>/<lineage_id>/
  briefing.json     ← the corpus: the cluster's articles, one entry per outlet
  metrics.json      ← cross-outlet similarity, distinctive vocabulary
  analysis.json     ← Claude's framing analysis (citation-grounded)
  analysis.md       ← human-readable version of the above
  thread.json       ← X/Threads draft (template, no LLM)
  carousel.json     ← IG/LinkedIn deck (template, no LLM)
  long.json         ← LinkedIn/Substack long-form (Sonnet)
```

Plus a per-date `index.json`, a rolling `latest.json`, and the landing
page at `/`.

---

## How it works (one paragraph per stage)

Nine stages run back-to-back every morning. Each is a separate Python
module under `core/` — `core/ingest/`, `core/embed/`, `core/cluster/`,
`core/briefing/`, `core/metrics/`, `core/analyze/` — and each is
independently runnable for local development.

### 1. Ingest — pull every RSS feed

**`core/ingest/pull_feeds.py`** fetches all 235 RSS feeds concurrently
using 30 worker threads with a per-host rate limit and exponential
backoff on server errors. Parses RSS, Atom, and RDF feeds, then writes
`data/snapshots/<DATE>.json` with raw items: title, link, summary,
publish date, plus flags like "title-only feed" or "Google News proxy."
Failed feeds get marked and reported rather than retried to death.
**~10 min.**

### 2. Extract — fetch the full article body

**`core/ingest/extract_bodies.py`** follows the article links and runs
each page through **Trafilatura** (an open-source library that strips
the navigation, ads, and boilerplate to leave just the article body).
About 85% of articles yield clean body text on a typical day. When the
host blocks the request (paywalls, Cloudflare 403s, anti-bot pages),
the script falls back to the **Wayback Machine** (web.archive.org)
which usually has an unblocked copy. Each item gets annotated with an
`extraction_status` (`FULL`, `PARTIAL`, `STUB`, `NONE`, `ERROR`).
**~3 min.**

### 3. Deduplicate + health-check

**`core/ingest/dedup.py`** canonicalises URLs (strips UTM tracking
params, normalises `m.example.com` → `example.com`, decodes Google News
proxy links) so the same article posted to multiple feeds collapses to
one item. Title-Jaccard near-duplicates within a feed collapse too. A
cross-day state file tracks wire-syndicated stories so AFP's coverage
of an event doesn't double-count across days.

**`core/ingest/health.py`** writes a health snapshot summarising
feed status, per-country extraction rates, and alerts. Two alert types:
**volume_drop** (a country's item count dropped >50% vs its trailing
7-day average — probably a feed broke), and **low_extraction** (feeds
pulled items fine but bodies didn't extract — probably the host
started 403-ing). **~1 min total.**

### 4. Embed — convert each article into a vector

**`core/embed/encode.py`** turns each article's text into a
1024-dimensional vector using **multilingual-e5-large**, an
**embedding model** — a neural network that converts text into
numerical vectors such that articles about the same topic end up close
together in vector space, regardless of language. So a Persian article
about Iran and an English article about Iran will produce vectors that
point in similar directions, even though their characters share
nothing in common.

The vectors get written to `data/snapshots/<DATE>_embeddings.npy` with
a versioned cache key — bumping the embedding model OR the way we
extract text from articles invalidates the cache automatically so
stale vectors can never silently get served. **~12 min on the
2-core Actions runner.**

### 5. Cluster — group the day's articles into stories

There is no fixed list of stories. **`core/cluster/cluster_daily.py`**
runs **HDBSCAN** over every article's vector from stage 4. HDBSCAN is a
density-based clustering algorithm: it groups vectors that are dense
neighbours of each other and leaves outliers as "noise" — no article is
forced into a cluster it doesn't belong in. A typical day produces
~50–200 clusters.

For each cluster, the script records the member article IDs, the
country / outlet / language distributions, and the most common words in
the member titles, and writes `data/snapshots/<DATE>_clusters.json`.
Because the clusterer operates on meaning-vectors, a cluster naturally
spans languages: the Persian, Arabic, and English coverage of one event
land in the same cluster without any pre-defined anchor for it.

Stories that persist get a stable identity. Weekly,
**`core/cluster/lineage.py`** chains clusters across days by the
**Jaccard overlap** of their member article IDs — if today's cluster
shares ≥30% of articles with a prior day's, it's the same lineage and
keeps the same `lineage_id`. (Jaccard overlap = intersection / union of
two sets.) That's what lets a long-running story carry one ID across
weeks while a one-off breaking story gets its own. **~3 min.**

### 6. Rank salience + build briefings

A day's 50–200 clusters are too many to analyse. **`core/cluster/salience.py`**
scores each one — `n_articles × country_spread × multilingual_bonus ×
cluster_stability` — and keeps the top ~15. The formula rewards exactly
what the project is about: broad cross-country coverage of the same
event, with a bonus when the coverage spans multiple language spheres.

**`core/briefing/build.py`** then assembles a per-cluster corpus for
each top cluster, keeping up to 2 articles per **outlet** (titles too
similar to an already-kept one get dropped, to maximise framing
diversity). Each corpus entry carries its outlet plus `country`,
`lang`, `lean`, and `section` tags — so downstream comparison can group
by any of them, not just geography. Briefings are written to
`data/briefings/<DATE>_<lineage_id>.json`. **~3 min.**

### 7. Metrics + within-language signals

**`core/metrics/cross_bucket.py`** measures how different outlets'
coverage of a story looks from each other:

- **Pairwise similarity:** average vector similarity between outlets'
  coverage (e.g. how much does a German outlet's Hormuz coverage
  resemble an Indian outlet's?). The base similarity uses **LaBSE**, a
  separate multilingual embedding model used here for its speed on the
  small per-outlet computation.
- **Isolation:** which outlet sits furthest from everyone else (an
  outlier — possibly framing the story uniquely, possibly just
  covering a different angle entirely).
- **Outlet-exclusive vocabulary:** words that appear in only one
  outlet's coverage and nowhere else (often the most revealing tell of
  how that outlet is framing the story differently).

**`within_language_llr.py`** and **`within_language_pmi.py`** compute
additional within-language signals — log-likelihood-ratio distinctive
vocab and pointwise-mutual-information bigram associations within each
language stratum, so vocabulary differences between outlets aren't
confounded by them publishing in different languages. **~3 min.**

### 8. Analyze — Claude writes the framing analyses

For each qualifying cluster (n_outlets ≥ 3), the workflow spawns a
**separate Sonnet session** via `anthropics/claude-code-action@v1`.
Each session reads ONE briefing + ONE metrics file, names the story
(Claude writes a `cluster_name` — the cluster arrives without one), and
writes:

- **`analyses/<DATE>_<lineage_id>.json`** — frames identified (2-8,
  drawn from a closed 15-frame codebook: ECONOMIC, MORALITY, FAIRNESS,
  SECURITY_DEFENSE, etc. The codebook is from
  Boydstun & Card's published framing research; using a fixed
  vocabulary across all stories makes longitudinal comparison
  possible), supporting quotes (verbatim, citation-validated against
  the briefing corpus), paradox (opposing-bloc convergence — when two
  ideologically opposed outlets reach the same conclusion), silences
  (which outlets or countries plausibly should have covered this and
  didn't), and single-outlet findings.
- **`analyses/<DATE>_<lineage_id>_headline.json`** — same shape but
  operating only on titles, so a downstream step can compare to the
  body analysis and produce a sensationalism index per outlet.
- **`sources/<DATE>_<lineage_id>.json`** — per-quote speaker attribution
  (who got quoted, what's their role).

The matrix runs in parallel via GitHub Actions, with `fail-fast: false`
so one story's regression doesn't cancel siblings. Each LLM session has
its own ~25-min budget and only ever sees one briefing's worth of
context.

After the matrix completes, **`analyze_render`** validates every JSON
(`core/analyze/validate.py` enforces schema + citation grounding +
number reconciliation), augments metrics with population-weighted frame
distribution, computes headline-body divergence, aggregates source
attribution, renders Markdown, runs the longitudinal aggregator, and
commits everything. **~25-40 min for the matrix + ~5 min for render.**

### 9. Render + publish + distribute

Everything downstream of the analysis JSON lives under `publish/` — the
content layer, kept separate from the `core/` research product.

- **`publish/render/thread.py`** and **`carousel.py`** —
  deterministic templates over the analysis JSON; no LLM. Hook priority
  for social drafts: paradox > divergence outlier > exclusive vocab >
  generic.
- **`publish/render/prompts/draft_long.md`** runs Sonnet over the
  analysis to write the long-form blog/post draft.
- **`publish/api/build_index.py`** assembles the public `api/` tree and
  deploys to GitHub Pages.
- **`publish/distribute/stage.py`** stages drafts to a pending queue
  for downstream poster bots.

**~10 min for draft + publish + distribute combined.**

---

## Deep dive

Detailed technical documentation:

- [**`docs/ARCHITECTURE.md`**](docs/ARCHITECTURE.md) — system diagram,
  per-script I/O reference, cadence table
- [**`docs/METHODOLOGY.md`**](docs/METHODOLOGY.md) — the analytical
  decisions: cross-lingual similarity, dynamic clustering + salience
  ranking, cross-day lineage, weighted frame distribution,
  multiple-testing corrections, every methodology change explained
- [**`docs/OPERATIONS.md`**](docs/OPERATIONS.md) — cron setup, the
  `CLAUDE_CODE_OAUTH_TOKEN` secret, manual runs, health alerts,
  retention rollup
- [**`docs/API.md`**](docs/API.md) — the public JSON API contract,
  every schema, CORS policy, polling cadence
- [**`docs/COVERAGE.md`**](docs/COVERAGE.md) — country-by-country grade
  table + the structural blind spots that survive
- [**`docs/RETENTION.md`**](docs/RETENTION.md) — snapshot/briefing
  archival policy (>90-day artefacts bundled into
  `data/archive/rollup/`)
- [**`docs/REPLICATION.md`**](docs/REPLICATION.md) — replay any past
  day's analytics from its frozen snapshot

---

## Quick start

```bash
git clone <repo> && cd epistemic-lens
pip install -r requirements.txt

# Run today's deterministic pipeline locally (matches the cron's ingest job)
python -m core.ingest.pull_feeds
python -m core.ingest.extract_bodies
python -m core.ingest.dedup
python -m core.ingest.health
python -m core.embed.encode                # downloads ~2GB on first run
python -m core.cluster.cluster_daily       # HDBSCAN over the day's articles
python -m core.cluster.salience            # rank clusters, pick top 15
python -m core.briefing.build              # one briefing per top cluster
python -m core.metrics.cross_bucket

# Test (offline; no network, no embedding model)
python -m unittest tests.tests tests.tests_edge
```

The analyze + draft + publish stages run via GitHub Actions only; see
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the one-time
`CLAUDE_CODE_OAUTH_TOKEN` setup.

---

## Methodology pin

Every input that affects analytical output (feeds list, stopwords,
frames codebook, prompts, embedding model, schema definitions, model
identifiers) is hashed in `core/config/meta_version.json`. Every
artifact (snapshot, briefing, metrics, analysis, draft) carries the
active `meta_version` so longitudinal consumers know which era they're
reading.

```bash
python scripts/baseline_pin.py --check                       # CI gate
python scripts/baseline_pin.py --bump minor --reason "..."   # bumper
```

CI's `meta-check.yml` workflow enforces hash match on every push and PR.

**Bump rules:**
- `patch` — no output change (typo fix, comment, internal refactor)
- `minor` — forward-compatible addition (new feed, new optional field)
- `major` — invalidates longitudinal comparison (changed similarity
  formula, swapped embedding model, changed the clusterer)

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the full policy
and the per-version changelog.

---

## Coverage

235 feeds across 55 countries. ~85% body-text extraction success on a
typical day. Highlights:

- **Mass-tabloid press:** Daily Mail (UK), Bild (DE), Komsomolskaya Pravda (RU)
- **Right-populist:** Daily Wire / Breitbart (US), Republic World / Aaj Tak (IN), Junge Freiheit (DE), Sky News Australia
- **Native multilingual:** Russian (Russia + diaspora), Hindi (Aaj Tak, Bhaskar), Korean (Chosun, Yonhap), Persian (Iran International, IRNA), Arabic (Al Jazeera, Al Arabiya), Japanese (NHK, Mainichi)
- **Pan-regional:** Middle East Eye, AfricaNews, The Diplomat
- **State-TV / religious:** Vatican News, France 24 AR/ES, Sputnik International, RT Africa

Country-by-country grade table in
[`docs/COVERAGE.md`](docs/COVERAGE.md).

---

## File map

```
epistemic-lens/
├── README.md                         ← you are here (research-product README)
├── requirements.txt
│
├── core/                             ← THE RESEARCH PRODUCT
│   ├── meta.py                       ← config loader / asserter / stamper
│   ├── config/
│   │   ├── outlets.json              ← flat list of 235 outlets (country/lang/lean tags)
│   │   ├── feeds.json                ← nested ingest config (235 feeds, 55 countries)
│   │   ├── country_weights.json      ← per-country aggregate weights
│   │   ├── outlet_quality.json       ← per-outlet quality tier
│   │   ├── frames_codebook.json      ← Boydstun/Card 15-frame taxonomy
│   │   ├── stopwords.txt
│   │   └── meta_version.json         ← methodology pin (the spine)
│   │
│   ├── ingest/                       ← DATA INGEST
│   │   ├── pull_feeds.py             ← parallel RSS fetcher
│   │   ├── extract_bodies.py         ← Trafilatura body extraction + Wayback fallback
│   │   ├── dedup.py                  ← URL canonicalisation + title near-dup + cross-day state
│   │   ├── health.py                 ← health snapshot + alerts
│   │   ├── coverage_matrix.py        ← per-feed coverage product
│   │   ├── rollup.py                 ← weekly snapshot/briefing tarball retention
│   │   └── feed_rot_check.py         ← weekly rot detection
│   │
│   ├── embed/
│   │   ├── encode.py                 ← multilingual embedding cache (one .npy per day)
│   │   └── article_id.py             ← versioned article identifier
│   │
│   ├── cluster/                      ← DYNAMIC STORY DISCOVERY
│   │   ├── cluster_daily.py          ← HDBSCAN over every article in the day's set
│   │   ├── salience.py               ← rank clusters, pick the top N for briefing
│   │   └── lineage.py                ← cross-day cluster lineage (member-ID Jaccard)
│   │
│   ├── briefing/
│   │   ├── build.py                  ← one outlet-keyed corpus per top cluster
│   │   ├── qualifying.py             ← analyze-matrix gate (n_outlets >= 3)
│   │   └── coverage_warnings.py      ← structural-silence caveats per briefing
│   │
│   ├── metrics/                      ← cross_bucket + within-language LLR / PMI
│   │
│   ├── analyze/                      ← LLM framing-analysis layer
│   │   ├── prompts/                  ← daily_analysis / headline / source_attribution
│   │   ├── validate.py               ← schema + citation + number reconciliation
│   │   ├── restamp.py                ← refresh meta_version on agent JSON output
│   │   └── divergence.py             ← headline-body sensationalism index
│   │
│   └── compare/                      ← longitudinal cross-comparators
│       ├── longitudinal.py / robustness.py / lag.py
│       ├── wire_baseline.py / tilt.py / mc_correction.py
│       └── source_aggregation.py
│
├── publish/                          ← DOWNSTREAM CONTENT PRODUCT (own README)
│   ├── render/                       ← analysis/sources Markdown + thread/carousel
│   ├── api/                          ← api/ tree for GitHub Pages + JSON schemas
│   ├── distribute/                   ← poster staging
│   ├── web/                          ← static landing page
│   └── video/                        ← dormant
│
├── data/                             ← runtime artefacts (mostly gitignored)
│   ├── snapshots/                    ← daily ingest output + <DATE>_clusters.json
│   ├── briefings/                    ← per-cluster corpora, keyed by lineage_id
│   ├── analyses/ sources/ drafts/ coverage/ trajectory/
│   └── archive/
│       ├── rollup/                   ← snapshot/briefing tarballs >90 days old
│       └── pre-v10/                  ← frozen v9.x data snapshot (see SUNSET.md)
│
├── tests/
│   ├── tests.py                      ← crucial v10 regression suite (offline)
│   └── tests_edge.py                 ← RSS parser + dedup edge cases (offline)
│
├── scripts/                          ← one-off operational scripts (baseline_pin, replay, …)
│
├── docs/                             ← deep-dive documentation (see "Deep dive" above)
│
└── .github/workflows/
    ├── daily.yml                     ← per-cluster matrix daily cron
    ├── weekly.yml                    ← Mondays: cross-outlet lag + tilt + rollup + lineage
    ├── weekly_rot.yml                ← Sundays: feed rot report
    └── meta-check.yml                ← required check (pin + unit tests) on every push
```

---

## Help, feedback, issues

- Help with this project: open an issue at
  [github.com/Hwesto/epistemic-lens/issues](https://github.com/Hwesto/epistemic-lens/issues)
- Help with Claude Code (the CLI): `/help` or
  [github.com/anthropics/claude-code/issues](https://github.com/anthropics/claude-code/issues)
