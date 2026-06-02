-- =============================================================================
-- framework_version: prior-v1
-- =============================================================================
-- This is the PRIOR, not validated truth (§3). It is adopted as vocabulary and
-- held loosely. The axes become *findings* only via confirmatory + exploratory
-- factor analysis on real behavioural data (§7). Versioned so it can change.
--
-- Content axes — the validated spine (MFQ-2): care, equality, proportionality,
-- loyalty, authority, purity. Purity is kept deliberately (it is highly
-- discriminating; cutting it must be a DATA decision, not a writing-difficulty one).
-- Unvalidated extras (honesty, autonomy) are flagged as such and probed lightly.
-- Scope and Process are MODIFIERS, not axes.
-- =============================================================================

insert into framework_versions (label, notes, definition) values (
  'prior-v1 (Opus-tagged MFQ-2)',
  'Initial prior. MFQ-2 six-axis spine + flagged unvalidated extras. Held loosely; expected to be confirmed/refined/replaced by factor analysis. Do NOT believe it yet.',
  '{
    "spine_axes": ["care", "equality", "proportionality", "loyalty", "authority", "purity"],
    "unvalidated_extras": ["honesty", "autonomy"],
    "modifiers": {
      "scope":   ["kin", "stranger", "group", "humanity"],
      "process": ["rule", "outcome"]
    },
    "relational_structure": "schwartz_circumplex: adjacent=compatible, opposite=trades-off",
    "loadings_rubric": {
      "range": [-1.0, 1.0],
      "convention": "positive = choosing this option expresses the axis; negative = it suppresses it",
      "note": "loadings are an Opus-proposed, human-confirmed PRIOR — not measured truth"
    },
    "epistemic_status": "pre-pilot prior; n~3; zero real data"
  }'::jsonb
);
