# Architecture

```
   CONTENT PIPELINE = EXPERIMENT DESIGN  (offline, not user-facing)
   plan coverage → Opus draft → human curate → tag (loadings PRIOR + edge +
   scope + framing + anchor flag + exploratory flag) → schedule by date
                         │ writes
                         ▼
   PWA CLIENT  ◄──HTTPS──►  API / BACKEND  ◄──►  POSTGRES
   (browser)               (serverless)         - stories / gates / choices
   - daily story           - serve story        - choice_events ∞ (append-only)
   - choices               - record choice       - users / profiles
   - split                 - compute split       - framework_versions
   - reveal                - derive profile      - coverage / anchor_health views
   - share card            - friend-diff
        │ static                │ aggregates (cached)         │ raw log
        ▼                       ▼                             ▼
      CDN                  CACHE (Redis/KV)            ANALYSIS (offline)
   today's story          split counts               confirmatory + exploratory
   + assets                                           factor analysis; reliability
                                                      via anchors → refines framework
                                                              │ new framework_version
                                                              ▼ re-score from raw log
```

## Core principle

The daily story is **static content on a CDN** (same for everyone, cacheable,
cheap). The backend does **light writes** (record a choice) and **light reads**
(split counts, profile). The **raw choice log feeds an offline analysis loop**
that periodically refines the scoring framework and re-derives every profile from
the immutable history. That loop turns the prior into a finding — and it only
works because the log is append-only and richly tagged **from day one**.

## Stack (defaults — swap for what your builder knows)

| Layer | Default | In this scaffold |
|-------|---------|------------------|
| Client | React + Vite PWA + Tailwind | `apps/web` |
| API | Serverless functions | `apps/api/api/*` (Vercel-style handlers) |
| DB | Postgres (Supabase/Neon/Railway) | `db/schema.sql` |
| Auth | Supabase Auth / Clerk | `apps/api/src/auth.ts` (stub) |
| Cache | Redis / KV (split counts) | `daily_aggregates` table (source of truth) |
| Share card | Server-side `@vercel/og` / Satori | `apps/api/api/share-card.ts` |
| Stats | Python (factor_analyzer, statsmodels) | `analysis/` |
| LLM | Claude API — **offline only**, never per-user | pipeline (not in v1 code) |

**MVP simplification:** Supabase alone covers DB + Auth + Storage + APIs.

## Cost shape (§11)

Hosting/CDN free→low tens of $/mo well into tens of thousands of users; DB/Auth
free→low hundreds at scale; LLM mostly **fixed** (~365 generations/yr + offline
tagging, amortised across all users). The real cost is **editorial + the
psychometrician** — people, not servers. Never live-generate content per user.
