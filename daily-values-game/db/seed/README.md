# Seed

Run after `db/schema.sql` (from the project root):

```bash
npm run db:schema   # or: psql "$DATABASE_URL" -f db/schema.sql
npm run db:seed     # or: psql "$DATABASE_URL" -f db/seed/0001_framework_v1.sql
# dev only — drops & recreates public schema, then schema + seed:
npm run db:reset
```

**No `psql`?** (e.g. you only have the Supabase dashboard) — paste the contents
of `db/schema.sql` then `db/seed/0001_framework_v1.sql` into the Supabase SQL
editor and run them in that order. `gen_random_uuid()` is built into Postgres
13+ (Supabase/Neon are 15+), so no extension is required.

- `0001_framework_v1.sql` — the **prior** (`framework_versions` row). Held
  loosely; everything is scored against the latest framework version. New
  versions are appended by the analysis loop (see `analysis/README.md`), never
  edited in place.

Stories (including the planted anchors) are loaded via the admin import endpoint
(`apps/api/api/admin/import-story.ts`) from `content/stories/*.json`, which stamps
each choice's loadings with the active framework version. Anchors, once imported,
are immutable.
