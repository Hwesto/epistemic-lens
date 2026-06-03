import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../../src/db";
import { currentUserId } from "../../src/auth";

// Update the user's privacy settings. Profile is private by default (§10); this
// lets the user opt in to making it shareable. Only the requesting user's own
// settings are touched.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "POST" && req.method !== "PATCH") {
    res.status(405).json({ error: "POST or PATCH" });
    return;
  }
  const userId = await currentUserId(req);
  if (!userId) {
    res.status(401).json({ error: "auth required" });
    return;
  }

  const profilePublic = Boolean(req.body?.profile_public);
  const sql = db();
  await sql`
    update users
    set privacy_settings = privacy_settings || ${sql.json({ profile_public: profilePublic })}
    where id = ${userId}
  `;
  res.status(200).json({ ok: true, profile_public: profilePublic });
}
