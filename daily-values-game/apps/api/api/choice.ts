import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../src/db";
import { currentUserId } from "../src/auth";

// Record one decision into the APPEND-ONLY log. This is the single most
// important write in the system — it is the asset (§4, §10). We never update or
// delete; the DB enforces immutability. We also bump the cached split counter.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "POST only" });
    return;
  }

  const userId = await currentUserId(req);
  if (!userId) {
    res.status(401).json({ error: "auth required" });
    return;
  }

  const { storyId, gateId, choiceId, rejectedChoiceId, responseMs } = req.body ?? {};
  if (!storyId || !gateId || !choiceId) {
    res.status(400).json({ error: "storyId, gateId, choiceId required" });
    return;
  }

  const sql = db();

  await sql.begin(async (tx) => {
    // append-only insert; richly tagged context is derivable via gate_id
    await tx`
      insert into choice_events
        (user_id, story_id, gate_id, choice_id, rejected_choice_id, response_ms)
      values
        (${userId}, ${storyId}, ${gateId}, ${choiceId},
         ${rejectedChoiceId ?? null}, ${responseMs ?? null})
    `;

    // bump cached social split (source of truth; mirror to Redis/KV in prod)
    await tx`
      insert into daily_aggregates (story_id, choice_id, count)
      values (${storyId}, ${choiceId}, 1)
      on conflict (story_id, choice_id) do update
        set count = daily_aggregates.count + 1
    `;
  });

  res.status(201).json({ ok: true });
}
