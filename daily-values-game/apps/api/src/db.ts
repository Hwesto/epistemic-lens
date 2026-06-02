import postgres from "postgres";

// Single connection factory. In serverless, reuse across warm invocations.
// DATABASE_URL points at Supabase / Neon / Railway Postgres.
let _sql: ReturnType<typeof postgres> | null = null;

export function db() {
  if (!_sql) {
    const url = process.env.DATABASE_URL;
    if (!url) throw new Error("DATABASE_URL is not set");
    _sql = postgres(url, { max: 1, idle_timeout: 20 });
  }
  return _sql;
}
