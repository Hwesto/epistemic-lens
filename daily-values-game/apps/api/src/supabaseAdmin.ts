import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Service-role client, used only for privileged auth operations (deleting the
// auth user on account deletion). NEVER expose the service key to clients.
// If the env isn't configured (e.g. local dev), the helpers no-op with a warning
// so the rest of the deletion flow still runs.

let _client: SupabaseClient | null = null;
function admin(): SupabaseClient | null {
  if (_client) return _client;
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  _client = createClient(url, key, { auth: { persistSession: false } });
  return _client;
}

// Delete the Supabase auth user (the PII holder + login). Returns false (with a
// warning) when not configured, so callers can proceed with the DB-side scrub.
export async function deleteAuthUser(authSub: string): Promise<boolean> {
  const client = admin();
  if (!client) {
    console.warn(
      "[supabaseAdmin] SUPABASE_SERVICE_ROLE_KEY not set — skipping auth user delete"
    );
    return false;
  }
  const { error } = await client.auth.admin.deleteUser(authSub);
  if (error) {
    console.error("[supabaseAdmin] deleteUser failed:", error.message);
    return false;
  }
  return true;
}
