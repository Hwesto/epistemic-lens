import { createClient } from "@supabase/supabase-js";

// Same Supabase project as the public app — admin access is gated by the
// is_admin flag server-side, not by a separate auth system.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const supabase = createClient(url ?? "http://localhost", anonKey ?? "anon");
