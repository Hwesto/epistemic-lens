# Epistemic Lens

**Daily framing comparison across mainstream international press.**

Every morning, this project pulls articles from 235 RSS feeds across 55
country/region buckets, decides which "story" each article is about
(using an AI that understands articles in Persian, Arabic, Chinese, and
English equally well), and has Claude write one structured framing
analysis per story — showing how outlets across 55 countries frame the
same event differently.

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

The story matcher works across non-Latin scripts (Persian, Arabic,
Chinese, Japanese, Korean, Hindi, Hebrew, Russian) by encoding article
meaning as a numerical vector — articles about the same topic land close
together in vector space regardless of their language. So a Persian Iran
International article about southern Lebanon ends up in the same
briefing as a BBC English piece about the same border conflict.

Per-day coverage stats land in `snapshots/<date>_health.json`.

---

## What lands every morning

For each story (typically 10-13 per day), the cron publishes a folder
on GitHub Pages:

```
hwesto.github.io/epistemic-lens/<DATE>/<story_key>/
  briefing.json     ← the corpus: every relevant article from every bucket
  metrics.json      ← cross-bucket similarity, distinctive vocabulary
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
module under `pipeline/` (data ingest) or `analytical/` (analysis), and
each is independently runnable for local development.

### 1. Ingest — pull every RSS feed

**`pipeline/ingest.py`** fetches all 235 RSS feeds concurrently using
30 worker threads with a per-host rate limit and exponential backoff
on server errors. Parses RSS, Atom, and RDF feeds, then writes
`snapshots/<DATE>.json` with raw items: title, link, summary,
publish date, plus flags like "title-only feed" or "Google News proxy."
Failed feeds get marked and reported rather than retried to death.
**~10 min.**

### 2. Extract — fetch the full article body

**`pipeline/extract_full_text.py`** follows the article links and runs
each page through **Trafilatura** (an open-source library that strips
the navigation, ads, and boilerplate to leave just the article body).
About 85% of articles yield clean body text on a typical day. When the
host blocks the request (paywalls, Cloudflare 403s, anti-bot pages),
the script falls back to the **Wayback Machine** (web.archive.org)
which usually has an unblocked copy. Each item gets annotated with an
`extraction_status` (`FULL`, `PARTIAL`, `STUB`, `NONE`, `ERROR`).
**~3 min.**

### 3. Deduplicate + health-check

**`pipeline/dedup.py`** canonicalises URLs (strips UTM tracking params,
normalises `m.example.com` → `example.com`, decodes Google News proxy
links) so the same article posted to multiple feeds collapses to one
item. Title-Jaccard near-duplicates within a bucket collapse too. A
cross-day state file tracks wire-syndicated stories so AFP's coverage
of an event doesn't double-count across days.

**`pipeline/daily_health.py`** writes a health snapshot summarising
feed status, per-bucket extraction rates, and alerts. Two alert types:
**volume_drop** (a bucket's item count dropped >50% vs its trailing
7-day average — probably a feed broke), and **low_extraction** (a
bucket pulled items fine but bodies didn't extract — probably the host
started 403-ing). **~1 min total.**

### 4. Embed — convert each article into a vector

**`pipeline/embed_articles.py`** turns each article's text into a
1024-dimensional vector using **multilingual-e5-large**, an
**embedding model** — a neural network that converts text into
numerical vectors such that articles about the same topic end up close
together in vector space, regardless of language. So a Persian article
about Iran and an English article about Iran will produce vectors that
point in similar directions, even though their characters share
nothing in common.

The vectors get written to `snapshots/<DATE>_embeddings.npy` with a
versioned cache key — bumping the embedding model OR the way we
extract text from articles invalidates the cache automatically so
stale vectors can never silently get served. **~12 min on the
2-core Actions runner.**

### 5. Match — assign each article to a canonical story

The project tracks 15 **canonical stories** — recurring international
narratives like the Ukraine war, China-Taiwan tensions, Iran nuclear
program, Hormuz Strait, Israel-Palestine, etc. Each story has 3-8
**anchor sentences** that describe it (e.g. for Lebanon: "Israeli
forces hold positions in southern Lebanon and strike Hezbollah targets
south of the Litani River"). Anchors are written in English plus
native scripts (Persian, Arabic) where the story has strong
non-Latin-language coverage.

**`analytical/perception.py`** encodes every story's anchors with the
same model from stage 4 and averages them into a **centroid** — a
single vector that represents "what this story looks like in
embedding space." Then for each article, it computes the **cosine
similarity** to every story's centroid. Cosine similarity is the
standard way to measure how closely two vectors point in the same
direction: 1.0 = identical meaning, 0.0 = unrelated, with most
in-domain news articles landing in the 0.5–0.9 range.

The article gets assigned to whichever story it scores highest against
— this is called **softmax-argmax assignment**: compare against all
15 stories simultaneously and pick the strongest. The assignment only
counts if (a) the top cosine clears a floor (default 0.40, so articles
that don't strongly match anything get rejected) and (b) the top score
beats the second-best by a small margin (the "open-world filter" — an
article roughly equidistant from many stories doesn't strongly belong
to any of them).

This is what unlocks the multilingual coverage: a Persian Iran
International article about southern Lebanon (cosine ≈ 0.84 against
Lebanon's mixed Persian + Arabic + English anchors) gets correctly
grouped with English coverage from BBC, Al Jazeera, Times of Israel,
and so on. The matcher is calibrated against a 343-row hand-labelled
test set — see
[`calibration/perception_eval_report.md`](calibration/perception_eval_report.md)
for the full record (test accuracy ~82%).

**`analytical/build_briefing.py`** then collects the matched articles
into per-story corpora — up to 2 articles per bucket, chosen to
maximise framing diversity (titles too similar to an already-kept one
get dropped). Each entry carries its matcher confidence scores for
auditing. **~3 min.**

### 6. Metrics + within-language signals

**`analytical/build_metrics.py`** measures how different the buckets'
coverage looks from each other for each story:

- **Pairwise similarity:** average vector similarity between every
  pair of buckets (e.g. how much do German articles about Hormuz
  resemble Indian articles about Hormuz?). The base similarity uses
  **LaBSE**, a separate multilingual embedding model used here for its
  speed on the small bucket-mean computation.
- **Isolation:** which bucket sits furthest from everyone else (an
  outlier — possibly framing the story uniquely, possibly just
  covering a different angle entirely).
- **Bucket-exclusive vocabulary:** words that appear in exactly one
  bucket and nowhere else (often the most revealing tell of how that
  bucket is framing the story differently).

**`within_language_llr.py`** and **`within_language_pmi.py`** compute
additional within-language signals — log-likelihood-ratio distinctive
vocab and pointwise-mutual-information bigram associations within each
language stratum, so vocabulary differences between buckets aren't
confounded by them speaking different languages. **~3 min.**

### 7. Discover — cluster the leftovers

Articles the matcher didn't assign (typically a few thousand per day —
either they didn't strongly match any canonical story or they were
equidistant from too many) are the discovery surface for emerging
stories the canonical set doesn't cover yet.

**`pipeline/discover_residual.py`** runs **HDBSCAN** over the residual
vectors. HDBSCAN is a clustering algorithm: it groups vectors that are
dense neighbours of each other and ignores outliers as "noise" (no
forced cluster assignment). For each cluster it finds, the script
records the member article IDs, which buckets contributed, and the
most common words in their titles.

Weekly, **`analytical/persistence_tracker.py`** chains clusters across
days by checking the **Jaccard overlap** of their member article IDs —
if today's cluster shares ≥30% of articles with yesterday's, it's the
same lineage. (Jaccard overlap = intersection / union of two sets;
0.30 = 30% of the combined article set appears in both clusters.)
Lineages that persist ≥ 3 days with ≥ 4 different buckets get
surfaced by **`analytical/auto_promote.py`** as promotion candidates
in `archive/auto_promoted_<DATE>.md` — a human-decision artefact, never
a silent canonical mutation. **~2 min daily; weekly review.**

### 8. Analyze — Claude writes the framing analyses

For each qualifying story (n_buckets ≥ 3), the workflow spawns a
**separate Sonnet session** via `anthropics/claude-code-action@v1`.
Each session reads ONE briefing + ONE metrics file and writes:

- **`analyses/<DATE>_<story>.json`** — frames identified (2-8, drawn
  from a closed 15-frame codebook: ECONOMIC, MORALITY, FAIRNESS,
  SECURITY_DEFENSE, etc. The codebook is from
  Boydstun & Card's published framing research; using a fixed
  vocabulary across all stories makes longitudinal comparison
  possible), supporting quotes (verbatim, citation-validated against
  the briefing corpus), paradox (opposing-bloc convergence — when two
  ideologically opposed outlets reach the same conclusion), silences
  (which buckets plausibly should have covered this and didn't), and
  single-outlet findings.
- **`analyses/<DATE>_<story>_headline.json`** — same shape but
  operating only on titles, so a downstream step can compare to the
  body analysis and produce a sensationalism index per outlet.
- **`sources/<DATE>_<story>.json`** — per-quote speaker attribution
  (who got quoted, what's their role, what stance did they take).

The matrix runs in parallel via GitHub Actions, with `fail-fast: false`
so one story's regression doesn't cancel siblings. Each LLM session has
its own ~25-min budget and only ever sees one briefing's worth of
context.

After the matrix completes, **`analyze_render`** validates every JSON
(`validate_analysis.py` enforces schema + citation grounding + number
reconciliation), augments metrics with population-weighted frame
distribution, computes headline-body divergence, aggregates source
attribution, renders Markdown, runs the longitudinal aggregator, and
commits everything. **~25-40 min for the matrix + ~5 min for render.**

### 9. Render + publish + distribute

- **`publication/render_thread.py`** and **`render_carousel.py`** —
  deterministic templates over the analysis JSON; no LLM. Hook priority
  for social drafts: paradox > divergence outlier > exclusive vocab >
  generic.
- **`.claude/prompts/draft_long.md`** runs Sonnet over the analysis to
  write the long-form blog/post draft.
- **`publication/build_index.py`** assembles the public `api/` tree and
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
  decisions: cross-lingual similarity, perception layer (embedding
  softmax-argmax + calibration record), discovery layer, weighted frame
  distribution, multiple-testing corrections, every methodology change
  explained
- [**`docs/OPERATIONS.md`**](docs/OPERATIONS.md) — cron setup, the
  `CLAUDE_CODE_OAUTH_TOKEN` secret, manual runs, health alerts,
  retention rollup
- [**`docs/API.md`**](docs/API.md) — the public JSON API contract,
  every schema, CORS policy, polling cadence
- [**`docs/COVERAGE.md`**](docs/COVERAGE.md) — bucket-by-bucket grade
  table + the structural blind spots that survive
- [**`docs/RETENTION.md`**](docs/RETENTION.md) — snapshot/briefing
  archival policy (>90-day artefacts bundled into `archive/rollup/`)
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
python -m core.briefing.build
python -m core.metrics.cross_bucket
python -m core.cluster.cluster_daily

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

CI's `meta-check.yml` workflow enforces hash match on every push and PR.

**Bump rules:**
- `patch` — no output change (typo fix, comment, internal refactor)
- `minor` — forward-compatible addition (new story, new feed, new
  optional field)
- `major` — invalidates longitudinal comparison (changed similarity
  formula, swapped embedding model, removed a story)

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the full policy
and the per-version changelog.

---

## Coverage

235 feeds across 55 buckets. ~85% body-text extraction success on a
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
├── README.md                         ← you are here
├── meta_version.json                 ← methodology pin (the spine)
├── meta.py                           ← loader / asserter / stamper
├── baseline_pin.py                   ← pin bumper / CI check
├── stopwords.txt                     ← pinned (hashed)
├── canonical_stories.json            ← 15 stories: anchor sentences + per-story floor
├── feeds.json                        ← 235 feeds, 55 buckets (hashed)
│
├── .github/workflows/
│   ├── daily.yml                     ← per-story matrix daily cron
│   ├── weekly.yml                    ← Mondays: cross-outlet lag + tilt + rollup + persistence
│   ├── golden.yml                    ← Sundays: matcher accuracy regression check
│   ├── meta-check.yml                ← required check on every PR
│   ├── ci.yml                        ← unit/edge/e2e tests
│   └── weekly_rot.yml                ← Sundays: feed rot report
│
├── .claude/prompts/
│   ├── daily_analysis.md             ← body-pass framing analysis (Sonnet, JSON)
│   ├── headline_analysis.md          ← headline-only pass (Sonnet, JSON)
│   ├── source_attribution.md         ← per-quote speaker attribution (Sonnet, JSON)
│   └── draft_long.md                 ← long-form blog/post draft (Sonnet, prose)
│
├── pipeline/                         ← DATA INGEST
│   ├── ingest.py                     ← parallel RSS fetcher
│   ├── extract_full_text.py          ← Trafilatura body extraction + Wayback fallback
│   ├── dedup.py                      ← URL canonicalisation + title near-dup + cross-day state
│   ├── daily_health.py               ← health snapshot + bucket alerts
│   ├── embed_articles.py             ← multilingual-e5-large embedding cache
│   ├── discover_residual.py          ← HDBSCAN clustering over unassigned articles
│   ├── rollup.py                     ← weekly snapshot/briefing tarball retention
│   └── feed_rot_check.py             ← weekly rot detection
│
├── analytical/                       ← ANALYSIS
│   ├── perception.py                 ← softmax-argmax story matcher (embedding-based)
│   ├── build_briefing.py             ← per-story corpus assembler
│   ├── build_metrics.py              ← LaBSE pairwise + isolation + exclusive vocab
│   ├── within_language_llr.py        ← distinctive vocab per language stratum
│   ├── within_language_pmi.py        ← bigram associations per language stratum
│   ├── validate_analysis.py          ← schema + citation + number reconciliation
│   ├── list_qualifying_stories.py    ← matrix bootstrap helper
│   ├── headline_body_divergence.py   ← sensationalism index per outlet
│   ├── source_aggregation.py         ← daily rollup of speaker attribution
│   ├── longitudinal.py               ← frame-share trajectories per story
│   ├── robustness_check.py           ← day-over-day Jaccard stability
│   ├── cross_outlet_lag.py           ← weekly cross-correlation (who-follows-whom)
│   ├── wire_baseline.py              ← rolling 90-day wire bigram baseline
│   ├── tilt_index.py                 ← per-outlet log-odds vs wire (Benjamini-Hochberg corrected)
│   ├── persistence_tracker.py        ← residual cluster lineage across days
│   ├── auto_promote.py               ← token + lineage promotion review notes
│   └── restamp_analyses.py           ← refresh meta_version on agent JSON output
│
├── calibration/                      ← PERCEPTION-LAYER CALIBRATION
│   ├── eval_set.jsonl                ← 343-row hand-labeled test set
│   ├── embedding_anchors_draft.json  ← per-story anchor sentences (English + multilingual)
│   ├── benchmark_models.py           ← three-way embedding-model bench
│   ├── parity_check.py               ← weekly accuracy-drift cron entry point
│   └── perception_eval_report.md     ← calibration verdict
│
├── publication/                      ← RENDER + PUBLISH
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
├── tests_perception.py               ← perception-layer tests
├── tests_discovery.py                ← discovery-layer tests
│
├── web/                              ← static landing page (Pages root)
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
