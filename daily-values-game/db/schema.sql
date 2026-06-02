-- =============================================================================
-- Daily Values-Mirror Game — core schema
-- =============================================================================
-- Design principles (from the infra spec, §4 & §10):
--   * choice_events is APPEND-ONLY and IMMUTABLE. The history IS the asset.
--   * Every set of loadings/scores is stamped with a framework_version so the
--     whole population can be re-scored from raw history when the prior changes.
--   * Anchors (is_anchor) are planted from day one and can NEVER be edited —
--     they are the measurement-invariance ruler for drift / test-retest.
--   * Gates carry rich experiment-design tags (edge / scope / framing / process /
--     exploratory) so the offline factor analysis is possible at all.
--
-- Target: Postgres 14+ (Supabase / Neon / Railway). Uses jsonb for loadings.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Framework versioning: the scoring rubric is a PRIOR, not truth. Versioned so
-- it can be confirmed / refined / replaced as data accrues, and so profiles can
-- be recomputed and frameworks compared.
-- ---------------------------------------------------------------------------
create table framework_versions (
  id           serial primary key,
  created_at   timestamptz not null default now(),
  label        text not null,                 -- e.g. 'prior-v1 (Opus-tagged MFQ-2)'
  notes        text,
  definition   jsonb not null                 -- axis set + loadings rubric in force
);

-- ---------------------------------------------------------------------------
-- Content: written by the pipeline (offline), read by everyone. One per day.
-- ---------------------------------------------------------------------------
create table stories (
  id            uuid primary key default gen_random_uuid(),
  publish_date  date unique not null,         -- exactly one shared story per day
  genre         text,
  title         text not null,
  body          text not null,
  art_url       text,
  audio_url     text,
  status        text not null default 'draft'
                check (status in ('draft','scheduled','live','archived')),
  created_at    timestamptz not null default now()
);

-- Each decision point = one staged conflict ("edge"). Rich design tags here.
create table gates (
  id               uuid primary key default gen_random_uuid(),
  story_id         uuid not null references stories(id) on delete cascade,
  sequence         int  not null,             -- order within the story
  body             text not null,
  art_url          text,
  is_terminal      boolean not null default false,

  -- EXPERIMENT-DESIGN TAGS -------------------------------------------------
  conflict_edge    text,                      -- e.g. 'care__honesty' (null if exploratory)
  scope_variant    text,                      -- 'kin'|'stranger'|'group'|'humanity'|...
  framing_variant  text,                      -- 'identifiable_victim'|'loss'|'gain'|'neutral'|...
  process_frame    text check (process_frame in ('rule','outcome') or process_frame is null),
  is_anchor        boolean not null default false,  -- fixed, never-edited invariance item
  anchor_id        text,                      -- links repeated instances of one anchor
  is_exploratory   boolean not null default false,  -- deliberately OUTSIDE the taxonomy

  created_at       timestamptz not null default now(),
  unique (story_id, sequence),
  -- an anchor must declare which anchor family it belongs to
  check (is_anchor = false or anchor_id is not null),
  -- a gate is either inside the taxonomy (has an edge) or exploratory, not both
  check (not (is_exploratory and conflict_edge is not null))
);

create index gates_story_idx        on gates(story_id);
create index gates_edge_idx         on gates(conflict_edge);
create index gates_anchor_idx       on gates(anchor_id) where is_anchor;

-- Selectable options at a gate. axis_loadings is a PRIOR stamped with the
-- framework_version that assigned it.
create table choices (
  id                    uuid primary key default gen_random_uuid(),
  gate_id               uuid not null references gates(id) on delete cascade,
  label                 text not null,
  next_gate_id          uuid references gates(id),       -- null => leads to terminal/end
  axis_loadings         jsonb not null default '{}'::jsonb,  -- {"care": 0.7, "honesty": -0.4}
  framework_version_id  int  not null references framework_versions(id),
  created_at            timestamptz not null default now()
);

create index choices_gate_idx on choices(gate_id);

-- ---------------------------------------------------------------------------
-- Users. Profile is PRIVATE by default (privacy is a legal necessity AND the
-- trust feature — see §10).
-- ---------------------------------------------------------------------------
create table users (
  id                uuid primary key default gen_random_uuid(),
  created_at        timestamptz not null default now(),
  display_name      text,
  auth_id           text unique,             -- maps to Supabase Auth / Clerk subject
  privacy_settings  jsonb not null default '{"profile_public": false}'::jsonb
);

-- ---------------------------------------------------------------------------
-- THE append-only log. Immutable. Tagged richly enough that analysis can
-- reconstruct full context (edge/scope/framing/anchor are derivable via gate_id).
-- response_ms captures gut-vs-reflective signal; rejected_choice_id is the
-- "would never" (most+least capture).
-- ---------------------------------------------------------------------------
create table choice_events (
  id                   bigserial primary key,
  user_id              uuid not null references users(id),
  story_id             uuid not null references stories(id),
  gate_id              uuid not null references gates(id),
  choice_id            uuid not null references choices(id),       -- option taken
  rejected_choice_id   uuid references choices(id),                -- the "would never"
  decided_at           timestamptz not null default now(),
  response_ms          int                                         -- time-to-decide
);

create index choice_events_user_idx  on choice_events(user_id);
create index choice_events_gate_idx  on choice_events(gate_id);
create index choice_events_story_idx on choice_events(story_id);

-- ---------------------------------------------------------------------------
-- Derived, recomputable from the log under a given framework_version.
-- The profile is a disposable VIEW of the immutable log — never the source.
-- ---------------------------------------------------------------------------
create table profiles (
  user_id               uuid not null references users(id),
  framework_version_id  int  not null references framework_versions(id),
  scored_at             timestamptz not null default now(),
  axis_scores           jsonb not null,   -- estimate per axis
  axis_confidence       jsonb not null,   -- error bars (rough in v1)
  consistency           jsonb not null,   -- principle vs context-dependent, per axis
  primary key (user_id, framework_version_id)
);

create table friendships (
  user_id     uuid not null references users(id),
  friend_id   uuid not null references users(id),
  status      text not null default 'pending'
              check (status in ('pending','accepted','blocked')),
  created_at  timestamptz not null default now(),
  primary key (user_id, friend_id),
  check (user_id <> friend_id)
);

-- The social split, cached counters. (Redis/KV in prod; this is the source of truth.)
create table daily_aggregates (
  story_id    uuid not null references stories(id),
  choice_id   uuid not null references choices(id),
  count       bigint not null default 0,
  primary key (story_id, choice_id)
);

-- ---------------------------------------------------------------------------
-- The experiment tracker — a VIEW over gates + choice_events. The gaps show
-- themselves: reps done per edge, which scope/framing variants have been hit.
-- ---------------------------------------------------------------------------
create view coverage as
select
  g.conflict_edge,
  count(distinct g.id)                                   as gates_authored,
  count(distinct g.story_id)                             as stories_touching,
  count(distinct g.scope_variant)
    filter (where g.scope_variant is not null)           as scope_variants_hit,
  count(distinct g.framing_variant)
    filter (where g.framing_variant is not null)         as framing_variants_hit,
  count(ce.id)                                           as choice_events_recorded,
  bool_or(g.is_anchor)                                   as has_anchor
from gates g
left join choice_events ce on ce.gate_id = g.id
where g.conflict_edge is not null
group by g.conflict_edge;

-- Anchor health: per anchor family, how many invariant re-runs and plays.
create view anchor_health as
select
  g.anchor_id,
  g.conflict_edge,
  count(distinct g.id)                                   as instances,
  count(distinct g.story_id)                             as distinct_dates,
  count(ce.id)                                           as plays
from gates g
left join choice_events ce on ce.gate_id = g.id
where g.is_anchor
group by g.anchor_id, g.conflict_edge;

-- =============================================================================
-- Immutability + anchor-protection enforcement (defence in depth; the admin
-- tool also blocks these, but the DB is the last line — see §10).
-- =============================================================================

-- choice_events is append-only: no UPDATE, no DELETE.
create or replace function forbid_mutation() returns trigger as $$
begin
  raise exception 'choice_events is append-only: % is not permitted', tg_op;
end;
$$ language plpgsql;

create trigger choice_events_no_update
  before update on choice_events
  for each row execute function forbid_mutation();

create trigger choice_events_no_delete
  before delete on choice_events
  for each row execute function forbid_mutation();

-- An anchor gate, once created, can never be edited — editing it silently
-- destroys its measurement-invariance value.
create or replace function forbid_anchor_edit() returns trigger as $$
begin
  if old.is_anchor then
    raise exception 'gate % is an anchor and is immutable (editing destroys invariance)', old.id;
  end if;
  return new;
end;
$$ language plpgsql;

create trigger gates_protect_anchors
  before update on gates
  for each row execute function forbid_anchor_edit();
