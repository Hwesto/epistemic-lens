import { useState } from "react";
import { useAuth } from "../lib/auth";

// Email magic-link sign-in. Social providers can be added via
// supabase.auth.signInWithOAuth — kept to email for v1.
export default function Login() {
  const { signInWithEmail } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const { error } = await signInWithEmail(email);
    if (error) setErr(error);
    else setSent(true);
  }

  if (sent)
    return (
      <div className="py-16 text-center text-slate-300">
        <p className="text-lg">Check your email.</p>
        <p className="mt-2 text-sm text-slate-500">We sent a sign-in link to {email}.</p>
      </div>
    );

  return (
    <form onSubmit={submit} className="space-y-4 py-12">
      <div>
        <h1 className="text-2xl font-semibold">Daily Values</h1>
        <p className="mt-2 text-sm text-slate-400">
          One shared story a day. Sign in to keep your private read.
        </p>
      </div>
      <input
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        className="w-full rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 outline-none focus:border-slate-400"
      />
      {err && <p className="text-sm text-red-400">{err}</p>}
      <button className="w-full rounded-xl bg-slate-100 px-4 py-3 font-medium text-slate-900">
        Send sign-in link
      </button>
    </form>
  );
}
