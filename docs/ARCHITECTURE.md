# Architecture — Epistemic Lens (v10)

## System overview

v10 replaces v9's closed-world story matching (a fixed
`canonical_stories.json` + softmax-argmax matcher) with **open-world
dynamic clustering**: every article in the day's set is embedded and
clustered, salience ranking picks the top ~15, and each top cluster
becomes a briefing. There is no pre-defined story list.

```
              ┌──────────────────────────────────────────┐
              │  core/config/feeds.json (235 feeds, 55)  │
              └────────────────────┬─────────────────────┘
                                   │
          ┌────────────────────────▼────────────────────────────┐
          │  INGEST  (core/ingest/)                              │
          │                                                      │
          │  pull_feeds      → data/snapshots/<date>.json        │
          │   • parallel fetch (ThreadPool, 30 workers)          │
          │   • per-host rate limit + retries                    │
          │   • RSS / Atom / RDF parser                          │
          │  extract_bodies  → annotates snapshot in place       │
          │   • trafilatura body extraction                      │
          │   • Wayback + Common Crawl News fallbacks            │
          │   • signal_text(): body | summary | title            │
          │  dedup           → _dedup.json + annotations         │
          │   • URL canonicalisation, title near-dup collapse    │
          │  coverage_matrix → data/coverage/<date>.json         │
          │  health          → <date>_health.json + alerts       │
          └────────────────────────┬─────────────────────────────┘
                                   │
          ┌────────────────────────▼─────────────────────────────┐
          │  EMBED + CLUSTER                                      │
          │                                                       │
          │  core/embed/encode    → <date>_embeddings.npy        │
          │   • multilingual-e5-large, unit-normed vectors        │
          │   • versioned article_id keys the cache               │
          │  core/cluster/cluster_daily → <date>_clusters.json   │
          │   • HDBSCAN over EVERY article (~50-200 clusters)    │
          │   • member IDs + country/outlet/lang distributions    │
          │  core/cluster/salience → <date>_top_clusters.json    │
          │   • score = n_articles × country_spread ×            │
          │     multilingual_bonus × stability; keep top ~15      │
          │  core/cluster/lineage (weekly) → archive/            │
          │     persistent_lineages_<date>.json                  │
          │   • cross-day member-ID Jaccard ≥ 0.30 → lineage_id  │
          └────────────────────────┬─────────────────────────────┘
                                   │
          ┌────────────────────────▼─────────────────────────────┐
          │  core/briefing/build                                  │
          │   • one corpus per top cluster                        │
          │   • up to 2 articles per OUTLET (novelty filter)     │
          │   • each entry tagged outlet/country/lang/lean        │
          │   • filename keyed by stable lineage_id               │
          └────────────────────────┬─────────────────────────────┘
                                   │
                  data/briefings/<date>_<lineage_id>.json
                                   │
          ┌────────────────────────▼─────────────────────────────┐
          │  core/metrics/cross_bucket                            │
          │   • pairwise LaBSE cosine on per-outlet means         │
          │   • outlet isolation (mean cosine vs others)          │
          │   • outlet-exclusive vocab (df==1, count>=3)          │
          │   • within-language LLR + PMI siblings                │
          │   • → <date>_<lineage_id>_metrics.json                │
          └────────────────────────┬─────────────────────────────┘
                                   │
          ┌────────────────────────▼─────────────────────────────┐
          │  ANALYZE  (per-cluster matrix)                        │
          │                                                       │
          │  analyze_bootstrap → core/briefing/qualifying         │
          │    emits JSON array of lineage_ids with               │
          │    n_outlets ≥ 3 → matrix axis for the LLM jobs       │
          │                                                       │
          │  analyze_body / analyze_headline / analyze_sources    │
          │    each: matrix per lineage_id (fail-fast: false)     │
          │    each entry: one Sonnet session, one briefing       │
          │    prompts under core/analyze/prompts/                │
          │    prompts accept a "# Assigned cluster:" header so   │
          │    the workflow scopes each call to one cluster       │
          │                                                       │
          │  analyze_render: restamp → validate → divergence →    │
          │    source_aggregation → render MD → longitudinal →    │
          │    robustness → commit                                │
          └────────────────────────┬─────────────────────────────┘
                                   │
              data/analyses/<date>_<lineage_id>.{json,md}
                                   │
          ┌────────────────────────▼─────────────────────────────┐
          │  DRAFT + PUBLISH  (publish/)                          │
          │   • publish/render/{thread,carousel}.py — templates   │
          │   • publish/render/prompts/draft_long.md — Sonnet     │
          │   • publish/api/build_index.py → api/ tree → Pages    │
          │   • publish/distribute/stage.py → pending queue       │
          └────────────────────────┬─────────────────────────────┘
                                   │
                       hwesto.github.io/epistemic-lens/
                                   │
              ├── /                          → landing page
              ├── /<DATE>/index.json
              ├── /<DATE>/<lineage_id>/{briefing,metrics,analysis}.{json,md}
              ├── /<DATE>/<lineage_id>/{thread,carousel,long}.json
              ├── /latest.json
              └── /schema/*.schema.json

      [Dormant: the video pipeline under publish/video/ is kept in
       the repo but not invoked by any cron. Reactivate when the
       public surface needs short-form video.]
```

## Repo layers

| Layer | Path | Role |
|---|---|---|
| Research product | `core/` | ingest → embed → cluster → briefing → metrics → analyze |
| Content product | `publish/` | render, api tree, distribution, web, video (dormant) |
| Runtime data | `data/` | snapshots, briefings, analyses, archive — mostly gitignored |
| Config | `core/config/` | feeds, outlets, weights, codebook, `meta_version.json` |

`core/` produces the data; `publish/` consumes it. The two are kept
visibly separate so the research pipeline has no dependency on the
content layer.

## Data layer details

**Snapshot file** (`data/snapshots/<date>.json`) — country-nested raw
ingest. `countries` is an organisational container; the atomic unit is
the outlet (a feed within a country).

```json
{
  "date": "2026-05-20",
  "countries": {
    "usa": {
      "label": "United States",
      "feeds": [
        {
          "name": "CNN World", "lang": "en", "lean": "Centre-liberal",
          "item_count": 50,
          "items": [
            {
              "title": "...", "link": "https://...", "summary": "...",
              "published": "Tue, 20 May 2026 06:00:00 +0000",
              "id": "abc123ef",
              "body_text": "...", "body_chars": 4200,
              "extraction_status": "FULL", "extraction_via_wayback": false,
              "canonical_url": "https://...", "normalised_title": "..."
            }
          ]
        }
      ]
    }
  }
}
```

**Clusters file** (`data/snapshots/<date>_clusters.json`) — HDBSCAN
output over the whole day. Each cluster:

```json
{
  "cluster_id": 7,
  "n_articles": 38, "n_countries": 14, "n_outlets": 22, "n_langs": 5,
  "member_article_ids": ["a1b2c3...", "..."],
  "country_distribution": {"usa": 6, "iran": 4, "...": 0},
  "outlet_distribution":  {"BBC News": 3, "...": 0},
  "lang_distribution":    {"en": 20, "fa": 7, "...": 0},
  "top_tokens": ["hormuz", "strait", "tanker"],
  "stability": 0.71
}
```

`<date>_top_clusters.json` is the salience-ranked top ~15 of the same
shape, each with an added `salience_score`.

**Briefing file** (`data/briefings/<date>_<lineage_id>.json`):

```json
{
  "date": "2026-05-20",
  "lineage_id": "Le4f8a39c1d",
  "cluster_id": 7,
  "cluster_name": null,
  "salience_score": 28.4,
  "top_tokens": ["hormuz", "strait", "tanker"],
  "n_outlets": 22, "n_countries": 14, "n_langs": 5,
  "n_articles_total": 38,
  "countries_present": ["iran", "usa", "..."],
  "corpus": [
    {
      "outlet": "Fox News World",
      "country": "usa", "country_label": "United States",
      "lang": "en", "lean": "Centre-right", "section": "news",
      "title": "...", "link": "https://...",
      "signal_level": "body",
      "signal_text": "first 2500 chars of body or summary",
      "extraction_status": "FULL", "via_wayback": false
    }
  ],
  "coverage_caveats": []
}
```

`cluster_name` is written later by Claude's analysis pass — the briefing
ships with it `null`.

## Component reference

### Pipeline scripts

| Module | Reads | Writes |
|---|---|---|
| `core.ingest.pull_feeds` | `core/config/feeds.json` | `<date>.json` + `_pull_report.md` |
| `core.ingest.extract_bodies` | snapshot | annotates snapshot in place |
| `core.ingest.dedup` | snapshot | `_dedup.json` + annotations |
| `core.ingest.coverage_matrix` | snapshot | `data/coverage/<date>.json` |
| `core.ingest.health` | snapshot + last 7 days | `<date>_health.json` |
| `core.embed.encode` | snapshot | `<date>_embeddings.npy` + `_embedding_ids.json` (.npy gitignored; CI regenerates each cron) |
| `core.cluster.cluster_daily` | embedding cache + snapshot | `<date>_clusters.json` (HDBSCAN over every article) |
| `core.cluster.salience` | `<date>_clusters.json` | `<date>_top_clusters.json` (top ~15) |
| `core.cluster.lineage` | last 7 days `<date>_clusters.json` (weekly) | `data/archive/persistent_lineages_<date>.json` |
| `core.briefing.build` | snapshot + `<date>_top_clusters.json` | `data/briefings/<date>_<lineage_id>.json` |
| `core.briefing.qualifying` | `data/briefings/*` | JSON array of lineage_ids to stdout (analyze-matrix bootstrap) |
| `core.metrics.cross_bucket` | briefing | `<date>_<lineage_id>_metrics.json` |
| `core.analyze.validate` | analysis + briefing + metrics | exits non-zero on schema / citation / number violation |
| `core.ingest.feed_rot_check` | last 7 `_health.json` (weekly) | `archive/review/rot_report_<date>.md` |
| `core.ingest.rollup` | snapshots + briefings ≥90d old (weekly) | `archive/rollup/<group>-YYYY-MM.tar.gz`; idempotent |

### Validation (defence in depth)

`core/analyze/validate.py` runs after the LLM matrix:

- **schema check** — `jsonschema` against `analysis.schema.json`
- **citation grounding** — every `signal_text_idx` resolves; quote is a
  verbatim substring of `corpus[idx].signal_text`; the claimed `outlet`
  matches `corpus[idx].outlet` (auto-filled from the corpus when blank)
- **number reconciliation** — `n_outlets` / `n_countries` match the
  metrics file; exclusive-vocab terms are present in metrics
- exits non-zero on any violation, failing the render job loudly

## Status flags in feeds.json

| Flag | Meaning |
|---|---|
| `OK` | Feed live, returns parseable items with real summaries |
| `STUB` | Title-only feed. Useful for headline tracking, weak for embedding nuance |
| `RETRY` | 403/429 from the probe container; expected to work from the production IP |
| `OK + extraction via Wayback` | Live feed, article body retrieved via web.archive.org because the host blocks |

## Pipeline cadence

| Cadence | Job | Action |
|---|---|---|
| Daily 07:00 UTC | `daily.yml` | ingest → extract → dedup → coverage → health → embed → cluster_daily → salience → build → metrics → analyze_bootstrap → analyze_body/headline/sources (matrix) → analyze_render → draft → publish_api → distribute |
| Mondays 09:00 UTC | `weekly.yml` | cross_outlet_lag (CCF) + wire_baseline + tilt_index + rollup + lineage → commit |
| Sundays 09:00 UTC | `weekly_rot.yml` | feed rot check → commit `archive/review/rot_report_<date>.md` |
| Push / PR to main / claude-* | `meta-check.yml` | `baseline_pin.py --check` (pin drift) + offline unit suite (`tests.tests` + `tests.tests_edge`) |
