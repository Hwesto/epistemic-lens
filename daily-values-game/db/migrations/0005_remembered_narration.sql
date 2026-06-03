-- =============================================================================
-- Migration 0005 — remembered narration (branch-and-bottleneck in prose)
-- =============================================================================
-- choices.lead_in_text: shown when a player arrives at this choice's next_gate
-- BECAUSE they took this choice. Options + dilemma text stay invariant; only this
-- connective tissue varies by path. It may acknowledge what happened, never
-- evaluate it. NEVER set when the target gate is an anchor (breaks invariance).
--
-- For databases provisioned before this column existed. Fresh installs get it
-- from db/schema.sql. Idempotent.
-- Apply:  psql "$DATABASE_URL" -f db/migrations/0005_remembered_narration.sql
-- =============================================================================

alter table choices add column if not exists lead_in_text text;

-- No remembered narration into an anchor gate (protects anchor path-invariance).
create or replace function forbid_leadin_into_anchor() returns trigger as $$
begin
  if new.lead_in_text is not null and new.next_gate_id is not null and exists (
    select 1 from gates g where g.id = new.next_gate_id and g.is_anchor
  ) then
    raise exception 'choice % carries a lead-in into an anchor gate — not permitted (anchors stay path-invariant)', new.id;
  end if;
  return new;
end;
$$ language plpgsql;

drop trigger if exists choices_no_leadin_into_anchor on choices;
create trigger choices_no_leadin_into_anchor
  before insert or update on choices
  for each row execute function forbid_leadin_into_anchor();
