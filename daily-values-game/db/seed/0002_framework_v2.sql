-- =============================================================================
-- framework_version: prior-v2  (MIRROR v2)
-- =============================================================================
-- Appended, never editing v1 (the log can always be re-scored under any version,
-- and versions stay comparable). New imports/scoring use the latest version.
--
-- What v2 adds over v1:
--   * Self-enhancement — the DEFECTION axis. Measured via choices.is_defection
--     (the costed self-interest option) + a `self_enhancement` key in
--     axis_loadings. Measures *whether you act when it costs you*.
--   * CNI process layer — Consequences / Norms / Inaction sensitivity. Measured
--     via gates.process_frame (rule|outcome) + choices.cni_role
--     (consequences|norms|inaction). Measures *how* you decide.
--
-- Held loosely, as ever: Honesty and Autonomy carry many v2 edges but remain
-- UNVALIDATED EXTRAS — probed, not baked in as proven axes. The factor analysis
-- decides whether they earn axis status. Spine six unchanged.
-- =============================================================================

insert into framework_versions (label, notes, definition) values (
  'prior-v2 (MIRROR: +self-enhancement, +CNI)',
  'Adds the defection axis (self_enhancement) and the CNI process layer to prior-v1. Still a PRIOR, not validated truth. CNI gives signal; true C/N/I parameter extraction needs matched crossed variants of the anchors over time, not claimed here.',
  '{
    "spine_axes": ["care", "equality", "proportionality", "loyalty", "authority", "purity"],
    "unvalidated_extras": ["honesty", "autonomy"],
    "defection_axis": {
      "name": "self_enhancement",
      "measured_via": "choices.is_defection (the costed self-interest option) + self_enhancement loading",
      "rule": "never on an anchor gate (a costed temptation would shift an anchor''s meaning)",
      "note": "a defection option without a real, named cost to the chooser measures nothing"
    },
    "process_layer_cni": {
      "components": ["consequences", "norms", "inaction"],
      "measured_via": "gates.process_frame (rule|outcome) + choices.cni_role (consequences|norms|inaction)",
      "honesty": "signal only at n stories; C/N/I parameter extraction needs matched crossed anchor variants over time"
    },
    "modifiers": {
      "scope":   ["kin", "stranger", "group", "humanity", "future"],
      "process": ["rule", "outcome"]
    },
    "relational_structure": "schwartz_circumplex: adjacent=compatible, opposite=trades-off",
    "format": "4 answers per beat; ~80% virtue-vs-virtue; ~20% defection beats (3 virtues + 1 costed self-interest)",
    "loadings_rubric": {
      "range": [-1.0, 1.0],
      "convention": "positive = choosing this option expresses the axis; negative = it suppresses it",
      "note": "loadings remain an Opus-proposed, human-confirmed PRIOR — not measured truth"
    },
    "epistemic_status": "pre-pilot prior; held loosely; expected to be confirmed/refined/replaced by factor analysis"
  }'::jsonb
);
