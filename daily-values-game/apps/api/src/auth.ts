import type { VercelRequest } from "@vercel/node";
import { db } from "./db";

// v1: resolve the user from the Supabase/Clerk session. Stubbed to read a
// verified subject from a header set by the auth middleware/edge. Replace with
// real JWT verification before launch.
export async function currentUserId(req: VercelRequest): Promise<string | null> {
  const authId = (req.headers["x-auth-subject"] as string) ?? null;
  if (!authId) return null;

  const sql = db();
  const rows = await sql<{ id: string }[]>`
    insert into users (auth_id)
    values (${authId})
    on conflict (auth_id) do update set auth_id = excluded.auth_id
    returning id
  `;
  return rows[0]?.id ?? null;
}
