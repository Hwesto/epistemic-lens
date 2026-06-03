import { supabase } from "./supabase";
import type { CoverageEdge, AnchorRow, StoryListItem, StoryInput } from "./types";

const base = import.meta.env.VITE_API_BASE ?? "";

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { authorization: `Bearer ${token}` } : {};
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${base}${path}`, {
    method,
    headers: { "content-type": "application/json", ...(await authHeaders()) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw Object.assign(new Error(`${path} -> ${r.status}`), { status: r.status, detail });
  }
  return r.json() as Promise<T>;
}

export const api = {
  me: () => req<{ is_admin: boolean }>("GET", "/api/me"),

  coverage: () =>
    req<{ target_reps: number; edges: CoverageEdge[]; anchors: AnchorRow[] }>(
      "GET",
      "/api/admin/coverage"
    ),

  stories: (status?: string) =>
    req<StoryListItem[]>("GET", `/api/admin/stories${status ? `?status=${status}` : ""}`),

  story: (id: string) => req<any>("GET", `/api/admin/story?id=${id}`),

  createStory: (story: StoryInput) => req<any>("POST", "/api/admin/import-story", story),

  updateStory: (patch: {
    id: string;
    publish_date?: string;
    status?: string;
    gates?: { id: string; body: string }[];
  }) => req<any>("PATCH", "/api/admin/story", patch),
};
