# Visualization Plan — Epistemic Lens frontend

A design spec for a data-journalism frontend: a set of recurring,
data-driven visualizations that a daily editorial piece can be built
around. This document is **plan only** — no code is changed by it.

It answers three questions:

1. How good are the current pipeline / API outputs for visualization?
2. What has to change before reliable visualizations can be built?
3. What is the full catalogue of visualizations worth building, and
   what data each one needs?

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
`publish/video/` pipeline does contain a real `react-simple-maps`
`WorldMap` + `CountryPin` — useful proof that the data can drive a map,
and a component worth salvaging.

### Output grading

| Artifact | In public API? | Keyed v10? | Viz-readiness |
|---|---|---|---|
| `analysis.json` — frames, evidence, paradox, silences, isolation, exclusive vocab | yes | **yes** | A — best-supported, fully v10 |
| `briefing.json` — per-article corpus w/ outlet/country/lang/lean tags | yes | **yes** | A — clean raw material |
| `metrics.json` — pairwise similarity, isolation, weighted frame distribution + bootstrap CIs | yes | **no** | C — v9-keyed; see §2 |
| `trajectory.json` — frame share over time + drivers | yes | **no** | C — v9 `story_key`-keyed |
| `tilt.json` — bigram log-odds vs wire baseline | yes | **no** | C — v9-keyed |
| `within_lang_llr` / `within_lang_pmi` — distinctive terms / bigrams | yes (per story) | **no** | C — v9-keyed |
| `sources.json` — per-quote speaker attribution | yes | **no** | C — v9-keyed |
| `coverage.json` — per-(story,feed) coverage + silence states | yes | **no** | C — v9-keyed |
| `<date>_clusters.json` + `<date>_top_clusters.json` — the full HDBSCAN landscape | **no** | yes | not exposed — see §3 |
| 2D embedding projection | **does not exist** | — | missing — see §3 |
| semantic grouping of distinctive words | **does not exist** | — | missing — see §3 |

The `analyze` + `briefing` layer is genuinely v10 and genuinely good.
Everything downstream of it is not.

---

## 2. Prerequisite: the v9 → v10 migration

The docs (METHODOLOGY / ARCHITECTURE / API / README) describe **v10** —
outlets as the atomic unit, `lineage_id`, emergent HDBSCAN clusters. The
ingest → cluster → briefing → analyze layer is v10. The downstream layer
was never migrated, and this **blocks any reliable frontend**:

| Component | Problem |
|---|---|
| `core/metrics/cross_bucket.py` | Groups by `country` (`art.get("country") or art.get("bucket")`). Emits `n_buckets`, `isolation[].bucket`, `bucket_exclusive_vocab` — never per-outlet, despite the v10 promise that the outlet is the atomic unit. |
| `publish/api/build_index.py` | Reads `e.get("bucket")` on the corpus. v10 corpus entries have `country`, not `bucket`. Result: `n_buckets` computes as `1`, `top_isolation` breaks, tilt-file matching breaks. |
| `metrics.schema.json` | `required` lists `pairwise_jaccard`; the producer emits `pairwise_similarity`. The schema does not match its own output. |
| `index.schema.json` | Requires `n_buckets` / `top_isolation_bucket`; API.md documents `n_outlets` / `n_countries` / `top_isolation_outlet`. |
| `coverage` / `trajectory` / `sources` / `tilt` / `word` schemas | All keyed on `story_key` + `bucket`. |

**Migration scope (Phase 0 below):**

1. `cross_bucket.py` → compute at **outlet** granularity (the v10
   promise). Frontend aggregates outlet → country for map views. This is
   a methodology change → **major meta-version bump**, with a `--reason`.
2. Re-key 6 schemas: `story_key` → `lineage_id`, `bucket` → `outlet`
   (or `country` where geography is the intent). Fix
   `pairwise_jaccard` → `pairwise_similarity` in `metrics.schema.json`.
3. `build_index.py` and `page_renderers.py` / `card_renderers.py` read
   `outlet` / `country`, never `bucket`.
4. `index.json`: `n_buckets` → `n_outlets` + `n_countries`;
   `top_isolation_bucket` → `top_isolation_outlet`.

Until this lands, every chart is sitting on a unit (the country bucket)
the methodology says was abandoned, and the unit v10 promises (the
outlet) is invisible.

---

## 3. New pipeline outputs needed

Three visualizations in the catalogue (§5) cannot be built from current
data. Each needs one new artifact.

### N1 — `clusters.json` (the daily landscape)

A published, lightweight form of `data/snapshots/<date>_clusters.json`.
Today the API ships only the top ~15 briefed stories; the 50–200-cluster
landscape — "everything the world talked about today" — is invisible.

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
      "dominant_frame": "SECURITY_DEFENSE", // top-15 only (from analysis)
      "centroid_xy": [0.42, -1.13]          // from N2
    }
  ]
}
```

Cost: a copy + projection-join in `build_index.py`. Cheap.

### N2 — 2D embedding projection

A new `core/cluster/project.py` runs after `core/embed/encode.py`,
projecting the day's 1024-dim `<date>_embeddings.npy` to 2D and emitting
`<date>_projection.json` — `{article_id: [x, y]}` plus per-cluster
centroids. Without it there are no coordinates for a true scatter.

Open question — projector choice:

- **PCA** — in `scikit-learn` already, deterministic, fast, but flattens
  structure (clusters overlap visually).
- **UMAP** — much better separation, but a new dependency and
  stochastic; needs a fixed seed to satisfy the methodology pin.

Recommendation: UMAP with a pinned seed, falling back to PCA. The
projector parameters get hashed into the methodology pin like any other
analytical input.

### N3 — vocabulary map (powers the word-grouping viz)

The project surfaces distinctive *words* (LLR, PMI, tilt, exclusive
vocab) but never **groups or positions them semantically**. A new step
(`core/metrics/vocab_map.py`, run in the metrics stage) for each story:

1. Collect the distinctive terms across all outlets (from the LLR and
   exclusive-vocab layers).
2. Embed each term with the multilingual model already loaded — either
   the bare term, or the term averaged over the sentences it appears in
   (context helps; see open question).
3. Cluster the term embeddings (HDBSCAN, or k-means with small k) into
   **emergent** semantic groups — not a hard-coded list.
4. Emit `<date>_<lineage_id>_vocab_map.json`:

```json
{
  "meta_version": "...", "lineage_id": "Le4f8a39c1d",
  "groups": [
    {
      "group_id": 0, "label": "threat / conflict",   // optional, LLM or centroid token
      "terms": [
        {"term": "guerra", "lang": "it", "outlets": ["ANSA"],
         "countries": ["italy"], "distinctiveness": 31.2, "axis": -0.81}
      ]
    },
    {
      "group_id": 1, "label": "agreement / de-escalation",
      "terms": [{"term": "accord", "lang": "fr", "outlets": ["Le Monde"],
                 "countries": ["france"], "distinctiveness": 24.0, "axis": 0.73}]
    }
  ],
  "axis": {"definition": "first principal component of term embeddings",
           "neg_pole_terms": ["guerra", "threat"],
           "pos_pole_terms": ["accord", "peace"]}
}
```

This is exactly the request: "terrorist / threat in one group, freedom /
peace-deal in another — not hard-set." Both an emergent `group_id` and a
continuous `axis` position are emitted, so the viz can render either
grouped columns or a single-axis beeswarm.

Open question — embedding bare terms: the `e5` model is a sentence
encoder; isolated words embed adequately but lose context. Embedding
each term as the mean of its in-corpus sentences is more faithful but
heavier. Decide during Phase 4 with a small spot-check.

---

## 4. Cross-cutting design decisions

### Frame color system

All 15 Boydstun/Card frames get a **fixed palette**, defined once and
reused everywhere — cluster map dots, frame matrix, frame trajectory.
Consistent color = the reader learns "blue means ECONOMIC" once and
carries it across every chart. This belongs in a shared
`publish/api/site_config.py` constant.

### Country flags

A `country_code → flag emoji` map already exists as `BUCKET_FLAGS` in
`card_renderers.py`. It is keyed by country code, so it survives the v10
migration unchanged — just conceptually renamed.

### Mobile-first

The audience reads on phones (the existing card is phone-shaped, and the
share/download-image flow is phone-shaped). Every visualization needs a
legible small-screen form — usually a simplified or vertically-stacked
variant, not the desktop chart shrunk.

### One striking thing per day

The editorial model is already "one striking comparison per day" with a
7-archetype picker (`word`, `paradox`, `silence`, `shift`, `sources`,
`tilt`, `echo`). The catalogue below assigns **one signature
visualization per archetype**, so the daily picker also picks the day's
hero chart. The cluster landscape (V1) sits outside the rotation as a
permanent "explore today" entry point.

---

## 5. The visualization catalogue

Each entry: what it shows, the data it needs, the journalism angle, and
the build status (✅ data ready post-Phase-0 · ⚠️ needs a new artifact).

### V1 — Today's story landscape  ·  ⚠️ needs N1 + N2

The day's HDBSCAN output as a **cluster map**: a 2D scatter of every
clustered article, points colored by cluster, the top-15 clusters drawn
as labelled bubbles (radius = `n_articles`, fill = `dominant_frame`),
country flags arranged around each bubble from `country_distribution`.
The long-tail clusters render as faint grey points — "the conversations
that did not cross borders."

- Data: `clusters.json` (N1) + `projection.json` (N2).
- Angle: *"Today the world's press split into 87 conversations. These 15
  crossed borders — here is the map."* This is the HDBSCAN intro piece.
- Note: only the top-15 carry a `dominant_frame` (the long tail is never
  analyzed); color the tail by dominant language instead.

### V2 — Cross-country framing matrix  ·  ✅

For one story: a heatmap, frame_id (rows) × outlet/country (columns),
cell shaded where that outlet carried the frame, the verbatim evidence
quote on hover/tap. An upgrade of today's HTML-table `render_frames_matrix`.

- Data: `analysis.frames[]` (`outlets`, `countries`, `evidence`).
- Angle: *"Everyone agreed it happened. Here is where they disagreed
  about what it meant."* — the signature **framing** viz, your "eco etc."

### V3 — Frame share over time (the Shift)  ·  ✅ (after trajectory re-key)

A multi-line or streamgraph chart of each frame's share of coverage, day
by day, for a persistent story. Inflection points annotated with the
`drivers` (the specific article URLs that moved the share).

- Data: `trajectory.json` (`frame_trajectories`, `drivers`).
- Archetype: **shift**.
- Angle: *"How the hantavirus story turned from health to economics in
  72 hours."*

### V4 — Vocabulary map (the word groups)  ·  ⚠️ needs N3

The distinctive words for a story, laid out semantically. Two renders
off the same `vocab_map.json`:

- **Grouped columns** — one column per emergent `group`, terms stacked,
  sized by `distinctiveness`, each tagged with the flags/outlets that
  use it.
- **Framing axis** — a beeswarm on the continuous `axis`: threat/conflict
  vocabulary on one pole, agreement/de-escalation on the other.

- Data: `vocab_map.json` (N3).
- Archetype: **word**.
- Angle: *"Six outlets, six words for the same ceasefire — and they fall
  into two camps."* This is request #3, with emergent (not hard-set) groups.

### V5 — Country coverage map (the Silence)  ·  ✅

A world choropleth: each country shaded by how it covered a story
(fill = dominant frame), **hollow** where it carried items but stayed
silent on this story, struck-through where every feed failed
(structural, not editorial). Salvage the `publish/video/` `WorldMap`
component.

- Data: `briefing.countries_present`, `analysis.silences`,
  `analysis.coverage_caveats`, `coverage.non_coverage`.
- Archetype: **silence**.
- Angle: *"14 countries covered the Hormuz deal. Egypt ran Sisi instead."*

### V6 — Paradox convergence diagram  ·  ✅

Two ideologically-opposed outlets as nodes on opposite sides, both arrows
landing on one shared `joint_conclusion` in the middle; each side shows
its verbatim quote and country flag.

- Data: `analysis.paradox` (`a`, `b`, `joint_conclusion`).
- Archetype: **paradox**.
- Angle: *"Iran's state press and its exiled opposition agreed on one
  thing today."*

### V7 — Whose voices (source composition)  ·  ✅ (after sources re-key)

A stacked bar per outlet (or per country) of `speaker_affiliation_bucket`
— state / political / civilian / expert / wire / corporate / academic /
NGO. Shows whose voices a story platformed and whose it omitted.

- Data: `sources.json` (`speaker_affiliation_bucket`, `stance_toward_target`).
- Archetype: **sources**.
- Angle: *"Vietnam's state media quoted 7 officials and zero civilians."*

### V8 — Tilt vs the wire baseline  ·  ✅ (after tilt re-key)

A diverging dot plot: per outlet, the bigrams whose log-odds depart most
from the Reuters/AFP/AP wire baseline, positive tilt right, negative
left, dot size = `z_score`.

- Data: `tilt.json` (`anchors.wire.positive_tilt` / `negative_tilt`).
- Archetype: **tilt**.
- Angle: *"How far each outlet's language drifts from the wire copy
  everyone started from."*

### V9 — Echo / lag timeline  ·  ✅ (after lag re-key)

A small timeline showing a story propagating across a curated outlet
chain (wire → flagship → follower), with the cross-correlation lag in
days drawn as the offset.

- Data: `lag.json` (CCF output from `core/compare/lag.py`).
- Archetype: **echo** (Monday weekly only).
- Angle: *"The Times of London ran the NYT framing 48 hours later."*

### V10 — Isolation / outlier beeswarm  ·  ✅

A beeswarm of every outlet in a story by `mean_similarity` to the
cluster consensus; the outlier sits visibly alone at the low end. A
proper-chart upgrade of today's CSS `render_isolation_panel`.

- Data: `metrics.isolation` / `analysis.outlet_isolation_top`.
- Supporting viz (not a hero archetype).

### Archetype → hero visualization

| Archetype | Hero viz |
|---|---|
| word | V4 vocabulary map |
| paradox | V6 convergence diagram |
| silence | V5 coverage map |
| shift | V3 frame trajectory |
| sources | V7 voice composition |
| tilt | V8 tilt dot plot |
| echo | V9 lag timeline |
| (landscape) | V1 cluster map — always-on "explore today" |

---

## 6. Frontend architecture (decision deferred)

Two viable paths; the choice is deferred but the trade-off is recorded
here.

**Option A — client-side data app.** A small JS app fetching the JSON
API (`latest.json` → `index.json` → artifacts) and rendering interactive
charts. Best fit for data journalism: hover, zoom, the cluster map needs
real interaction. Requires a build step and a charting choice (D3 for
the bespoke charts V1/V4/V10; Observable Plot or Vega-Lite for the
standard charts V2/V3/V7/V8).

**Option B — extend the server-rendered site.** Keep `build_index.py`
rendering; add SVG charts to the static HTML output. Lower lift, no
build step, but no interactivity — V1's cluster map and V4's beeswarm
lose most of their value.

**Recommendation:** a hybrid. Keep server-rendered static HTML + a baked
share-image (`today.png`) for the daily hero — that flow is good and SEO-
and share-friendly. Add a client-side "explore" layer for the interactive
charts (V1, V2, V4). The API is already CORS-open, file-based, and
schema'd — a strong base for the client layer once it is v10-consistent.

---

## 7. Phased roadmap

| Phase | Work | Unlocks | Depends on |
|---|---|---|---|
| **0** | v10 migration: `cross_bucket.py` → outlet-level; re-key 6 schemas; fix `build_index.py` / renderers; major meta bump | every chart below renders correct data | — |
| **1** | Frame color system; V2 framing matrix; V3 frame trajectory; V10 isolation beeswarm | the **framing** story (request #2) | Phase 0 |
| **2** | V5 coverage map (salvage video `WorldMap`); V6 paradox diagram; V7 voice composition; V8 tilt plot | 4 more archetype heroes | Phase 0 |
| **3** | N1 `clusters.json` + N2 projection artifact; V1 cluster landscape | the **HDBSCAN intro** map (request #1) | Phase 0 |
| **4** | N3 vocabulary-map step; V4 vocabulary map | the **word-grouping** viz (request #3) | Phases 0, 3 (shares the embedding/cluster machinery) |

Phase 1 is the fastest win — it needs no new artifact, only the
migration and a real chart. Phase 4 is the most novel and most
distinctive piece of journalism, and the heaviest lift.

---

## 8. Open questions

1. **Metrics granularity.** §2 recommends `cross_bucket.py` move to
   outlet-level. Confirm — the v10 docs promise it, but it is a major
   methodology bump and changes every isolation/exclusive-vocab number.
2. **Projector choice (N2).** UMAP (better, stochastic, new dependency)
   vs PCA (deterministic, in-tree, flatter). Pin a seed either way.
3. **Term embedding (N3).** Bare term vs term-in-context. Spot-check in
   Phase 4.
4. **Group labelling (N3).** Emergent groups need a human-readable label
   — centroid's nearest token (cheap, deterministic) or a one-shot LLM
   label (nicer, costs a call).
5. **Landscape payload size.** A per-article projection for V1 could be
   1–2k points/day. Cluster-centroid-only keeps `clusters.json` tiny;
   the full article scatter is a heavier optional fetch.
6. **Frontend architecture (§6)** — deferred, but Phase 1 can proceed
   server-rendered regardless; the decision only blocks V1/V4.
