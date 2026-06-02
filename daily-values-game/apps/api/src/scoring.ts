// v1 scoring: turn the PRIOR loadings into an axis read. This is deliberately
// simple — a weighted mean of the loadings on the options a user actually chose,
// under one framework_version. It is NOT calibrated measurement; confidence is a
// rough function of how many relevant events we have (§9). Phase 2 replaces this
// with IRT/factor analysis run over the immutable log (§7).

export const SPINE_AXES = [
  "care",
  "equality",
  "proportionality",
  "loyalty",
  "authority",
  "purity",
] as const;
export type Axis = (typeof SPINE_AXES)[number];

export interface ScoredEvent {
  // the loadings of the option the user TOOK
  loadings: Record<string, number>;
}

export interface AxisRead {
  axis: Axis;
  score: number; // -1..1
  confidence: number; // 0..1 (rough)
}

export function scoreProfile(events: ScoredEvent[]): AxisRead[] {
  return SPINE_AXES.map((axis) => {
    const vals = events
      .map((e) => e.loadings[axis])
      .filter((v): v is number => typeof v === "number");

    const n = vals.length;
    const mean = n ? vals.reduce((a, b) => a + b, 0) / n : 0;

    // Rough confidence: saturates with evidence. ~10 relevant events ≈ 0.6.
    // Honest hedge: this is a heuristic, not a calibrated CI.
    const confidence = n === 0 ? 0 : Math.min(0.85, 1 - 1 / Math.sqrt(n + 1));

    return { axis, score: clamp(mean, -1, 1), confidence: round(confidence) };
  });
}

// The honest hedge surfaced with every reveal (§9). Keep it front-and-centre:
// a confident reveal feels true whether earned or not (§10).
export const REVEAL_HEDGE =
  "This is your read so far — a reflection of the choices you've made in the " +
  "game, not a verdict on who you are. The way we read these choices is still " +
  "being tested against real data, so hold it lightly. It gets sharper the more " +
  "you play.";

function clamp(x: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, x));
}
function round(x: number) {
  return Math.round(x * 100) / 100;
}
