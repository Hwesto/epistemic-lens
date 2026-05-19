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

> If you're running locally during development, `python build_index.py`
> emits the same tree under `./api/` for testing without deploying.

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
      "key": "hormuz_iran",
      "title": "Hormuz / US-Iran Deal",
      "n_buckets": 27,
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
        "briefing": "/api/2026-05-07/hormuz_iran/briefing.json",
        "metrics":  "/api/2026-05-07/hormuz_iran/metrics.json",
        "analysis": "/api/2026-05-07/hormuz_iran/analysis.md",
        "thread":   "/api/2026-05-07/hormuz_iran/thread.json",
        "carousel": "/api/2026-05-07/hormuz_iran/carousel.json",
        "long":     "/api/2026-05-07/hormuz_iran/long.json"
      },
      "top_isolation_bucket": "iran_opposition",
      "paradox": true
    }
  ]
}
```

`has.<format>` tells you whether that artifact is present. Drafts may
be missing if the analyze or draft job failed; the index still ships.

## Per-story artifacts

For each story, six files (some optional):

| Path                                  | Type             | Schema                          |
|---------------------------------------|------------------|---------------------------------|
| `<story>/briefing.json`               | application/json | `/api/schema/briefing.schema.json` |
| `<story>/metrics.json`                | application/json | `/api/schema/metrics.schema.json`  |
| `<story>/analysis.json`               | application/json | `/api/schema/analysis.schema.json` |
| `<story>/analysis.md`                 | text/markdown    | rendered from analysis.json     |
| `<story>/thread.json`                 | application/json | `/api/schema/thread.schema.json`   |
| `<story>/carousel.json`               | application/json | `/api/schema/carousel.schema.json` |
| `<story>/long.json`                   | application/json | `/api/schema/long.schema.json`     |

## Per-day discovery output (v9.2.0+)

| Path                                                  | Type             | Schema                                           |
|-------------------------------------------------------|------------------|--------------------------------------------------|
| `<date>/residual_clusters.json`                       | application/json | `/api/schema/residual_clusters.schema.json`      |
| weekly `archive/persistent_residual_<date>.json`      | application/json | `/api/schema/persistent_residual.schema.json`    |

These surface emerging stories the canonical-set doesn't cover yet:
articles the perception layer didn't assign get HDBSCAN-clustered daily,
linked across days by member-article-ID Jaccard ≥ 0.30, and reviewed
weekly. Lineages with day_count ≥ 3 AND n_buckets_union ≥ 4 land in
`archive/auto_promoted_<date>.md` as promotion candidates.

## Schemas — `/api/schema/`

JSON Schema 2020-12. Validate at parse time in your frontend if you want
strong typing.

```bash
curl https://hwesto.github.io/epistemic-lens/api/schema/briefing.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/analysis.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/canonical_stories.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/residual_clusters.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/persistent_residual.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/thread.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/carousel.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/long.schema.json
```

**Briefing schema additions (meta-v9.0.0):** `corpus[].match_cosine` and
`corpus[].match_softmax` — the matcher's confidence stamp from the
embedding softmax-argmax assignment. `match_cosine` is the raw cosine
against the assigned story's anchor centroid; `match_softmax` is the
softmax-normalised score across the full canonical set. Both optional;
absent on pre-9.0 briefings.

**Canonical stories schema additions (meta-v9.0.0):** each story carries
`embedding_anchors` (3-8 sentence anchor list, including native-script
multilingual variants where applicable), `assignment_floor` (per-story
override of `meta.PERCEPTION.assignment_floor_default`), and `tier`
(`long_running` | `dated`). The legacy `patterns` + `exclude` regex
fields are retained but no longer drive briefing assignment — only the
emerging-story token detector reads them.

Quick shapes:

- **thread**: `{story_key, date, hook, tweets[{text, sources[{bucket,url}]}], closing_cta?}`
- **carousel**: `{story_key, date, title, subtitle?, slides[{title, body, source?}], closing}`
- **long**: `{story_key, date, title, body_md (markdown), sources[{bucket,url}]}`

Every factual claim cites at least one source. The `bucket` value is a
stable key from `feeds.json` (e.g. `usa`, `iran_opposition`, `russia`).
The `url` is the article link from the briefing's source field — not a
homepage, not a search result.

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

All dates are kept indefinitely. URL paths are stable. If a story is
later renamed (rare), the old key remains a 404 and the new key
appears in fresh indexes.

## Versioning

The URL surface, `latest.json` shape, and required schema fields are
contracted — breaking changes will ship under `/api/v2/`. Optional
fields (`top_isolation_bucket`, `paradox`, `tags`, etc.) and metric
internals may evolve without notice.

## Reading the source repo directly

If you want to consume artifacts without GH Pages — for example
during local dev or for an offline pipeline — they live at canonical
paths in this repo:

```
briefings/<DATE>_<story>.json
briefings/<DATE>_<story>_metrics.json
analyses/<DATE>_<story>.md
drafts/<DATE>_<story>_{thread,carousel,long}.json
```

`raw.githubusercontent.com` works but is rate-limited per IP and lacks
CORS in some cases. Prefer the Pages URL for production.
