# Visualization Plan — Epistemic Lens frontend

A design spec for a data-journalism frontend: a set of recurring,
data-driven visualizations that a daily editorial piece can be built
around. This document is **plan only** — no code is changed by it.

This is **v2** of the plan. v1 took the project's metrics at face value
and proposed a chart for each. This revision instead audited what the
pipeline *actually* produces — verified against the code, not the prose
docs — and asks which framings the data can **defend**, and which it
cannot.

The headline conclusion: **the project is frame-first, not
cluster-first.** Its unique, defensible asset is the *frame matrix* — a
fixed 15-frame vocabulary applied with verbatim citations across N
outlets in M countries for one event. The HDBSCAN cluster landscape is
a good "explore today" doorway, but it is **not** where the defensible
daily stories live. The two visualizations that lean hardest on raw
embedding geometry — a 2D cluster scatter, and a re-embedded "word
axis" — are the weakest ideas in the catalogue: they manufacture axes a
reader cannot name. Both are kept, but **re-specified** to encode only
real, nameable quantities. See §8.

It answers four questions:

1. How good are the current pipeline / API outputs for visualization?
2. What must change first — the v9→v10 migration **and** the metrics
   that are mis-specified for journalism?
3. What is the full catalogue of visualizations worth building?
4. What was rejected, and why.

---

## 1. Current state

### The frontend today

The public site (`publish/web/`) is **not a data application**. It is a
static site rendered server-side at deploy time by
`publish/api/build_index.py` → `page_renderers.py` / `card_renderers.py`.
`app.js` is 73 lines of share / copy / keyboard-nav; it never fetches the
API. Every "page" is baked HTML.

Visualizations that exist today are all pure CSS/HTML:

- `render_frames_matrix` — an HTML `<table>` of frames × buckets
- `render_isolation_panel` — CSS-width horizontal bars
- `render_coverage_page` — a table of filled / hollow dots
- block-character (`█░`) language bars

There is no SVG, no map, no scatter plot, no time series, and no
client-side interactivity beyond share/copy. The **dormant**
`publish/video/` pipeline contains a real `react-simple-maps` `WorldMap`
+ `CountryPin` and a bundled `world-110m.json` topology — useful proof
the data can drive a map, and components worth salvaging.

### Output grading (verified against the code, May 2026)

The `data/` tree is gitignored and empty in a fresh checkout — outputs
are regenerated each cron — so this grading was checked against the
producing code, the schemas, and the analyze prompts directly.

| Artifact | In public API? | v10-keyed? | Viz-grade |
|---|---|---|---|
| `analysis.json` — frames, evidence, paradox, silences, isolation, exclusive vocab | yes | **yes** (verified: `analysis.schema.json` keyed on `lineage_id` / `outlet` / `country`) | **A — best-supported, fully v10** |
| `briefing.json` — per-article corpus w/ `outlet`/`country`/`lang`/`lean`/`section` tags | yes | **yes** | **A — clean raw material** |
| `metrics.json` (`core/metrics/cross_bucket.py`) | yes | **no** (verified: still emits `story_key`, `n_buckets`, `bucket_exclusive_vocab`; groups by `country`, never `outlet`; docstring + output path are v9) | C — see §2 |
| `trajectory.json` — frame share over time + drivers | yes | **no** — `story_key`-keyed | C — see §2 |
| `tilt.json` — bigram log-odds vs wire baseline | yes | **no** | C — see §2 |
| `within_lang_llr` / `within_lang_pmi` — distinctive terms / bigrams | yes (per story) | **no** | C — see §2/§3 |
| `sources.json` — per-quote speaker attribution | yes | **no** | C — see §2 |
| `coverage.json` — per-(story,feed) coverage + silence states | yes | **no** | C — see §2 |
| `<date>_clusters.json` — the full HDBSCAN landscape (50–200 clusters) | **no** | yes | not exposed — see §4 |
| 2D embedding projection | **does not exist** | — | **not needed** — rejected, see §8 |
| semantic word grouping | **does not exist** | — | **replaced** by a render-time join, see §4 |

The `analyze` + `briefing` layer is genuinely v10 and genuinely good.
Everything downstream of it is not. Two of the schemas actively
contradict their own producers (verified):

- `metrics.schema.json` lists `pairwise_jaccard` as `required`; the
  producer emits `pairwise_similarity`.
- `index.schema.json` requires `n_buckets` / `top_isolation_bucket`;
  `docs/API.md` documents `n_outlets` / `n_countries` /
  `top_isolation_outlet`.

### The thesis: build on frames, not on geometry

Every reliable visualization below is a different cut of one object:
`analysis.frames[]`. A frame entry carries a `frame_id` from a **closed,
fixed 15-frame codebook** (Boydstun/Card), an optional free-text
`sub_frame`, the `outlets[]` and `countries[]` carrying it, and
`evidence[]` — verbatim quotes with a `signal_text_idx`. That is a
**categorical, nameable, citation-grounded** structure:

- frames × country → a heatmap (V2)
- one frame's countries → a choropleth (V5)
- frames over days → a trajectory (V3)
- two opposed outlets, one shared frame → a paradox diagram (V6)
- frame × political `lean` → a bias grid (V11)

None of these needs a projection, a re-embedding, or a manufactured
axis. They are strong *because* their axes are things a reader can
name. The cluster landscape and the raw embedding space are, by
contrast, 1024-dimensional objects with no nameable axes — useful for
*grouping* (which is what HDBSCAN already does) but not for *plotting*.

This maps directly onto the three requests that prompted the plan:

| Request | Delivered by | Note |
|---|---|---|
| Cluster map w/ country flags for the HDBSCAN intro | **V1** | re-specified as a packed-bubble / treemap, **not** a scatter — see §8 |
| Framing comparison ("eco" etc.) | **V2** | the flagship; data is grade-A today |
| Word groups ("threat" camp vs "peace" camp), *not hard-set* | **V4** | grouped by the **emergent-per-story frames**, not a hand-coded lexicon and not a re-embedded axis — see §4/§8 |

---

## 2. Prerequisite A — the v9 → v10 migration

The docs (METHODOLOGY / ARCHITECTURE / API / README) describe **v10** —
outlets as the atomic unit, `lineage_id`, emergent HDBSCAN clusters. The
ingest → cluster → briefing → analyze layer **is** v10. The downstream
layer was never migrated, and this **blocks every chart below**:

| Component | Problem (verified) |
|---|---|
| `core/metrics/cross_bucket.py` | Groups by `country` (`art.get("country") or art.get("bucket")`). Emits `n_buckets`, `isolation[].bucket`, `bucket_exclusive_vocab`, `story_key`, `story_title` — never per-outlet, despite the v10 promise that the outlet is the atomic unit. Module docstring and output path are still v9. |
| `publish/api/build_index.py` | Reads `e.get("bucket")` on the corpus. v10 corpus entries have `country`, not `bucket` → `n_buckets` collapses to `1`, `top_isolation` breaks, tilt-file matching breaks. The card picker scores on `story_key` / `n_buckets`. |
| `metrics.schema.json` | `required` lists `pairwise_jaccard`; the producer emits `pairwise_similarity`. |
| `index.schema.json` | Requires `n_buckets` / `top_isolation_bucket`; API.md documents `n_outlets` / `n_countries` / `top_isolation_outlet`. |
| `coverage` / `trajectory` / `sources` / `tilt` / `word` schemas | All keyed on `story_key` + `bucket`. |

**Migration scope (Phase 0):**

1. `cross_bucket.py` → compute at **outlet** granularity (the v10
   promise). The frontend aggregates outlet → country for map views.
   This is a methodology change → **major meta-version bump**, with a
   `--reason`.
2. Re-key 6 schemas: `story_key` → `lineage_id`, `bucket` → `outlet`
   (or `country` where geography is the intent). Fix `pairwise_jaccard`
   → `pairwise_similarity` in `metrics.schema.json`.
3. `build_index.py` and `page_renderers.py` / `card_renderers.py` read
   `outlet` / `country`, never `bucket`. Re-key the card / hero pickers
   off `story_key` → `lineage_id`.
4. `index.json`: `n_buckets` → `n_outlets` + `n_countries`;
   `top_isolation_bucket` → `top_isolation_outlet`.

Until this lands, every chart sits on a unit (the country bucket) the
methodology says was abandoned, and the unit v10 promises (the outlet)
is invisible.

---

## 3. Prerequisite B — metrics mis-specified for journalism

The migration fixes the *keys*. It does not fix three metric *choices*
that are defensible as research but wrong for a daily chart. Fix these
in the **same major bump** as §2 — re-keying the metrics file is already
a breaking change, so absorb the corrections there.

### 3.1 Weighted frame share → unweighted share + CI band

`weighted_frame_distribution` weights each bucket by `population_m ×
audience_reach` (`bucket_weights.json`). That weighting is an *editorial
judgment* — it decides Indonesia's framing "counts more" than Norway's —
and it is the single easiest thing for a critic to attack in a chart
caption. The **bootstrap CI machinery is genuinely good and stays.**

For the chart, publish the **unweighted per-frame share with its 5/95
CI band**: *"this frame appeared in 6 of 22 outlets [CI 2–11]"* is
honest and needs no contestable weighting. Keep the weighted number as
an optional toggle, never the default.

### 3.2 Three distinctiveness statistics → two for viz, drop one

The pipeline computes within-language **LLR**, within-language
**PMI-bigrams**, and **tilt-vs-wire**. They are not interchangeable:

- **LLR (Dunning)** — "which words does this outlet use more than its
  same-language peers." Legible. One chart (V4).
- **Tilt** — a *different* question: "how far is this outlet's language
  from the wire copy everyone started with." Also legible. Its own
  chart (V8).
- **PMI-bigrams** — LLR-for-word-pairs: the same question as LLR, a
  noisier estimator, no separate journalism angle.

**Drop PMI as a visualization input.** Keep it in the pipeline if it is
cheap; never build a chart on it. Rule: one distinctiveness statistic
per chart, and a reader must be able to name what it measures.

### 3.3 Isolation is a supporting metric, not a hero

`isolation` (mean cosine to other outlets) is real but fragile at the
~20-outlet scale of a single cluster — the existing thin-bucket
exclusion logic is itself evidence the authors know it is noisy. It is
fine as a supporting beeswarm (V10) that adds texture to a framing
piece; it must **not** headline a daily piece on its own. No archetype
in the editorial rotation should resolve to "isolation".

---

## 4. New data needed — one artifact, one join

v1 of this plan proposed three new artifacts (N1 `clusters.json`, N2 a
2D projection, N3 a re-embedded "vocab map"). The audit kept **one**,
rejected **one** outright, and replaced **one** with a cheap join.

### N1 — `clusters.json` (the daily landscape) — KEPT

A published, lightweight form of `data/snapshots/<date>_clusters.json`.
Today the API ships only the top ~15 briefed stories; the
50–200-cluster landscape — "everything the world talked about today" —
is invisible.

Proposed `/api/<date>/clusters.json`:

```json
{
  "meta_version": "...", "date": "2026-05-20",
  "n_clusters": 87, "n_articles_clustered": 1840, "n_noise": 410,
  "clusters": [
    {
      "cluster_id": 7,
      "lineage_id": "Le4f8a39c1d",      // present only if briefed
      "is_top": true,                    // entered the top-15
      "n_articles": 38, "n_countries": 14, "n_outlets": 22, "n_langs": 5,
      "stability": 0.71, "salience_score": 28.4,
      "top_tokens": ["hormuz", "strait", "tanker"],
      "country_distribution": {"usa": 6, "iran": 4},
      "lang_distribution": {"en": 20, "fa": 7},
      "dominant_frame": "SECURITY_DEFENSE"  // top-15 only (joined from analysis)
    }
  ]
}
```

Note there is **no `centroid_xy`** — see the projection rejection in §8.
Cost: a copy + a `dominant_frame` join in `build_index.py`. Cheap.

### N2 — 2D embedding projection — REJECTED

v1 proposed projecting the day's 1024-dim embeddings to 2D (UMAP/PCA) to
give the cluster map real coordinates. **Rejected.** A 2D projection of
high-dimensional multilingual embeddings produces axes with no nameable
meaning, distorts distances (clusters that look adjacent need not be
related), and — even with a pinned seed — re-projects to a completely
different layout each day as the article pool changes, so the map is
not comparable day to day. Data-journalism readers over-read spatial
position. V1 is re-specified (§8) to need no projection at all.

### N3 — the words-by-frame join (replaces the "vocab map")

v1 proposed a new pipeline step that re-embeds each distinctive term and
re-clusters the term embeddings into "emergent semantic groups."
**Rejected as a pipeline step** — `e5` embeds isolated words poorly, the
emergent term-clusters have no stable identity, and a "framing axis =
PC1 of term embeddings" is another manufactured axis (§8).

Replaced by a **deterministic render-time join** over two artifacts that
already exist after Phase 0:

1. The LLR layer gives distinctive terms **per outlet**.
2. `analysis.frames[]` lists, per frame, the `outlets[]` carrying it and
   the `evidence[]` quotes.
3. For each distinctive term *T* of outlet *O*: if *T* appears in an
   `evidence.quote` cited for frame *F* by outlet *O*, bind *T → F*
   directly. Otherwise fall back to the frame(s) *O* carries.

Result: every distinctive word is tagged with the frame its own
coverage was assigned. **No embedding, no clustering, no methodology
bump** — it reads two published files and can live in `build_index.py`
or a render helper. The groups are still emergent (which frames appear,
and which words land under them, is decided per story from evidence) —
the *codebook* is fixed, which is the feature, not the bug: it is what
makes the word groups comparable across days. This satisfies the
"not hard-set" requirement without maintaining a lexicon.

---

## 5. Cross-cutting design decisions

### Frame color system

All 15 Boydstun/Card frames get a **fixed palette**, defined once and
reused everywhere — landscape bubbles, frame matrix, trajectory, lean
grid. Consistent color = the reader learns "blue means ECONOMIC" once
and carries it across every chart. This belongs in a shared
`publish/api/site_config.py` constant. With the frame-first thesis this
is now the **most load-bearing** cross-cutting decision — do it first
in Phase 1.

### Country flags

A `country_code → flag emoji` map already exists as `BUCKET_FLAGS` in
`card_renderers.py`, keyed by country code, so it survives the v10
migration unchanged — just conceptually renamed.

### Mobile-first

The audience reads on phones (the existing card is phone-shaped, the
share/download-image flow is phone-shaped). Every visualization needs a
legible small-screen form — usually a simplified or vertically-stacked
variant, not the desktop chart shrunk.

### One striking thing per day

The editorial model is "one striking comparison per day" with a
7-archetype picker (`word`, `paradox`, `silence`, `shift`, `sources`,
`tilt`, `echo`; `today_picker.json` / `card_picker.json`). The catalogue
assigns **one signature visualization per archetype**, so the daily
picker also picks the day's hero chart. The cluster landscape (V1) sits
outside the rotation as a permanent "explore today" entry point.

---

## 6. The visualization catalogue

Each entry: what it shows, the data it needs, the journalism angle, the
build status (✅ data ready post-Phase-0 · ⚠️ needs §4 work · 🔶 needs a
small aggregator).

### V1 — Today's story landscape · ⚠️ needs N1

The day's HDBSCAN output as a **packed-circle chart** (primary) or a
**treemap** (alternative): one bubble per cluster, **radius =
`n_articles`**, **fill = `dominant_frame`** (top-15) or dominant
language (the long tail), country flags from `country_distribution`
arranged around each top-15 bubble. The long-tail clusters render as
small faint bubbles — "the conversations that did not cross borders."

- Data: `clusters.json` (N1). **No projection** — every visual channel
  (size, color, flags) encodes a named quantity; there is no x/y axis to
  over-read. See §8 for why this beats the scatter v1 proposed.
- Angle: *"Today the world's press split into 87 conversations. These 15
  crossed borders — here is the map."* The HDBSCAN intro piece.

### V2 — Cross-country framing matrix · ✅ (the flagship)

For one story: a heatmap, `frame_id` (rows) × outlet/country (columns),
cell shaded where that outlet carried the frame, the verbatim evidence
quote on hover/tap. A real-chart upgrade of today's HTML-table
`render_frames_matrix`.

- Data: `analysis.frames[]` (`outlets`, `countries`, `evidence`) —
  grade-A, available today.
- Angle: *"Everyone agreed it happened. Here is where they disagreed
  about what it meant."* — the signature **framing** viz.

### V3 — Frame share over time (the Shift) · ✅ after trajectory re-key

A multi-line or streamgraph of each frame's share of coverage, day by
day, for a persistent story. Inflection points annotated with the
`drivers` (the article URLs that moved the share). Render the
**unweighted share with its CI band** (§3.1).

- Data: `trajectory.json` (`frame_trajectories`, `drivers`).
- Archetype: **shift**.
- Angle: *"How the hantavirus story turned from health to economics in
  72 hours."*

### V4 — Distinctive vocabulary, grouped by frame (the Words) · ⚠️ needs the N3 join + LLR re-key

The distinctive words for a story, laid out by the **frame their own
coverage was assigned** (the §4 join). Two renders off the same data:

- **Grouped columns** — one column per frame present in the story, the
  distinctive terms stacked inside, sized by **LLR** (§3.2), each tagged
  with the flags/outlets that use it.
- **Beeswarm** — terms on a single line, *if* an explicit pole pair is
  wanted (e.g. SECURITY_DEFENSE-leaning frames vs FAIRNESS /
  POLICY_PRESCRIPTION). The pole ordering is an editorial choice and
  must be **labelled as such**, never derived from PCA.

- Data: LLR distinctive terms + `analysis.frames[]` evidence (joined).
- Archetype: **word**.
- Angle: *"Six outlets, six words for the same ceasefire — and they
  fall into two frames."* This is request #3 — emergent per-story
  groups, no hand-coded lexicon, no manufactured axis.

### V5 — Country coverage map (the Silence) · ✅

A world choropleth: each country shaded by how it covered a story
(fill = dominant frame), **hollow** where it carried items but stayed
silent on this story, struck-through where every feed failed
(structural, not editorial). Salvage the `publish/video/` `WorldMap`
component and its `world-110m.json` topology.

- Data: `briefing.countries_present`, `analysis.silences`,
  `analysis.coverage_caveats`, `coverage.non_coverage`.
- Archetype: **silence**.
- Angle: *"14 countries covered the Hormuz deal. Egypt ran Sisi instead."*

### V6 — Paradox convergence diagram · ✅

Two ideologically-opposed outlets as nodes on opposite sides, both
arrows landing on one shared `joint_conclusion` in the middle; each side
shows its verbatim quote and country flag.

- Data: `analysis.paradox` (`a`, `b`, `joint_conclusion`) — grade-A.
- Archetype: **paradox**.
- Angle: *"Iran's state press and its exiled opposition agreed on one
  thing today."*

### V7 — Whose voices (source composition) · ✅ after sources re-key

A stacked bar per outlet (or per country) of `speaker_affiliation_bucket`
— state / political / civilian / expert / wire / corporate / academic /
NGO. Shows whose voices a story platformed and whose it omitted.

- Data: `sources.json` (`speaker_affiliation_bucket`,
  `stance_toward_target`).
- Archetype: **sources**.
- Angle: *"Vietnam's state media quoted 7 officials and zero civilians."*

### V8 — Tilt vs the wire baseline · ✅ after tilt re-key (weekly)

A diverging dot plot: per outlet, the bigrams whose log-odds depart most
from the Reuters/AFP/AP wire baseline, positive tilt right, negative
left, dot size = `z_score`. One statistic, one chart (§3.2).

- Data: `tilt.json` (`anchors.wire.positive_tilt` / `negative_tilt`).
- Archetype: **tilt**.
- Angle: *"How far each outlet's language drifts from the wire copy
  everyone started from."*

### V9 — Echo / lag timeline · ✅ after lag re-key (weekly)

A small timeline showing a story propagating across a curated outlet
chain (wire → flagship → follower), the cross-correlation lag in days
drawn as the offset.

- Data: `lag.json` (CCF output from `core/compare/lag.py`).
- Archetype: **echo** (Monday weekly only).
- Angle: *"The Times of London ran the NYT framing 48 hours later."*

### V10 — Outlet isolation beeswarm · ✅ (supporting only)

A beeswarm of every outlet in a story by `mean_similarity` to the
cluster consensus; the outlier sits visibly alone at the low end. A
proper-chart upgrade of today's CSS `render_isolation_panel`.

- Data: `metrics.isolation` / `analysis.outlet_isolation_top`.
- **Supporting viz, never a hero** (§3.3). Use it to add texture beside
  V2, not to anchor a daily piece.

### V11 — Lean × frame bias grid · ✅ (single-story) · 🔶 (cross-corpus)

A grid: political `lean` (rows) × `frame_id` (columns), each cell
shaded by how often outlets of that lean carried that frame. Surfaces
systematic framing differences along the *pre-registered* `lean` tag.

- Data: `analysis.frames[].outlets` joined to `briefing.corpus[].lean`.
  Single-story version is a pure frontend join (✅). The punchy
  cross-corpus version ("Centre-right reaches for SECURITY_DEFENSE,
  Centre-left for FAIRNESS — across 200 stories") needs a small
  aggregator over `data/analyses/`.
- Angle: *"It is not which story they cover — it is which frame they
  reach for."* A **stronger bias story than tilt**: `lean` is a tag set
  in advance, not a statistic derived after the fact.

### V12 — Headline vs body divergence · ⚠️ needs divergence output exposed

`core/analyze/divergence.py` already compares the title-only frame pass
to the body pass and emits an `agreement_rate` and
`highest_diverging_outlets` — a sensationalism index. A simple
slope/dumbbell chart per outlet (headline frame → body frame) makes it
visible.

- Data: `divergence.py` output. **Verify it ships in the public API
  before building** — it is not in the per-story artifact list in
  API.md; exposing it is a small migration item.
- Angle: *"These outlets' headlines say one thing; their articles say
  another."*

### V13 — Frame co-occurrence network · 🔶 needs an aggregator

A network graph over accumulated `analysis.json`: nodes = the 15
frames, edge weight = how often two frames are assigned to the same
story. Shows which framings travel together (ECONOMIC ↔ SECURITY on
energy stories; MORALITY ↔ FAIRNESS on rights stories).

- Data: an aggregator over `data/analyses/` (no per-story artifact —
  this is an inherently longitudinal view).
- Angle: *"The frames the press never separates."* A genuinely novel
  view nothing in the pipeline computes today.

### Archetype → hero visualization

| Archetype | Hero viz |
|---|---|
| word | V4 vocabulary-by-frame |
| paradox | V6 convergence diagram |
| silence | V5 coverage map |
| shift | V3 frame trajectory |
| sources | V7 voice composition |
| tilt | V8 tilt dot plot |
| echo | V9 lag timeline |
| (landscape) | V1 packed-bubble — always-on "explore today" |

V2 (framing matrix), V10 (isolation), V11 (lean grid) and V12
(divergence) are **supporting** views that deepen any framing piece;
V13 is a standalone longitudinal feature.

---

## 7. Frontend architecture (decision deferred)

Two viable paths; the choice is deferred but the trade-off is recorded.

**Option A — client-side data app.** A small JS app fetching the JSON
API (`latest.json` → `index.json` → artifacts) and rendering interactive
charts. Best fit for data journalism: hover, zoom, the landscape needs
real interaction. Requires a build step and a charting choice (D3 for
the bespoke V1/V4/V10; Observable Plot or Vega-Lite for the standard
V2/V3/V7/V8/V11).

**Option B — extend the server-rendered site.** Keep `build_index.py`
rendering; add SVG charts to the static HTML output. Lower lift, no
build step, but no interactivity.

**Recommendation:** a hybrid. Keep server-rendered static HTML + a baked
share-image (`today.png`) for the daily hero — that flow is good and
SEO- / share-friendly. Add a client-side "explore" layer for the
interactive charts (V1, V2, V4). The API is already CORS-open,
file-based, and schema'd — a strong base for the client layer once it is
v10-consistent. Phase 1 can proceed server-rendered regardless; the
decision only blocks the interactive views.

---

## 8. What was rejected, and why

This section exists because the two most visually exciting ideas are the
two least defensible — and the reasoning is worth keeping.

### Rejected: the 2D cluster scatter

A scatter of every article positioned by a 2D projection of its
embedding *looks* like the definitive data-journalism chart. It is the
riskiest one in the catalogue:

- Projecting 1024-dim multilingual embeddings to 2D (UMAP / t-SNE / PCA)
  yields **axes with no nameable meaning** — there is no "x is X."
- It **distorts distance**: local neighbourhoods survive badly, global
  distance is meaningless, and two clusters that render adjacent may be
  unrelated.
- It is **not stable day to day**: a re-projection over a new article
  pool relays out the whole map even with a pinned seed, so the reader
  cannot compare today's map to yesterday's.
- Data-journalism readers **over-read spatial position** — proximity
  reads as relatedness whether or not it is.

**Kept instead (V1):** a packed-circle / treemap where size =
`n_articles`, color = `dominant_frame`, and flags = `country_distribution`.
Every channel is a real quantity; there is no axis to over-read. HDBSCAN
already did the honest job — *grouping*. The chart should show the
groups, not a lossy picture of the space they live in.

### Rejected: the re-embedded "word axis"

v1's N3 proposed re-embedding each distinctive term and clustering the
term embeddings into emergent semantic groups, plus a continuous
"framing axis = PC1 of those embeddings."

- `e5` is a **sentence** encoder; isolated words embed poorly.
- The emergent term-clusters have **no stable identity** and need an
  LLM-generated label — cost and drift for no longitudinal payoff.
- "axis = PC1 of term embeddings" is, again, a **manufactured axis** —
  not nameable, not reproducible across days.

**Kept instead (V4 + the §4 join):** group distinctive terms by the
frame the analyst already assigned to the outlet that uses them. The
grouping is emergent per story, citation-grounded, deterministic, and
needs no embedding. The user's "threat camp vs peace camp" is real — it
is the SECURITY_DEFENSE-vs-FAIRNESS/POLICY_PRESCRIPTION frame split the
pipeline already computes, not a new clustering.

### General principle

A visualization is only as defensible as its least nameable axis. The
frame layer gives categorical axes a reader can name; the raw embedding
space does not. Build on the former; use the latter only for the
grouping it already does well.

---

## 9. Phased roadmap

| Phase | Work | Unlocks | Depends on |
|---|---|---|---|
| **0** | v10 migration (§2) + metric corrections (§3): `cross_bucket.py` → outlet-level; re-key 6 schemas; fix `build_index.py` / renderers / pickers; unweighted-share-for-charts; drop PMI from viz; one major meta bump | every chart below renders correct, defensible data | — |
| **1** | Frame color system; V2 framing matrix; V3 frame trajectory; V11 lean grid (single-story); V10 isolation beeswarm | the **framing** story (request #2) — the project's strongest asset | Phase 0 |
| **2** | V5 coverage map (salvage video `WorldMap`); V6 paradox diagram; V7 voice composition; V8 tilt plot; V12 divergence (expose the artifact first) | 4 archetype heroes + the sensationalism view | Phase 0 |
| **3** | N1 `clusters.json`; V1 landscape packed-bubble | the **HDBSCAN intro** map (request #1) | Phase 0 |
| **4** | The words-by-frame join (§4 N3); V4 vocabulary-by-frame | the **word-grouping** viz (request #3) | Phases 0, 1 (needs the LLR re-key + the frame layer) |
| **5** | Cross-corpus aggregator; V11 cross-corpus grid; V13 frame co-occurrence | the longitudinal / "systematic bias" features | Phases 0–1, accumulated `data/analyses/` |

Phase 1 is the fastest win **and** the strongest journalism — it needs
no new artifact, only the migration and real charts on the grade-A
frame layer. The cluster landscape (Phase 3) is deliberately *after* the
framing work: it is the doorway, not the story.

---

## 10. Open questions

1. **Metrics granularity (§2.1).** `cross_bucket.py` moving to
   outlet-level is a major methodology bump that changes every
   isolation / exclusive-vocab number. Confirm before Phase 0.
2. **PMI retention (§3.2).** Drop PMI from the pipeline entirely, or
   keep it computed-but-unvisualized? Keeping it is cheap and preserves
   optionality; dropping it simplifies the methodology pin.
3. **Term → frame fallback (§4 N3).** When a distinctive term is not in
   any evidence quote, fall back to *all* frames its outlet carries, or
   only the outlet's dominant frame? Spot-check in Phase 4.
4. **V12 exposure.** `divergence.py` output is not in the public API
   today — confirm where it lands and add it to the artifact set before
   committing to V12.
5. **Landscape payload (V1).** `clusters.json` with full
   `country_distribution` per cluster is small; confirm it stays under
   ~100 KB/day so the "explore" fetch is cheap.
6. **Frontend architecture (§7).** Deferred — but Phase 1 can proceed
   server-rendered regardless; the decision only blocks V1 / V4.
