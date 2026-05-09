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
| `<story>/briefing.json`               | application/json | (raw corpus, see source repo)   |
| `<story>/metrics.json`                | application/json | (LaBSE cosine + divergence + vocab) |
| `<story>/analysis.md`                 | text/markdown    | structure: `docs/HORMUZ_CORRELATION.md` |
| `<story>/thread.json`                 | application/json | `/api/schema/thread.schema.json`   |
| `<story>/carousel.json`               | application/json | `/api/schema/carousel.schema.json` |
| `<story>/long.json`                   | application/json | `/api/schema/long.schema.json`     |

## Schemas — `/api/schema/`

The three draft formats are JSON Schema 2020-12. Validate at parse time
in your frontend if you want strong typing.

```bash
curl https://hwesto.github.io/epistemic-lens/api/schema/thread.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/carousel.schema.json
curl https://hwesto.github.io/epistemic-lens/api/schema/long.schema.json
```

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
