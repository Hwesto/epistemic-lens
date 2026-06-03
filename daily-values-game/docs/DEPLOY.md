# Deploy — get a real, testable URL (free tier)

This puts the game online as a **frictionless anonymous** web app (no login: open
the link and play; choices persist; splits are real). Two free services:
**Vercel** (hosting + serverless API) and **Neon** (Postgres). Real Supabase login
stays built and is a later env-flip (see the end).

The repo is already deploy-ready: `vercel.json`, serverless functions in `/api`,
anonymous mode (`ALLOW_ANON`), and a one-shot DB bootstrap (`npm run db:bootstrap`)
are all in place and locally verified.

---

## Part 1 — What you need (accounts + tokens)

Create these (all free). Gather the values in the **right column** — that's
everything a fresh Claude session (or you) needs to deploy.

| # | Account | Do this | You get |
|---|---------|---------|---------|
| 1 | **GitHub** | Make a new **empty** repo, e.g. `daily-values-game` (private is fine). | repo URL |
| 2 | **Neon** (neon.tech) | New Project → copy the **connection string** (the "pooled" one, includes `?sslmode=require`). | `DATABASE_URL` |
| 3 | **Vercel** (vercel.com) | Sign up with GitHub. Then Account Settings → **Tokens** → create one. | `VERCEL_TOKEN` |

That's it. No Supabase, no payment. (Neon free ≈ 0.5 GB; Vercel Hobby is free for
personal use. Plenty for a friends-test.)

---

## Part 2 — Put the code in your fresh repo

From a checkout of this code (the `daily-values-game/` folder is self-contained):

```bash
cp -r daily-values-game /tmp/daily-values-game
cd /tmp/daily-values-game
rm -rf node_modules apps/*/node_modules        # don't commit deps
git init && git add . && git commit -m "Initial import: Daily Values-Mirror Game"
git branch -M main
git remote add origin https://github.com/<you>/daily-values-game.git
git push -u origin main
```

Now the repo **root** is the app (so `vercel.json`, `/api`, `apps/` are at the
top level — Vercel needs that).

---

## Part 3 — Deploy

Two ways. **Pick A (hand a fresh Claude session the tokens) for least effort, or
B (dashboard clicks) if you'd rather not share a token.**

### A. Let a fresh Claude session do it (recommended)

Start a new Claude Code session **on your new repo**, with a network policy that
allows outbound internet (so it can reach Neon + Vercel). Paste the prompt in
**Part 5**, filling in your `DATABASE_URL` and `VERCEL_TOKEN`. It will bootstrap
the DB, deploy, and hand you back the URL.

### B. Do it by hand (Vercel dashboard)

1. **Bootstrap the database** (one time, from your machine — needs Node 18+):
   ```bash
   cd daily-values-game && npm install
   DATABASE_URL="<your neon string>" npm run db:bootstrap
   ```
   Prints `✓ bootstrap complete — Story 1 is live`. (Idempotent; safe to re-run.)
2. **Import to Vercel:** vercel.com → Add New → Project → pick your GitHub repo.
   - Framework Preset: **Other** (the repo's `vercel.json` supplies build settings).
   - Leave Root Directory as the repo root.
3. **Environment variables** (Project → Settings → Environment Variables):
   - `DATABASE_URL` = your Neon string (with `?sslmode=require`)
   - `ALLOW_ANON` = `true`
4. **Deploy.** When it finishes you get `https://<project>.vercel.app` — open it
   and play.

> If you used Vercel's own **Storage → Neon** integration instead of step 1's
> Neon account, it sets `POSTGRES_URL` automatically (the app reads either); you
> still run `db:bootstrap` once against that connection string.

---

## Part 4 — Verify it's live

- Open the URL → you should land straight in **today's story** (no login).
- Play a beat → you see the social split.
- Reach the **debt** and **will** beats → the remembered-narration lead-ins show.
- Finish → the **share card** renders (`/api/share-card`).

Quick API smoke test:
```bash
curl -s https://<project>.vercel.app/api/today | head -c 200
curl -s https://<project>.vercel.app/api/me -H "x-anon-id: smoke-test"   # {"consented":true,...}
```

---

## Part 5 — Prompt for the fresh Claude session

Copy this into a new session on the new repo (fill in the two values):

```
This repo is the Daily Values-Mirror Game, ready to deploy as a frictionless
anonymous web app (no login) on Vercel + Neon. It's a monorepo: apps/web (Vite
PWA), apps/api (handlers, re-exported as Vercel functions in /api), db/ (schema +
migrations), content/ (the corpus). docs/DEPLOY.md has the full plan.

Credentials:
  DATABASE_URL = <your Neon connection string, includes ?sslmode=require>
  VERCEL_TOKEN = <your Vercel token>

Please:
1. Run `npm install` then `DATABASE_URL=... npm run db:bootstrap` to create the
   schema, seed the framework versions, load Story 1, and make it today's live
   story. Confirm it printed "bootstrap complete".
2. Deploy to Vercel with the Vercel CLI using VERCEL_TOKEN (npx vercel). Set env
   vars on the project: DATABASE_URL (the Neon string) and ALLOW_ANON=true. Deploy
   to production.
3. Smoke-test the deployed URL: GET /api/today returns the story; GET /api/me with
   an `x-anon-id` header returns consented:true; the web root loads the game.
4. Give me the live URL.

If the Vercel build fails on the serverless functions, the likely cause is the
/api/*.ts shims importing from ../apps/api — check the function bundling traces
those imports; the runtime deps (postgres, jose, @vercel/og, @supabase/supabase-js)
are in the root package.json. Iterate against the live build and tell me what you
changed.
```

---

## Later — flip on real accounts (optional)

When you want real sign-in + the consent gate instead of anonymous play:

1. Create a **Supabase** project. Set on Vercel: `VITE_SUPABASE_URL`,
   `VITE_SUPABASE_ANON_KEY`, `SUPABASE_URL`, `SUPABASE_JWT_SECRET`,
   `SUPABASE_SERVICE_ROLE_KEY`, and remove `ALLOW_ANON` (or set it `false`).
2. Redeploy. The web app now requires magic-link login and shows the consent gate;
   the API verifies Supabase JWTs. No code change — it's all wired
   (`apps/api/src/auth.ts`, `apps/web/src/lib/auth.tsx`).

## Notes / gotchas

- **The admin tool** (`apps/admin`) is a separate Vite app; it isn't part of this
  web deploy. Run it locally, or deploy it as a second Vercel project later
  (gate it behind real auth + `is_admin` first — don't expose it anonymously).
- **Custom domain:** Vercel → Project → Domains. Free.
- **One story for now:** `db:bootstrap` loads Story 1 only. More stories load via
  the admin tool's import, or extend the bootstrap script.
