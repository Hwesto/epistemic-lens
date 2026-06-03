// Canonical axis list (the PRIOR spine). Keep in sync with
// apps/web/src/lib/axes.ts and db/seed/0001_framework_v1.sql.
export const SPINE_AXES = [
  "care",
  "equality",
  "proportionality",
  "loyalty",
  "authority",
  "purity",
] as const;

export type Axis = (typeof SPINE_AXES)[number];

// Modifier vocabularies for the tag fields (from the framework prior).
export const SCOPE_VARIANTS = ["kin", "stranger", "group", "humanity"];
export const FRAMING_VARIANTS = ["identifiable_victim", "loss", "gain", "neutral"];
export const PROCESS_FRAMES = ["rule", "outcome"];
