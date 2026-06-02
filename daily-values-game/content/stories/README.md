# Stories — authored content

Pre-generated, human-curated content. **Never live-generated per user** (§10).

- `example-story.json` is the reference shape. See `db/schema.sql` for the
  authoritative field semantics (`stories`, `gates`, `choices`).
- Loadings are a **prior**, stamped with a `framework_version_id` at import time.
- Authoring/curation flow lives in the admin tool (`apps/admin/`, deferred in v1)
  and follows the 7-step pipeline in `docs/PIPELINE.md`.

## The curation bar (the part AI is worst at — §6)

A story passes only if every gate is:

- **stake-y** — the choice costs something
- **valence-neutral** — no "right answer" signalled; both options defensible
- **a clean fork** — richness in the scene, not leaking into the options
- **not preachy**

## Import

`content/stories/*.json` → `db` via a loader (see `analysis/README.md` and the
`api` import stub). Anchors are written once and never re-imported with edits.
