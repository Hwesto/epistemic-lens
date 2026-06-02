# Seed

Run after `db/schema.sql`:

```bash
psql "$DATABASE_URL" -f db/seed/0001_framework_v1.sql
```

- `0001_framework_v1.sql` — the **prior** (`framework_versions` row). Held
  loosely; everything is scored against the latest framework version. New
  versions are appended by the analysis loop (see `analysis/README.md`), never
  edited in place.

Stories (including the planted anchors) are loaded via the admin import endpoint
(`apps/api/api/admin/import-story.ts`) from `content/stories/*.json`, which stamps
each choice's loadings with the active framework version. Anchors, once imported,
are immutable.
