import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Story, Gate as GateT, Choice, Split } from "../lib/types";
import { Gate } from "../components/Gate";
import { SocialSplit } from "../components/SocialSplit";
import { ShareCard } from "../components/ShareCard";

type Phase = "loading" | "reading" | "playing" | "done" | "error";

export default function Today() {
  const [story, setStory] = useState<Story | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [gate, setGate] = useState<GateT | null>(null);
  const [split, setSplit] = useState<Split>({});
  const [lastChoice, setLastChoice] = useState<Choice | null>(null);

  useEffect(() => {
    api
      .today()
      .then((s) => {
        setStory(s);
        setGate(s.gates.find((g) => g.sequence === 1) ?? null);
        setPhase("reading");
      })
      .catch(() => setPhase("error"));
  }, []);

  async function handleDecide(input: {
    gate: GateT;
    choice: Choice;
    rejected?: Choice;
    responseMs: number;
  }) {
    if (!story) return;
    setLastChoice(input.choice);
    await api.recordChoice({
      storyId: story.id,
      gateId: input.gate.id,
      choiceId: input.choice.id,
      rejectedChoiceId: input.rejected?.id,
      responseMs: input.responseMs,
    });
    // Reveal the social split for this gate, then advance or finish.
    setSplit(await api.split(story.id));

    const nextId = input.choice.next_gate_id;
    const next = nextId ? story.gates.find((g) => g.id === nextId) ?? null : null;
    if (next && !input.gate.is_terminal) {
      // brief pause to show the split is handled by the page below
      setGate(next);
    } else {
      setPhase("done");
    }
  }

  if (phase === "loading") return <p className="py-12 text-slate-500">Loading today…</p>;
  if (phase === "error" || !story)
    return <p className="py-12 text-slate-500">No story today. Check back tomorrow.</p>;

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-wide text-slate-500">
          {story.publish_date} · {story.genre}
        </p>
        <h1 className="mt-1 text-2xl font-semibold">{story.title}</h1>
        <p className="mt-3 leading-relaxed text-slate-300">{story.body}</p>
      </div>

      {phase === "reading" && gate && (
        <button
          onClick={() => setPhase("playing")}
          className="w-full rounded-xl bg-slate-100 px-4 py-3 font-medium text-slate-900"
        >
          Begin
        </button>
      )}

      {phase === "playing" && gate && <Gate gate={gate} onDecide={handleDecide} />}

      {lastChoice && gate && (
        <SocialSplit choices={gate.choices} split={split} yourChoiceId={lastChoice.id} />
      )}

      {phase === "done" && (
        <div className="space-y-6 border-t border-slate-800 pt-6">
          <ShareCard storyId={story.id} title={story.title} />
        </div>
      )}
    </div>
  );
}
