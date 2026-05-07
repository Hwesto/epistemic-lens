# URGENT — do these next time at a computer

Two one-time setup steps gate the whole pipeline. Once done, the cron
runs unattended forever.

---

## 1. Generate + paste the Claude OAuth token

This needs a terminal (the `claude setup-token` step). Without it,
the `analyze` and `draft` jobs in daily.yml will fail fast with a
clear error — they won't burn cycles, but they also won't produce
analyses or drafts.

```bash
# In a terminal on your laptop:
claude setup-token
# Copy the token string it prints.
```

Then in your browser:

1. Go to: https://github.com/hwesto/epistemic-lens/settings/secrets/actions
2. Click **New repository secret**
3. **Name:** `CLAUDE_CODE_OAUTH_TOKEN`
4. **Value:** paste the token
5. Click **Add secret**

---

## 2. Confirm GitHub Pages is enabled for THIS repo with Actions source

You said Pages is enabled on your account — that's at the org level.
It still needs to be turned on per-repo, with the **source set to
"GitHub Actions"** (not "Deploy from a branch"). Our `publish_api`
job uses the official `actions/deploy-pages` flow, which only works
with the Actions source.

1. Go to: https://github.com/hwesto/epistemic-lens/settings/pages
2. Under **Source**, select **GitHub Actions**
3. Save. You should see a URL like
   `https://hwesto.github.io/epistemic-lens/`

That's it. No build config, no Jekyll, nothing else.

---

## 3. Test the chain (optional but recommended)

Once both above are done, trigger a manual run to validate before
tomorrow's 07:00 UTC schedule:

1. https://github.com/hwesto/epistemic-lens/actions/workflows/daily.yml
2. Click **Run workflow** → pick `main` → **Run workflow**
3. Watch all four jobs go green: `ingest → analyze → draft → publish_api`
4. Visit `https://hwesto.github.io/epistemic-lens/api/latest.json` — should
   return JSON with today's date.

---

## What happens if you forget

- **Forget #1**: `analyze` job fails with `CLAUDE_CODE_OAUTH_TOKEN repo
  secret is missing.` Ingest still runs and commits snapshots/briefings,
  so no data is lost.
- **Forget #2**: `publish_api` job fails with a Pages permission error.
  Drafts are still committed to the repo; the API is just not yet
  served at the public URL. Re-run after enabling.

Both are recoverable — no destructive failure modes.
