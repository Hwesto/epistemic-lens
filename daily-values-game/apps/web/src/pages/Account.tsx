import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

// Account & privacy controls (§10): private-by-default toggle, data export, and
// account+data deletion (anonymise & retain — your choices live on de-identified).
export default function Account() {
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const [profilePublic, setProfilePublic] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function togglePublic() {
    const next = !profilePublic;
    setProfilePublic(next);
    await api.setProfilePublic(next);
  }

  async function exportData() {
    const data = await api.exportData();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "my-values-data.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function deleteAccount() {
    setBusy(true);
    try {
      await api.deleteAccount();
      await signOut();
      navigate("/login", { replace: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8 py-6">
      <section className="space-y-2">
        <h2 className="text-base font-semibold">Privacy</h2>
        <label className="flex items-center justify-between text-sm text-slate-300">
          <span>Make my profile shareable</span>
          <input type="checkbox" checked={profilePublic} onChange={togglePublic} />
        </label>
        <p className="text-xs text-slate-500">
          Off by default. Your read stays private unless you turn this on.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold">Your data</h2>
        <button
          onClick={exportData}
          className="w-full rounded-xl border border-slate-700 px-4 py-3 text-sm hover:border-slate-400"
        >
          Export my data (JSON)
        </button>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-red-400">Delete account</h2>
        <p className="text-xs text-slate-500">
          Removes your login and personal details. Your individual choices are kept
          only in de-identified form, with nothing linking them back to you.
        </p>
        {!confirming ? (
          <button
            onClick={() => setConfirming(true)}
            className="w-full rounded-xl border border-red-900 px-4 py-3 text-sm text-red-400 hover:border-red-500"
          >
            Delete my account
          </button>
        ) : (
          <div className="space-y-2">
            <p className="text-sm text-slate-300">This can’t be undone. Are you sure?</p>
            <div className="flex gap-2">
              <button
                disabled={busy}
                onClick={deleteAccount}
                className="flex-1 rounded-xl bg-red-600 px-4 py-3 text-sm font-medium text-white disabled:opacity-50"
              >
                Yes, delete
              </button>
              <button
                onClick={() => setConfirming(false)}
                className="flex-1 rounded-xl border border-slate-700 px-4 py-3 text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
