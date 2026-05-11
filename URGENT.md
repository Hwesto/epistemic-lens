# URGENT — one-shot setup from a computer

> **Historical (meta-v1.0.0 era).** This file is the one-time setup
> checklist used when the methodology pin was first established. The
> setup it describes is long-done — the daily cron has been running
> unattended for many pin eras (current: meta-v2.9.0). Kept for
> reproducibility and in case a from-scratch deployment is ever needed.
>
> For the current operational guide, see
> [`docs/OPERATIONS.md`](docs/OPERATIONS.md).
> For the methodology pin contract, see
> [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).
> For audit progress + backlog, see
> [`docs/AUDIT_BACKLOG.md`](docs/AUDIT_BACKLOG.md).

This is a checklist for the **next time you're at a laptop**. After it's
done, the entire pipeline runs unattended and you can review on your
phone every day.

There are three setup steps. They are not interchangeable; do them in
order, verify each before moving on.

You will need ~15 minutes total: ~5 min for OAuth, ~3 min for Pages, ~2
min for branch protection, plus ~5 min for the smoke-test run.

---

## Pre-flight (do this first, ~2 min)

Verify you're on the right machine, the right account, and have what
you need. Skip nothing — every line below has bitten this project
before.

- [ ] Open a terminal. Run `git -C ~/path/to/epistemic-lens status` and
      confirm you're on `main` or a branch you intend to use, with a
      clean working tree.
- [ ] `gh auth status` (or open https://github.com — whichever — and
      confirm you're logged in as **`hwesto`**, the account that owns
      the repo). Wrong account = secrets land in the wrong place and
      Pages won't deploy.
- [ ] `claude --version` should print a version number. If it errors,
      install Claude Code first:
      `curl -fsSL https://claude.ai/install.sh | bash` (or follow the
      install page; the binary needs to be on PATH).
- [ ] Open https://github.com/hwesto/epistemic-lens/actions and confirm
      the **Actions tab is enabled** (some org-imported repos disable
      it by default). If you see "Workflows aren't being run on this
      forked repository," click the green button to enable.

If any of the above fails, fix it before going further. The rest of
this doc assumes the four checks pass.

---

## Step 0 — Push the methodology baseline tag (~30 sec)

The `meta-v1.0.0` git tag was created locally during the merge that
introduced this file, but the agent environment couldn't push tags
(harness restriction). The tag points to the right commit on `main`;
you just need to push it once. This anchors the day-zero pin so
future major bumps (`meta-v2.0.0`) have something concrete to be
"after."

### 0a. Push the tag

```bash
cd ~/path/to/epistemic-lens
git fetch origin && git checkout main && git pull --ff-only

# Recreate the tag locally — your clone almost certainly doesn't have
# it yet (it lived only in the agent's environment):
git tag -a meta-v1.0.0 cd67e81 \
  -m "methodology pin baseline — 235 feeds, 54 buckets, 5 stories, 4 prompts"

git push origin meta-v1.0.0
```

### 0b. Verify

- [ ] `git ls-remote --tags origin | grep meta-v1.0.0` returns one
      line.
- [ ] https://github.com/hwesto/epistemic-lens/tags lists
      `meta-v1.0.0`. Click it — the target commit should be `cd67e81`
      ("methodology pin (v1.0.0) + comprehensive URGENT.md").

### Alternative: GitHub UI

If you'd rather not touch the terminal:

1. https://github.com/hwesto/epistemic-lens/releases/new
2. **Choose a tag:** type `meta-v1.0.0`, click "Create new tag: …"
3. **Target:** select commit `cd67e81` from the dropdown.
4. **Release title:** `meta-v1.0.0 — methodology baseline`
5. **Description:** copy from the tag message above.
6. **Publish release** — this creates and pushes the tag in one click.

### Failure modes

- `git push origin meta-v1.0.0` returns `403`/permission denied →
  you're not authenticated as `hwesto` (or a collaborator with push
  rights). Fix `gh auth status` from pre-flight.
- Tag `meta-v1.0.0` already exists locally with a different SHA →
  someone (or a previous run) created a wrong-target tag. Delete it
  with `git tag -d meta-v1.0.0`, then re-run 0a.
- Tag exists on remote with a different SHA → don't force-push (it
  invalidates anyone who's already fetched it). Pick `meta-v1.0.0a`
  or accept the existing one.

---

## Step 1 — Claude OAuth token (~5 min)

The `analyze` and `draft` jobs in `daily.yml` call Claude via the
`anthropics/claude-code-action`. They need a long-lived OAuth token in
the `CLAUDE_CODE_OAUTH_TOKEN` repo secret. Without it, both jobs fail
fast with a precheck error before burning any tokens — no data is
lost, the chain just stops at `ingest`.

### 1a. Generate the token

In your terminal:

```bash
claude setup-token
```

You'll be walked through a browser flow. When it finishes, the
terminal prints a token starting with `sk-ant-oat01-...`. **Copy the
whole thing.** It's shown once.

If `claude setup-token` errors with "command not found", your CLI
install is missing the subcommand — update Claude Code to the latest
version (`claude update` or reinstall). The token is *not* an
Anthropic Console API key; do not try to substitute one.

### 1b. Paste it into the repo secret

1. Go to https://github.com/hwesto/epistemic-lens/settings/secrets/actions
2. Click **New repository secret** (green button, top-right).
3. **Name:** `CLAUDE_CODE_OAUTH_TOKEN` — case sensitive, exact.
4. **Secret:** paste the token from 1a. No quotes, no whitespace.
5. Click **Add secret**.

You should see `CLAUDE_CODE_OAUTH_TOKEN` listed under "Repository
secrets" with a "Updated now" timestamp.

### 1c. Verify

The token's validity isn't testable directly from the UI. We test it
in Step 4 (smoke test). For now just confirm the secret name appears
on the secrets page.

### 1d. Calendar reminder for rotation

OAuth tokens expire (~1 year for `claude setup-token`'s output, but
this can change). Add a calendar event for **one year from today**
titled "Rotate `CLAUDE_CODE_OAUTH_TOKEN` for epistemic-lens" with the
URL to this file as the description. When it fires, re-run 1a–1b.

### Failure modes you might hit later

- `analyze` job logs `CLAUDE_CODE_OAUTH_TOKEN repo secret is missing.`
  → secret name is wrong (must be exact, case-sensitive) or you pasted
  it into a *user* secret, not a *repo* secret.
- `analyze` job logs `403` from `api.anthropic.com` → token is expired
  or revoked. Re-run `claude setup-token`, replace the secret value.
- `analyze` job logs `429 rate_limit` → don't re-run; wait until the
  next 07:00 UTC. Anthropic's daily/minute limits will reset.

---

## Step 2 — GitHub Pages source (~3 min)

`publish_api` deploys the `api/` tree as a static site so phones,
videos, and any future renderer can fetch
`https://hwesto.github.io/epistemic-lens/api/latest.json`. It uses the
official `actions/deploy-pages@v4` flow, which **only works when the
Pages source is set to GitHub Actions** — not "Deploy from a branch".

### 2a. Enable Pages, source = Actions

1. Go to https://github.com/hwesto/epistemic-lens/settings/pages
2. Under **Build and deployment → Source**, select **GitHub Actions**.
   ⚠️ This is a different option from "Deploy from a branch". If you
   pick the wrong one, `publish_api` fails with a permission error
   and you have to come back here.
3. There's no "Save" button — selecting it is the save.
4. The page should now show "Your site is live at
   `https://hwesto.github.io/epistemic-lens/`" (or "ready to deploy"
   until the first run succeeds).

### 2b. Verify

- [ ] Open https://hwesto.github.io/epistemic-lens/ in a browser. You
      should see a 404 ("There isn't a GitHub Pages site here.") —
      *not* the Pages-not-configured error. A 404 here is **correct**;
      it means Pages is enabled but `publish_api` hasn't deployed yet.
      The first deploy in Step 4 fixes the 404.

### Failure modes

- `publish_api` job logs `Resource not accessible by integration` →
  Pages source is still "Deploy from a branch", not "GitHub Actions".
  Go back to 2a.
- `publish_api` succeeds but the URL still 404s after several minutes
  → check https://github.com/hwesto/epistemic-lens/settings/pages
  again; the deploy URL is shown there. CDN caching can take ~5 min
  on the first deploy.

---

## Step 3 — Branch protection (~2 min)

This is the safety rail that stops a bad commit from corrupting the
methodology pin or the bot's data path. Without it, anyone (or any
agent) with push access can land code that breaks longitudinal
comparisons.

### 3a. Add a ruleset for `main`

1. Go to https://github.com/hwesto/epistemic-lens/settings/rules
2. Click **New ruleset → New branch ruleset**.
3. **Ruleset name:** `main protection`.
4. **Enforcement status:** Active.
5. **Target branches:** Add `main` (use "Include default branch").
6. Under **Branch rules**, enable:
   - [x] **Restrict deletions**
   - [x] **Require linear history**
   - [x] **Require status checks to pass**
     - Add required check: `validate-meta`
   - [x] **Block force pushes**
7. Under **Bypass list**: leave empty for now. The `epistemic-lens-bot`
   commits as a regular user via `GITHUB_TOKEN`, which respects the
   ruleset; required-checks are satisfied by the same workflow run, so
   no bypass is needed.
8. **Create**.

We require *only* `validate-meta` (not `unit-tests`) because
`unit-tests` is gated on Python file paths and won't trigger when the
bot pushes pure data (snapshots, briefings) — making it a required
check would block the daily commit. `validate-meta` runs on every push
to `main`, every PR, and every `workflow_dispatch`.

### 3b. Verify

- [ ] Try to push a trivial change directly to `main` from your laptop.
      It should be rejected with `protected branch: required status
      check "validate-meta" not satisfied`. (Then revert the local
      attempt — `git reset --soft HEAD~1` and re-push to a feature
      branch.)

### Failure modes

- Bot's daily snapshot push is rejected with `all push attempts failed`
  → the required check (`validate-meta`) didn't run on the bot's push.
  This happens when the validating workflow has path filters that
  exclude `snapshots/` / `briefings/` / etc. The fix is in this repo:
  `validate-meta` lives in `.github/workflows/meta-check.yml` with
  **no path filters**, so it runs on every push. If you ever move it
  back into a path-filtered workflow, bot pushes will silently break
  the same way.
- Bot's push rejected even though `meta-check` ran → check the rule
  named `main protection`: the required-check name must be exactly
  `validate-meta` (job name, case-sensitive). If you accidentally
  added `unit-tests` or `e2e-smoke` as required, remove them — they
  are path-filtered and won't run on bot data pushes.

---

## Step 4 — Smoke test (~5 min)

Run the full chain manually before letting tomorrow's 07:00 UTC cron
hit it cold.

### 4a. Trigger a manual run

1. Go to https://github.com/hwesto/epistemic-lens/actions/workflows/daily.yml
2. Click **Run workflow** (right side).
3. Branch: `main`. Click **Run workflow** (green button).

### 4b. Watch each job

The chain is `ingest → analyze → draft → publish_api`. Click into
the run and watch them go green in order. Expected timing:

| Job | Expected duration | Common failure |
|---|---|---|
| `ingest` | 4–8 min | feed timeouts (auto-retried; should still succeed) |
| `analyze` | 5–15 min | `CLAUDE_CODE_OAUTH_TOKEN` missing → fix Step 1 |
| `draft` | 10–25 min | schema validation fails → see "Schema fail" below |
| `publish_api` | 1–2 min | Pages source wrong → fix Step 2 |

### 4c. Verify the output

After all four jobs are green:

- [ ] Visit `https://hwesto.github.io/epistemic-lens/api/latest.json` —
      should return JSON with `"date": "<today UTC>"` and `n_stories >= 1`.
- [ ] Visit `https://hwesto.github.io/epistemic-lens/api/<DATE>/index.json` —
      should list each story with its `briefing`, `metrics`, `analysis`,
      `thread`, `carousel`, `long` artifact paths.
- [ ] Pick one story and visit its `analysis.md` URL. Read it. This is
      what shows up in your phone-review PR every day. If the writing
      is bad, the prompts in `.claude/prompts/` need work.
- [ ] Confirm every JSON file under `api/` has `"meta_version": "1.0.0"`
      at the top — that's the methodology pin in action.

### 4d. Failure recovery

If a job fails partway, the chain stops. **Re-running the failed job
is safe** — every step is idempotent (writes deterministic filenames
based on the date). Click **Re-run failed jobs** in the run UI.

If `ingest` succeeds but `analyze` fails repeatedly, you've got
upstream data on disk but no analyses. That's fine — tomorrow's run
will pick up the same date and try again, since the bot pushed the
ingest artifacts.

---

## Schema fail troubleshooting

If `draft` reports `schema fail: <message>`:

1. Open `docs/api/schema/<format>.schema.json` (where `<format>` is
   `thread`, `carousel`, or `long`).
2. Open the failing draft file under `drafts/<DATE>_<story>_<format>.json`.
3. Claude wrote the wrong shape. Two recoveries:
   - **Quick:** delete the bad draft, re-run the `draft` job. Claude
     will regenerate. Often this is a one-shot oversight.
   - **Persistent:** the prompt in `.claude/prompts/draft_<format>.md`
     is ambiguous. Open a PR to tighten the schema-mention in the
     prompt. (This is a methodology-prompt change → bumps `meta_version`
     because `prompts_hash` will drift; CI's `validate-meta` will tell
     you to run `python baseline_pin.py --bump minor --reason "..."`.)

---

## Disable switch — if you need to pause the cron

One file edit, no UI clicks:

```yaml
# .github/workflows/daily.yml
on:
  # schedule:
  #   - cron: '0 7 * * *'
  workflow_dispatch:
```

Comment out the `schedule:` block, push, the cron stops. Re-enable by
uncommenting. The `workflow_dispatch:` line lets you still trigger
manually for testing.

---

## What you don't have to do

- ❌ You don't need to install Python deps, configure Pages build
  config, set up Jekyll, or enable Actions billing.
- ❌ You don't need to add the bot as a collaborator. It uses
  `GITHUB_TOKEN`, which is auto-provisioned per workflow run.
- ❌ You don't need to register a domain. `hwesto.github.io/...` is
  free and stable. Custom domain is a future polish.

---

## Recoverability

Every step is recoverable. If you forget Step 1, you can do it
tomorrow — the cron will fail `analyze` cleanly until you do, and no
data is lost. If you forget Step 2, drafts get committed but the
public API stays on the previous version until you fix Pages and
re-run `publish_api`. Step 3 is purely defensive; not having it
doesn't break anything until someone pushes bad code.

The only step that **must** happen on a computer is Step 1 — the
`claude setup-token` flow needs an interactive browser. Steps 2, 3, 4
are all clickable from a phone if you'd rather, but they're easier on
desktop.
