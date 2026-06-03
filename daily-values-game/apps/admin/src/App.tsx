import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { api } from "./lib/api";
import { useAuth } from "./lib/auth";

type Access = "checking" | "anon" | "forbidden" | "ok";

// Admin gate: access is decided by the server (/api/me → is_admin). In local dev
// the API bypass returns an admin dev-user, so no sign-in is needed.
export default function App() {
  const { signInWithEmail, signOut } = useAuth();
  const [access, setAccess] = useState<Access>("checking");
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  useEffect(() => {
    api
      .me()
      .then((m) => setAccess(m.is_admin ? "ok" : "forbidden"))
      .catch((e) => setAccess(e?.status === 401 ? "anon" : "forbidden"));
  }, []);

  if (access === "checking") return <Centered>Checking access…</Centered>;

  if (access === "anon")
    return (
      <Centered>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            await signInWithEmail(email);
            setSent(true);
          }}
          className="w-full max-w-sm space-y-3"
        >
          <h1 className="text-lg font-semibold">Admin sign-in</h1>
          {sent ? (
            <p className="text-sm text-slate-400">Check your email for a sign-in link.</p>
          ) : (
            <>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2"
              />
              <button className="w-full rounded-lg bg-slate-100 px-3 py-2 font-medium text-slate-900">
                Send link
              </button>
            </>
          )}
        </form>
      </Centered>
    );

  if (access === "forbidden")
    return (
      <Centered>
        <div className="text-center">
          <p className="text-slate-300">Not authorised.</p>
          <button onClick={signOut} className="mt-3 text-sm text-slate-500 hover:text-slate-300">
            Sign out
          </button>
        </div>
      </Centered>
    );

  return (
    <div className="mx-auto max-w-5xl px-6">
      <header className="flex items-center justify-between border-b border-slate-800 py-4">
        <Link to="/" className="font-semibold">
          DVG Admin
        </Link>
        <nav className="flex gap-4 text-sm text-slate-400">
          <Tab to="/">Coverage</Tab>
          <Tab to="/stories">Stories</Tab>
          <Tab to="/new">New story</Tab>
          <button onClick={signOut} className="hover:text-slate-100">
            Sign out
          </button>
        </nav>
      </header>
      <main className="py-6">
        <Outlet />
      </main>
    </div>
  );
}

function Tab({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) => (isActive ? "text-slate-100" : "hover:text-slate-100")}
    >
      {children}
    </NavLink>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6 text-slate-400">
      {children}
    </div>
  );
}
