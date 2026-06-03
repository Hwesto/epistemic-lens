import { createClient } from "@supabase/supabase-js";

// Anon (public) Supabase client. Holds the user session in the browser; the
// access token is attached to API calls (see lib/api.ts). Never put the service
// role key here.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

if (!url || !anonKey) {
  // Not fatal in local dev (the dev API server bypasses auth), but the login
  // flow won't work until these are set.
  console.warn("VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY not set — login disabled");
}

export const supabase = createClient(url ?? "http://localhost", anonKey ?? "anon");
