import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../../src/db";
import { currentUserId } from "../../src/auth";

// Data export (GDPR access right): the user's own raw choice history + derived
// profile as JSON. Read-only; reflects the immutable log.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  const userId = await currentUserId(req);
  if (!userId) {
    res.status(401).json({ error: "auth required" });
    return;
  }

  const sql = db();

  const events = await sql`
    select story_id, gate_id, choice_id, rejected_choice_id, decided_at, response_ms
    from choice_events
    where user_id = ${userId}
    order by decided_at
  `;
  const profile = await sql`
    select framework_version_id, scored_at, axis_scores, axis_confidence, consistency
    from profiles where user_id = ${userId}
  `;
  const consents = await sql`
    select version, granted_at, withdrawn_at from consents where user_id = ${userId}
  `;

  res.setHeader("content-disposition", 'attachment; filename="my-values-data.json"');
  res.status(200).json({
    exported_at: new Date().toISOString(),
    choice_events: events,
    profiles: profile,
    consents,
  });
}
