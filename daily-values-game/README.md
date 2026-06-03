# Daily Values-Mirror Game

One **shared** story a day. You make a choice; you see how the world split; over
time you get a private, honestly-hedged read on your own values. Underneath,
invisibly, every choice feeds a **designed experiment** in moral psychometrics.

> **Epistemic status (read first).** The *engineering* here is built with
> confidence. The *measurement* framework (the axes, the loadings, the whole
> taxonomy) is a **prior to be tested, not settled truth.** It becomes a finding
> only by factor-analysing real behavioural data — so the corpus is built to be
> capable of **proving the framework wrong.** Status today: pre-pilot, n≈3, zero
> real data. Build the engineering with confidence; hold the measurement loosely.

This is the **web-first v1 foundation** scaffold. See `docs/` for the full spec
distilled into architecture, measurement, pipeline, build-phase, and privacy notes.

## The three things that must be right from day one

Because they're the things you can **cannot retrofit** (§10):

1. **The append-only, richly-tagged choice log** — `db/schema.sql`
   (`choice_events`, immutable; edge/scope/framing/process/response_ms tags).
2. **The anchors** — `content/coverage/anchors.md` (planted now or lost forever).
3. **The share card** — `apps/api/api/share-card.ts` (the growth engine).

Everything else upgrades in place — including the framework itself.

## Layout

```
db/                  Postgres schema (the spine), framework seed, anchors
  schema.sql           append-only log, anchors, coverage/anchor_health views,
                       immutability + anchor-protection triggers
  seed/                framework_versions prior-v1 (the held-loosely prior)
content/             the corpus AS a designed experiment
  coverage/            coverage_plan.md (edge matrix, targets), anchors.md
  stories/             example-story.json (the tagged content contract)
apps/web/            React + Vite + Tailwind PWA (the daily story, split, reveal, share)
apps/api/            serverless functions (today, choice, split, profile, share-card,
                     admin/import-story)
analysis/            offline psychometrics notebook layer (confirmatory + exploratory)
docs/                architecture, measurement, pipeline, build phases, privacy
```

## Run it (end-to-end)

Needs a Postgres `DATABASE_URL` (hosted Supabase/Neon, or local). `db:*` scripts
use `psql`; the API runs in a small Node dev server (`apps/api/dev-server.ts`,
via `tsx`) — no Vercel CLI needed for local dev.

```bash
# 0. point at your database (or copy .env.example → apps/api/.env)
export DATABASE_URL=postgres://user:pass@host:5432/dbname

# 1. schema + framework seed (db:reset drops & recreates — dev only)
npm run db:reset

# 2. a dev fixture story dated TODAY, so /api/today has something to serve
npm run seed:dev

# 3. API on :3000  (one terminal)
npm install --workspaces
npm run dev:api

# 4. web client  (another terminal)
npm run dev:web

# 5. admin tool  (another terminal) — coverage, authoring, scheduling
npm run dev:admin
```

Then open the Vite URL and play the loop. The dev server injects a `dev-user`
auth subject (made **admin + consented** by `seed:dev`), so neither accounts nor
a Supabase project are needed locally. In production, auth is real **Supabase**
JWT verification (`apps/api/src/auth.ts`): the web app gates play behind sign-in
+ consent, and the admin tool is gated by the `is_admin` flag. Account deletion
**anonymises and retains** de-identified events — see `docs/PRIVACY.md`. Set the
`SUPABASE_*` / `VITE_SUPABASE_*` vars (`.env.example`) to enable real login.

> The dev fixture is **not** the real anchor corpus — it only exercises the loop.
> Production content is loaded via the admin import endpoint (`POST
> /api/admin/import-story`) from `content/stories/*.json`.

## What's real vs deferred in v1 (§9)

| Real | Deferred / faked |
|------|------------------|
| Daily shared-story delivery | Validated scoring (uses the Opus-tagged **prior** loadings) |
| Append-only, richly-tagged log | Calibrated confidence intervals (rough heuristic) |
| Anchors + coverage tracking | Recurring characters, the live moment |
| The share card | Native app, push at scale |
| Social split | B2B layer, custom/personalised stories |
| Private profile + the reveal (hedged) | Real IRT/factor calibration (Phase 2, from the log) |

The reveal is **honestly-hedged Forer-grade** in v1 — "your read so far", a game.
It converts to real measurement in Phase 2 *from the data this log gathers*.

## Provenance

Originally scaffolded inside the `epistemic-lens` repo under `daily-values-game/`
(the session environment could not create a standalone GitHub repo). Intended to
be extracted into its own repository — see `docs/EXTRACTION.md`.
