import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../src/db";
import { currentUserId, CONSENT_VERSION } from "../src/auth";

// Record explicit consent for the current consent version, before any profiling
// (§10). Idempotent: re-granting the same active version is a no-op.
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

  const sql = db();
  await sql`
    insert into consents (user_id, version)
    select ${userId}, ${CONSENT_VERSION}
    where not exists (
      select 1 from consents
      where user_id = ${userId} and version = ${CONSENT_VERSION} and withdrawn_at is null
    )
  `;

  res.status(201).json({ ok: true, version: CONSENT_VERSION });
}
