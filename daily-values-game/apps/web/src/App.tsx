import { Link, Outlet } from "react-router-dom";
import { useAuth } from "./lib/auth";

export default function App() {
  const { signOut } = useAuth();
  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col px-4">
      <header className="flex items-center justify-between py-4">
        <Link to="/" className="text-lg font-semibold tracking-tight">
          Daily&nbsp;Values
        </Link>
        <nav className="flex items-center gap-4 text-sm text-slate-400">
          <Link to="/profile" className="hover:text-slate-100">
            Your read
          </Link>
          <Link to="/account" className="hover:text-slate-100">
            Account
          </Link>
          <button onClick={signOut} className="hover:text-slate-100">
            Sign out
          </button>
        </nav>
      </header>
      <main className="flex-1 pb-16">
        <Outlet />
      </main>
      <footer className="py-6 text-center text-xs text-slate-600">
        Private by default. Your choices are yours.
      </footer>
    </div>
  );
}
