import type { Story, Split, Profile } from "./types";
import { supabase } from "./supabase";

// Thin client over the serverless API. Today's story is served from cache/CDN;
// choices are light writes to the append-only log.
const base = import.meta.env.VITE_API_BASE ?? "";

// Attach the Supabase access token as a Bearer header (verified server-side).
async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { authorization: `Bearer ${token}` } : {};
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${base}${path}`, { headers: await authHeaders() });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json() as Promise<T>;
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${base}${path}`, {
    method,
    headers: { "content-type": "application/json", ...(await authHeaders()) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    // surface a structured error code (e.g. consent_required) when present
    const detail = await r.json().catch(() => ({}));
    throw Object.assign(new Error(`${path} -> ${r.status}`), { status: r.status, detail });
  }
  return r.json() as Promise<T>;
}

export interface Me {
  user_id: string;
  is_admin: boolean;
  consented: boolean;
  consent_version: string;
  privacy_settings: { profile_public?: boolean };
}

export const api = {
  me: () => get<Me>("/api/me"),

  today: () => get<Story>("/api/today"),

  split: (storyId: string) => get<Split>(`/api/split?story=${storyId}`),

  profile: () => get<Profile>("/api/profile"),

  // Record one decision. response_ms is the gut-vs-reflective signal (§4).
  recordChoice: (input: {
    storyId: string;
    gateId: string;
    choiceId: string;
    rejectedChoiceId?: string;
    responseMs: number;
  }) => send("POST", "/api/choice", input),

  // Privacy / account (§10).
  recordConsent: () => send("POST", "/api/consent"),
  exportData: () => get("/api/account/export"),
  deleteAccount: () => send("POST", "/api/account/delete"),
  setProfilePublic: (profile_public: boolean) =>
    send("POST", "/api/account/privacy", { profile_public }),

  // URL of the server-rendered, spoiler-free share card PNG (§10, growth engine).
  // The card shows the date + title and the axis legend — never an outcome.
  shareCardUrl: (title: string, date: string) =>
    `${base}/api/share-card?title=${encodeURIComponent(title)}&date=${encodeURIComponent(date)}`,
};
