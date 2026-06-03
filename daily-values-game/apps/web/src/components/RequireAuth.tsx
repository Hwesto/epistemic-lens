import { useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";

// Route guard: requires a session, then ensures consent before any play.
// - no session  → /login
// - session, not consented, not already on /consent → /consent
//
// Dev-only bypass: when no Supabase project is configured (VITE_SUPABASE_URL
// unset), skip the session requirement and rely on the API's dev-user (the API
// server injects it in non-production). This mirrors the backend's dev bypass so
// the app is playable locally without standing up Supabase. Inert in production,
// where VITE_SUPABASE_URL is always set.
const DEV_NO_AUTH = !import.meta.env.VITE_SUPABASE_URL;

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const location = useLocation();
  const [consented, setConsented] = useState<boolean | null>(null);

  useEffect(() => {
    if (!session && !DEV_NO_AUTH) return;
    api
      .me()
      .then((m) => setConsented(m.consented))
      .catch(() => setConsented(false));
  }, [session]);

  if (loading) return <p className="py-12 text-center text-slate-500">…</p>;
  if (!session && !DEV_NO_AUTH) return <Navigate to="/login" replace />;

  // wait for consent status before deciding (avoids a flash of the game)
  if (consented === null) return <p className="py-12 text-center text-slate-500">…</p>;

  if (!consented && location.pathname !== "/consent") {
    return <Navigate to="/consent" replace />;
  }

  return <>{children}</>;
}
