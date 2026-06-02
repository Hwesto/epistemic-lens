import type { Profile } from "../lib/types";
import { AXIS_COLOR, AXIS_LABEL } from "../lib/axes";

// The reveal is HONESTLY-HEDGED, Forer-grade in v1 (§9). It is framed as
// "your read so far", a game — NOT a verdict. It becomes real measurement in
// Phase 2 from the log this very session is helping to gather.
export function Reveal({ profile }: { profile: Profile }) {
  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold">Your read so far</h2>

      <div className="space-y-2">
        {profile.axes.map((a) => {
          // map -1..1 to a 0..100 bar centred at 50
          const pct = Math.round((a.score + 1) * 50);
          return (
            <div key={a.axis} className="text-sm">
              <div className="mb-1 flex justify-between text-slate-300">
                <span>{AXIS_LABEL[a.axis]}</span>
                <span className="tabular-nums text-slate-500">
                  ±{Math.round((1 - a.confidence) * 100)}%
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded bg-slate-800">
                <div
                  className="h-full"
                  style={{ width: `${pct}%`, backgroundColor: AXIS_COLOR[a.axis] }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <p className="rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-400">
        {profile.hedge}
      </p>
    </div>
  );
}
