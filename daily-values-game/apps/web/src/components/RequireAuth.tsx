import { useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";

// Route guard: requires a session, then ensures consent before any play.
// - no session  → /login
// - session, not consented, not already on /consent → /consent
export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const location = useLocation();
  const [consented, setConsented] = useState<boolean | null>(null);

  useEffect(() => {
    if (!session) return;
    api
      .me()
      .then((m) => setConsented(m.consented))
      .catch(() => setConsented(false));
  }, [session]);

  if (loading) return <p className="py-12 text-center text-slate-500">…</p>;
  if (!session) return <Navigate to="/login" replace />;

  // wait for consent status before deciding (avoids a flash of the game)
  if (consented === null) return <p className="py-12 text-center text-slate-500">…</p>;

  if (!consented && location.pathname !== "/consent") {
    return <Navigate to="/consent" replace />;
  }

  return <>{children}</>;
}
