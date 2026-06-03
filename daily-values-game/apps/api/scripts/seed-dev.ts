// DEV FIXTURE seed. Imports a story dated TODAY (status=live) so /api/today
// returns a playable story during local/hosted dev. This is NOT the real anchor
// corpus (that is a separate content layer) — it exists only to exercise the loop.
//
// Run:  npm run seed:dev   (tsx --env-file=.env scripts/seed-dev.ts)
import postgres from "postgres";
import { importStory, type StoryInput } from "../src/import";

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL is not set");
  process.exit(1);
}

const today = new Date().toISOString().slice(0, 10);

const fixture: StoryInput = {
  publish_date: today,
  genre: "kitchen-sink realism",
  title: "The Reference (dev fixture)",
  body:
    "Maya has managed Theo for two years. He is kind, tries hard, and is — by " +
    "every honest measure — not good at the job. He has just asked her to be a " +
    "reference for a role he desperately wants and, she suspects, also cannot do.",
  status: "live",
  gates: [
    {
      sequence: 1,
      body:
        "The hiring manager calls. 'Would you recommend him without reservation?' " +
        "The honest answer is no. The kind answer is yes.",
      is_terminal: false,
      conflict_edge: "care__honesty",
      scope_variant: "stranger",
      framing_variant: "identifiable_victim",
      process_frame: "outcome",
      choices: [
        { label: "Vouch for him. He needs the chance.", next_sequence: 2, axis_loadings: { care: 0.8, honesty: -0.6, loyalty: 0.3 } },
        { label: "Tell the truth, gently.", next_sequence: 2, axis_loadings: { honesty: 0.8, care: -0.4, authority: 0.2 } },
      ],
    },
    {
      sequence: 2,
      body: "Later, Theo asks what you said.",
      is_terminal: true,
      is_exploratory: true,
      scope_variant: "kin",
      framing_variant: "neutral",
      choices: [
        { label: "Tell him exactly what you told the manager.", axis_loadings: { honesty: 0.7 } },
        { label: "Soften it to protect the relationship.", axis_loadings: { care: 0.5, honesty: -0.3 } },
      ],
    },
  ],
};

const sql = postgres(url, { max: 1 });

try {
  // idempotent for dev: clear any existing story for today, then import
  await sql`delete from stories where publish_date = ${today}`;
  const result = await sql.begin((tx) => importStory(tx, fixture));
  console.log(`seeded dev story for ${today}:`, result);

  // dev-user: the subject the dev server injects. Make it an admin and grant
  // consent so the loop AND the admin tool work locally without real Supabase.
  const consentVersion = process.env.CONSENT_VERSION ?? "v1";
  const [devUser] = await sql<{ id: string }[]>`
    insert into users (auth_id, is_admin)
    values ('dev-user', true)
    on conflict (auth_id) do update set is_admin = true
    returning id
  `;
  await sql`
    insert into consents (user_id, version)
    select ${devUser.id}, ${consentVersion}
    where not exists (
      select 1 from consents
      where user_id = ${devUser.id} and version = ${consentVersion} and withdrawn_at is null
    )
  `;
  console.log(`dev-user ${devUser.id} is admin + consented (${consentVersion})`);
} catch (e) {
  console.error("seed failed:", e);
  process.exitCode = 1;
} finally {
  await sql.end();
}
