// Canonical axis list = the PRIOR spine (MFQ-2). Held loosely (§3).
// Keep in sync with db/seed/0001_framework_v1.sql and api/src/lib/axes.ts.
// Purity is kept deliberately — cutting it must be a data decision (§3).
export const SPINE_AXES = [
  "care",
  "equality",
  "proportionality",
  "loyalty",
  "authority",
  "purity",
] as const;

export type Axis = (typeof SPINE_AXES)[number];

// Matches tailwind.config.js and the server-rendered share card legend (§10).
export const AXIS_COLOR: Record<Axis, string> = {
  care: "#ef4444",
  equality: "#f59e0b",
  proportionality: "#eab308",
  loyalty: "#22c55e",
  authority: "#3b82f6",
  purity: "#a855f7",
};

export const AXIS_LABEL: Record<Axis, string> = {
  care: "Care",
  equality: "Equality",
  proportionality: "Proportionality",
  loyalty: "Loyalty",
  authority: "Authority",
  purity: "Purity",
};
