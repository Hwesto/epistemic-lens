import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../../src/db";
import { currentUserId } from "../../src/auth";
import { deleteAuthUser } from "../../src/supabaseAdmin";

// Account + data deletion — ANONYMISE & RETAIN (docs/PRIVACY.md).
//
// Reconciles the user's right to deletion with the append-only choice_events log:
//   1. delete the Supabase auth user (removes login + the PII it holds)
//   2. scrub the users row (null auth_id/display_name, set is_anonymized) — this
//      severs the link between the person and their events
//   3. delete derived/relational rows tied to the person (profiles, consents,
//      friendships)
//   4. LEAVE choice_events intact — they are now de-identified (no PII points to
//      the person), so the behavioural signal is retained for the science and the
//      append-only trigger is never touched.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "POST" && req.method !== "DELETE") {
    res.status(405).json({ error: "POST or DELETE" });
    return;
  }
  const userId = await currentUserId(req);
  if (!userId) {
    res.status(401).json({ error: "auth required" });
    return;
  }

  const sql = db();

  // capture the auth subject before we scrub it, to delete the Supabase user
  const [u] = await sql<{ auth_id: string | null }[]>`
    select auth_id from users where id = ${userId}
  `;
  if (u?.auth_id) await deleteAuthUser(u.auth_id);

  await sql.begin(async (tx) => {
    await tx`delete from profiles    where user_id = ${userId}`;
    await tx`delete from consents    where user_id = ${userId}`;
    await tx`delete from friendships where user_id = ${userId} or friend_id = ${userId}`;
    // scrub identity; choice_events keep pointing here but no PII remains
    await tx`
      update users
      set auth_id = null,
          display_name = null,
          privacy_settings = '{}'::jsonb,
          is_admin = false,
          is_anonymized = true
      where id = ${userId}
    `;
  });

  res.status(200).json({ ok: true, anonymized: true });
}
