# Public API — Epistemic Lens

A daily-updated, file-based JSON API served from GitHub Pages. No auth.
No rate limits beyond GitHub's CDN. Built fresh every morning by the
cron pipeline in this repo.

This document is the **contract** for any frontend / app / scheduler
consuming the data. URL surface and required schema fields are
guaranteed stable; optional fields may be added.

## Base URL

```
https://hwesto.github.io/epistemic-lens/api/
```

> If you're running locally during development,
> `python -m publish.api.build_index` emits the same tree under `./api/`
> for testing without deploying.

## Entry point — `latest.json`

Your frontend should poll this file (≥ 5 min interval recommended; the
cron updates once daily at ~07:30 UTC).

```bash
curl https://hwesto.github.io/epistemic-lens/api/latest.json
```

```json
{
  "date": "2026-05-07",
  "url": "/api/2026-05-07/index.json",
  "n_stories": 4,
  "generated_at": "2026-05-07T07:35:12.123456+00:00"
}
```

If `date` changes, fetch the new `url` to discover that day's stories.

## Per-day index — `<date>/index.json`

```bash
curl https://hwesto.github.io/epistemic-lens/api/2026-05-07/index.json
```

```json
{
  "date": "2026-05-07",
  "generated_at": "2026-05-07T07:35:11.987654+00:00",
  "n_stories": 4,
  "stories": [
    {
      "key": "Le4f8a39c1d",
      "title": "Strait of Hormuz / US-Iran deal",
      "n_outlets": 27,
      "n_countries": 14,
      "n_articles": 41,
      "has": {
        "briefing": true,
        "metrics":  true,
        "analysis": true,
        "thread":   true,
        "carousel": true,
        "long":     true
      },
      "artifacts": {
        "briefing": "/api/2026-05-07/Le4f8a39c1d/briefing.json",
        "metrics":  "/api/2026-05-07/Le4f8a39c1d/metrics.json",
        "analysis": "/api/2026-05-07/Le4f8a39c1d/analysis.md",
        "thread":   "/api/2026-05-07/Le4f8a39c1d/thread.json",
        "carousel": "/api/2026-05-07/Le4f8a39c1d/carousel.json",
        "long":     "/api/2026-05-07/Le4f8a39c1d/long.json"
      },
      "top_isolation_outlet": "Iran International",
      "paradox": true
    }
  ]
}
```

`key` is the cluster's `lineage_id` — a stable hash that persists for
as long as the story keeps re-clustering across days. `title` is the
`cluster_name` Claude wrote during the analysis pass.

`has.<format>` tells you whether that artifact is present. Drafts may
be missing if the analyze or draft job failed; the index still ships.

## Per-story artifacts

For each story, keyed by its `lineage_id`, six files (some optional):

| Path                                  | Type             | Schema                          |
|---------------------------------------|------------------|---------------------------------|
| `<lineage_id>/briefing.json`          | application/json | `/api/schema/briefing.schema.json` |
| `<lineage_id>/metrics.json`           | application/json | `/api/schema/metrics.schema.json`  |
| `<lineage_id>/analysis.json`          | application/json | `/api/schema/analysis.schema.json` |
| `<lineage_id>/analysis.md`            | text/markdown    | rendered from analysis.json     |
| `<lineage_id>/thread.json`            | application/json | `/api/schema/thread.schema.json`   |
| `<lineage_id>/carousel.json`          | application/json | `/api/schema/carousel.schema.json` |
| `<lineage_id>/long.json`              | application/json | `/api/schema/long.schema.json`     |

## Schemas — `/api/schema/`

JSON Schema 2020-12. Validate at parse time in your frontend if you want
strong typing.

```bash
curl https://hwesto.github.io/epistemic-lens/api/schema/briefing.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/analysis.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/metrics.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/thread.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/carousel.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/long.schema.json
```

**Briefing schema (v10).** A briefing is one HDBSCAN cluster's corpus.
Top-level: `lineage_id`, `cluster_id`, `n_outlets`, `n_countries`,
`salience_score`, `top_tokens`. Each `corpus[]` entry carries `outlet`
plus `country`, `lang`, `lean`, and `section` tags — so a consumer can
group the same corpus by outlet, country, language, or political lean
without re-fetching anything.

**Analysis schema (v10).** Required: `lineage_id`, `cluster_id`,
`cluster_name` (Claude's name for the story), `n_outlets`,
`n_countries`. Each `frames[]` entry lists the `outlets` and
`countries` that carried that frame.

Quick shapes:

- **thread**: `{lineage_id, date, hook, tweets[{text, sources[{outlet,url}]}], closing_cta?}`
- **carousel**: `{lineage_id, date, title, subtitle?, slides[{title, body, source?}], closing}`
- **long**: `{lineage_id, date, title, body_md (markdown), sources[{outlet,url}]}`

Every factual claim cites at least one source. The `url` is the article
link from the briefing corpus — not a homepage, not a search result.

## CORS

GH Pages serves all paths with `Access-Control-Allow-Origin: *`. Your
frontend can fetch directly from the browser without a proxy.

## Polling cadence

The cron runs once daily at 07:00 UTC. Pipeline finishes by ~07:35 UTC
on a normal day. Recommended polling:

| Interval | Use case                                |
|----------|-----------------------------------------|
| 5 min    | Active dashboard during morning window  |
| 1 hour   | Background sync                         |
| webhook  | Not yet built — file an issue if needed |

## Retention

All dates are kept indefinitely. URL paths are stable. A story's
`lineage_id` persists across days for as long as the cluster keeps
re-surfacing; a story that stops being covered and later returns may
get a fresh `lineage_id`.

## Versioning

This is a prototype: the v10 rebuild changed the URL surface
(`<story_key>` → `<lineage_id>`) and several schema shapes, and no
API-stability promise is made yet. Optional fields
(`top_isolation_outlet`, `paradox`, `tags`, etc.) and metric internals
may evolve without notice. Each artifact carries a `meta_version` field
so consumers can detect the era they're reading.

## Reading the source repo directly

If you want to consume artifacts without GH Pages — for example
during local dev or for an offline pipeline — they live at canonical
paths in this repo:

```
data/briefings/<DATE>_<lineage_id>.json
data/briefings/<DATE>_<lineage_id>_metrics.json
data/analyses/<DATE>_<lineage_id>.md
data/drafts/<DATE>_<lineage_id>_{thread,carousel,long}.json
```

`raw.githubusercontent.com` works but is rate-limited per IP and lacks
CORS in some cases. Prefer the Pages URL for production.
