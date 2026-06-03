import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../src/db";
import { currentUserId, hasActiveConsent, CONSENT_VERSION } from "../src/auth";

// Lightweight identity/status for the client: who am I, am I admin, have I
// consented. Lets the app gate play on consent and the admin tool on is_admin
// without leaking anything sensitive.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  const userId = await currentUserId(req);
  if (!userId) {
    res.status(401).json({ error: "auth required" });
    return;
  }
  const sql = db();
  const [u] = await sql<{ is_admin: boolean; privacy_settings: any }[]>`
    select is_admin, privacy_settings from users where id = ${userId}
  `;
  const consented = await hasActiveConsent(sql, userId, CONSENT_VERSION);

  res.status(200).json({
    user_id: userId,
    is_admin: u?.is_admin ?? false,
    consented,
    consent_version: CONSENT_VERSION,
    privacy_settings: u?.privacy_settings ?? {},
  });
}
