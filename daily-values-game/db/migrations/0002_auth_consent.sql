-- =============================================================================
-- Migration 0002 — auth + consent
-- =============================================================================
-- For databases already provisioned with schema.sql before these fields existed.
-- Fresh installs get these from db/schema.sql directly. Idempotent.
-- Apply:  psql "$DATABASE_URL" -f db/migrations/0002_auth_consent.sql
-- =============================================================================

alter table users add column if not exists is_admin      boolean not null default false;
alter table users add column if not exists is_anonymized boolean not null default false;

create table if not exists consents (
  id            bigserial primary key,
  user_id       uuid not null references users(id),
  version       text not null,
  granted_at    timestamptz not null default now(),
  withdrawn_at  timestamptz
);

create index if not exists consents_user_idx on consents(user_id);
