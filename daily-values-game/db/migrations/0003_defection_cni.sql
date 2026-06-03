-- =============================================================================
-- Migration 0003 — defection (self-enhancement) + CNI process layer (framework v2)
-- =============================================================================
-- For databases already provisioned before these fields existed. Fresh installs
-- get these from db/schema.sql directly. Idempotent.
-- Apply:  psql "$DATABASE_URL" -f db/migrations/0003_defection_cni.sql
-- =============================================================================

-- v2: the Self-enhancement / defection layer (the costed self-interest option).
alter table choices add column if not exists is_defection boolean not null default false;

-- v2: CNI process layer — which route an answer represents on a [PROCESS] beat.
alter table choices add column if not exists cni_role text;
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'choices_cni_role_check'
  ) then
    alter table choices add constraint choices_cni_role_check
      check (cni_role in ('consequences','norms','inaction') or cni_role is null);
  end if;
end $$;

create index if not exists choices_defection_idx on choices(is_defection) where is_defection;

-- No defection option on an anchor gate (v2 design rule).
create or replace function forbid_defection_on_anchor() returns trigger as $$
begin
  if new.is_defection and exists (
    select 1 from gates g where g.id = new.gate_id and g.is_anchor
  ) then
    raise exception 'choice % is a defection option on an anchor gate — not permitted (anchors stay temptation-free)', new.id;
  end if;
  return new;
end;
$$ language plpgsql;

drop trigger if exists choices_no_defection_on_anchor on choices;
create trigger choices_no_defection_on_anchor
  before insert or update on choices
  for each row execute function forbid_defection_on_anchor();
