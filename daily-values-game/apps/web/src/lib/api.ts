import type { Story, Split, Profile } from "./types";

// Thin client over the serverless API. Today's story is served from cache/CDN;
// choices are light writes to the append-only log.
const base = import.meta.env.VITE_API_BASE ?? "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${base}${path}`, { credentials: "include" });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json() as Promise<T>;
}

export const api = {
  today: () => get<Story>("/api/today"),

  split: (storyId: string) => get<Split>(`/api/split?story=${storyId}`),

  profile: () => get<Profile>("/api/profile"),

  // Record one decision. response_ms is the gut-vs-reflective signal (§4).
  recordChoice: async (input: {
    storyId: string;
    gateId: string;
    choiceId: string;
    rejectedChoiceId?: string;
    responseMs: number;
  }) => {
    const r = await fetch(`${base}/api/choice`, {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!r.ok) throw new Error(`/api/choice -> ${r.status}`);
    return r.json();
  },

  // URL of the server-rendered, spoiler-free share card PNG (§10, growth engine).
  // The card shows the date + title and the axis legend — never an outcome.
  shareCardUrl: (title: string, date: string) =>
    `${base}/api/share-card?title=${encodeURIComponent(title)}&date=${encodeURIComponent(date)}`,
};
