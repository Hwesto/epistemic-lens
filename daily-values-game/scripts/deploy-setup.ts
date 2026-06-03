// One-time deploy bootstrap. Run once against your hosted Postgres after creating
// it (Neon / Vercel Postgres / Supabase):
//
//   DATABASE_URL="postgres://...sslmode=require" npm run db:bootstrap
//
// It is idempotent: creates the schema + framework seeds if missing, loads Story 1
// if missing, and makes it today's live story. Re-running is safe.
import postgres from "postgres";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { importStory } from "../apps/api/src/import";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const file = (p: string) => readFileSync(resolve(root, p), "utf8");

const url = process.env.DATABASE_URL || process.env.POSTGRES_URL;
if (!url) {
  console.error("Set DATABASE_URL (or POSTGRES_URL) to your hosted Postgres.");
  process.exit(1);
}
const local = url.includes("localhost") || url.includes("127.0.0.1");
const sql = postgres(url, { max: 1, ssl: local ? false : "require" });

async function tableExists(name: string): Promise<boolean> {
  const r = await sql`select to_regclass(${"public." + name}) as t`;
  return r[0].t !== null;
}

async function main() {
  try {
  if (!(await tableExists("framework_versions"))) {
    console.log("· creating schema…");
    await sql.file(resolve(root, "db/schema.sql"));
    console.log("· seeding framework versions…");
    await sql.file(resolve(root, "db/seed/0001_framework_v1.sql"));
    await sql.file(resolve(root, "db/seed/0002_framework_v2.sql"));
  } else {
    console.log("· schema already present — skipping");
  }

  const title = "The Baker's Last Day";
  const existing = await sql`select id from stories where title = ${title} limit 1`;
  if (existing.length === 0) {
    console.log("· importing Story 1…");
    const story = JSON.parse(file("content/stories/01-the-bakers-last-day.json"));
    await sql.begin((tx) => importStory(tx, story));
  } else {
    console.log("· Story 1 already imported — skipping");
  }

  // make Story 1 today's live story (publish_date is unique per day)
  await sql`
    update stories set publish_date = current_date, status = 'live'
    where title = ${title}
      and not exists (select 1 from stories s2 where s2.publish_date = current_date and s2.title <> ${title})
  `;
  console.log("✓ bootstrap complete — Story 1 is live for", new Date().toISOString().slice(0, 10));
  } catch (e: any) {
    console.error("bootstrap failed:", e.message ?? e);
    process.exitCode = 1;
  } finally {
    await sql.end();
  }
}

main();
