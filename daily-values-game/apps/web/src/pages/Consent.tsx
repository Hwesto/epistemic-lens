import { useState } from "react";
import { api } from "../lib/api";

// Explicit, logged consent before any profiling (§10). Shown after sign-in until
// granted; the server also blocks /api/choice without it.
export default function Consent() {
  const [busy, setBusy] = useState(false);

  async function agree() {
    setBusy(true);
    try {
      await api.recordConsent();
      // Full reload so the route guard re-fetches consent status (a SPA navigate
      // would keep the guard's stale consented=false and bounce back here).
      window.location.assign("/");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5 py-10">
      <h1 className="text-2xl font-semibold">Before you play</h1>
      <div className="space-y-3 text-sm leading-relaxed text-slate-300">
        <p>
          This is a game about moral choices. As you play, we record the choices you
          make to build a private “read” on your values, just for you.
        </p>
        <p>
          Values data can be sensitive. Your profile is{" "}
          <strong>private by default</strong> and yours to export or delete at any
          time. We store the minimum needed to run the game.
        </p>
        <p className="text-slate-400">
          By continuing you consent to us recording your in-game choices for this
          purpose. You can withdraw and delete your data from your account page.
        </p>
      </div>
      <button
        disabled={busy}
        onClick={agree}
        className="w-full rounded-xl bg-slate-100 px-4 py-3 font-medium text-slate-900 disabled:opacity-50"
      >
        I understand — let’s play
      </button>
    </div>
  );
}
