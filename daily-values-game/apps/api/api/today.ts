import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../src/db";

// Serve today's shared story. Same for everyone, cacheable, cheap (§1).
// axis_loadings are intentionally NOT returned — they are a measurement detail
// and must not bias the player's choice.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  const sql = db();

  const stories = await sql`
    select id, publish_date, genre, title, body, art_url
    from stories
    where publish_date = current_date and status = 'live'
    limit 1
  `;
  if (stories.length === 0) {
    res.status(404).json({ error: "no story today" });
    return;
  }
  const story = stories[0];

  const gates = await sql`
    select id, sequence, body, art_url, is_terminal
    from gates where story_id = ${story.id} order by sequence
  `;

  const gateIds = gates.map((g: any) => g.id);
  const choices = gateIds.length
    ? await sql`
        select id, gate_id, label, next_gate_id
        from choices where gate_id in ${sql(gateIds)}
        order by gate_id, position
      `
    : [];

  const withChoices = gates.map((g: any) => ({
    ...g,
    choices: choices.filter((c: any) => c.gate_id === g.id),
  }));

  // Today's story is immutable for the day → allow CDN/edge caching.
  res.setHeader("Cache-Control", "public, s-maxage=600, stale-while-revalidate=86400");
  res.status(200).json({ ...story, gates: withChoices });
}
