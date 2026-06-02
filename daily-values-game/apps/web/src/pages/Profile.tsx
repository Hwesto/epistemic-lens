import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Profile as ProfileT } from "../lib/types";
import { Reveal } from "../components/Reveal";

export default function Profile() {
  const [profile, setProfile] = useState<ProfileT | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.profile().then(setProfile).catch(() => setErr(true));
  }, []);

  if (err)
    return (
      <p className="py-12 text-slate-500">
        Play a few days first — your read builds from your choices.
      </p>
    );
  if (!profile) return <p className="py-12 text-slate-500">Deriving your read…</p>;

  return (
    <div className="py-2">
      <Reveal profile={profile} />
    </div>
  );
}
