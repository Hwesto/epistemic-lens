import type { Choice, Split } from "../lib/types";

// The social split: "X% chose what you chose." Read constantly, so the counts
// are cached server-side (§10). Spoiler-free; shown after the user decides.
export function SocialSplit({
  choices,
  split,
  yourChoiceId,
}: {
  choices: Choice[];
  split: Split;
  yourChoiceId: string;
}) {
  return (
    <div className="space-y-2">
      {choices.map((c) => {
        const pct = Math.round(split[c.id] ?? 0);
        const mine = c.id === yourChoiceId;
        return (
          <div key={c.id} className="text-sm">
            <div className="mb-1 flex justify-between">
              <span className={mine ? "font-medium text-slate-100" : "text-slate-400"}>
                {c.label}
                {mine && " · you"}
              </span>
              <span className="tabular-nums text-slate-400">{pct}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded bg-slate-800">
              <div
                className={`h-full ${mine ? "bg-slate-100" : "bg-slate-600"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
