import { useEffect, useRef, useState } from "react";
import type { Gate as GateT, Choice } from "../lib/types";

// Renders one staged conflict. Captures the chosen option, the rejected option
// (the "would never" — most+least capture), and response_ms (gut vs reflective).
export function Gate({
  gate,
  onDecide,
}: {
  gate: GateT;
  onDecide: (input: {
    gate: GateT;
    choice: Choice;
    rejected?: Choice;
    responseMs: number;
  }) => void;
}) {
  const shownAt = useRef<number>(Date.now());
  const [picked, setPicked] = useState<Choice | null>(null);

  useEffect(() => {
    shownAt.current = Date.now();
    setPicked(null);
  }, [gate.id]);

  function choose(choice: Choice) {
    const responseMs = Date.now() - shownAt.current;
    // With a binary fork the rejected option is the other one. With 3–4 options
    // we'd prompt for the explicit "would never"; kept simple here.
    const rejected =
      gate.choices.length === 2
        ? gate.choices.find((c) => c.id !== choice.id)
        : undefined;
    setPicked(choice);
    onDecide({ gate, choice, rejected, responseMs });
  }

  return (
    <section className="space-y-4">
      <p className="text-lg leading-relaxed">{gate.body}</p>
      <div className="grid gap-3">
        {gate.choices.map((c) => (
          <button
            key={c.id}
            disabled={picked !== null}
            onClick={() => choose(c)}
            className={`rounded-xl border px-4 py-3 text-left transition
              ${
                picked?.id === c.id
                  ? "border-slate-100 bg-slate-800"
                  : "border-slate-700 hover:border-slate-400 hover:bg-slate-900"
              }
              ${picked && picked.id !== c.id ? "opacity-40" : ""}`}
          >
            {c.label}
          </button>
        ))}
      </div>
    </section>
  );
}
