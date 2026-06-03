import type { VercelRequest } from "@vercel/node";
import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";
import { db } from "./db";

// Auth resolves the user from a verified Supabase access token. PII (email, name)
// stays in Supabase; our DB stores only the auth subject (`sub`) as users.auth_id
// — the minimum identity needed (§10, docs/PRIVACY.md).
//
// Verification supports both Supabase signing modes:
//   * asymmetric (recommended) — JWKS at SUPABASE_URL/auth/v1/.well-known/jwks.json
//   * legacy HS256 shared secret — SUPABASE_JWT_SECRET
// In development only, an `x-auth-subject` header is accepted as a stand-in so
// the dev server can drive the loop without real tokens.

const IS_PROD = process.env.NODE_ENV === "production";

let _jwks: ReturnType<typeof createRemoteJWKSet> | null = null;
function jwks() {
  if (!_jwks) {
    const base = process.env.SUPABASE_URL;
    if (!base) return null;
    _jwks = createRemoteJWKSet(new URL(`${base}/auth/v1/.well-known/jwks.json`));
  }
  return _jwks;
}

// Verify a bearer token → return its `sub`, or null if it can't be verified.
async function subjectFromToken(token: string): Promise<string | null> {
  let payload: JWTPayload | null = null;

  const secret = process.env.SUPABASE_JWT_SECRET;
  if (secret) {
    try {
      ({ payload } = await jwtVerify(token, new TextEncoder().encode(secret)));
    } catch {
      payload = null;
    }
  }

  if (!payload) {
    const ks = jwks();
    if (ks) {
      try {
        ({ payload } = await jwtVerify(token, ks));
      } catch {
        payload = null;
      }
    }
  }

  return typeof payload?.sub === "string" ? payload.sub : null;
}

function bearer(req: VercelRequest): string | null {
  const h = req.headers["authorization"] as string | undefined;
  if (!h) return null;
  const [scheme, token] = h.split(" ");
  return scheme?.toLowerCase() === "bearer" && token ? token : null;
}

// Resolve the auth subject for a request (verified token, or dev shim).
// Frictionless anonymous mode (spec Phase 0: "bare page, no accounts"). When
// ALLOW_ANON=true, an `x-anon-id` header (a stable per-browser id) is accepted as
// the subject — no login. Anonymous users are auto-consented below.
const ALLOW_ANON = process.env.ALLOW_ANON === "true";

async function authSubject(req: VercelRequest): Promise<string | null> {
  const token = bearer(req);
  if (token) return subjectFromToken(token);
  const anon = req.headers["x-anon-id"];
  if (ALLOW_ANON && typeof anon === "string" && anon) return `anon:${anon}`;
  if (!IS_PROD) return (req.headers["x-auth-subject"] as string) ?? null;
  return null;
}

// Resolve (and lazily create) the internal user id for the request, or null.
export async function currentUserId(req: VercelRequest): Promise<string | null> {
  const sub = await authSubject(req);
  if (!sub) return null;

  const sql = db();
  const rows = await sql<{ id: string }[]>`
    insert into users (auth_id)
    values (${sub})
    on conflict (auth_id) do update set auth_id = excluded.auth_id
    returning id
  `;
  const id = rows[0]?.id ?? null;

  // Anonymous users carry no consent ceremony — auto-grant the active version so
  // the profiling guard passes (Phase 0). Real accounts go through /api/consent.
  if (id && sub.startsWith("anon:")) {
    await sql`
      insert into consents (user_id, version)
      select ${id}, ${CONSENT_VERSION}
      where not exists (
        select 1 from consents where user_id = ${id} and version = ${CONSENT_VERSION} and withdrawn_at is null
      )
    `;
  }
  return id;
}

// Like currentUserId, but additionally requires users.is_admin. Gates the
// content admin tool (replaces the old static x-admin-token).
export async function requireAdmin(req: VercelRequest): Promise<string | null> {
  const userId = await currentUserId(req);
  if (!userId) return null;

  const sql = db();
  const rows = await sql<{ is_admin: boolean }[]>`
    select is_admin from users where id = ${userId}
  `;
  return rows[0]?.is_admin ? userId : null;
}

// True if the user has granted (and not withdrawn) consent for `version`.
export async function hasActiveConsent(
  sql: any,
  userId: string,
  version: string
): Promise<boolean> {
  const rows = await sql<{ ok: boolean }[]>`
    select true as ok from consents
    where user_id = ${userId} and version = ${version} and withdrawn_at is null
    limit 1
  `;
  return rows.length > 0;
}

export const CONSENT_VERSION = process.env.CONSENT_VERSION ?? "v1";
