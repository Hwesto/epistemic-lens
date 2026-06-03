-- =============================================================================
-- Migration 0004 — deterministic fixed option order (choices.position)
-- =============================================================================
-- Options are shown in a FIXED order, identical for every player (the shared
-- artifact: split / friend-diff / share card). Today the choice queries have no
-- ORDER BY, so the order isn't actually guaranteed. This makes the authored order
-- explicit and deterministic.
--
-- For databases already provisioned before this column existed. Fresh installs
-- get it from db/schema.sql. Idempotent.
-- Apply:  psql "$DATABASE_URL" -f db/migrations/0004_choice_position.sql
-- =============================================================================

alter table choices add column if not exists position smallint not null default 0;

-- Backfill existing rows deterministically (0-based per gate) before enforcing
-- uniqueness — existing rows all default to 0 and would otherwise collide.
update choices c
set position = sub.rn
from (
  select id, (row_number() over (partition by gate_id order by created_at, id) - 1) as rn
  from choices
) sub
where c.id = sub.id;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'choices_gate_id_position_key'
  ) then
    alter table choices add constraint choices_gate_id_position_key unique (gate_id, position);
  end if;
end $$;
