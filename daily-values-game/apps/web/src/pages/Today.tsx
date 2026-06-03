import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { Story, Gate as GateT, Choice, Split } from "../lib/types";
import { Gate } from "../components/Gate";
import { SocialSplit } from "../components/SocialSplit";
import { ShareCard } from "../components/ShareCard";

type Phase = "loading" | "reading" | "playing" | "decided" | "done" | "error";

export default function Today() {
  const navigate = useNavigate();
  const [story, setStory] = useState<Story | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [gate, setGate] = useState<GateT | null>(null);
  const [split, setSplit] = useState<Split>({});
  // the gate + choice the user just decided — drives the split reveal so it
  // always matches the gate that was answered (not the next one).
  const [decided, setDecided] = useState<{ gate: GateT; choice: Choice } | null>(null);
  // remembered narration: the lead-in for the gate now on screen, set from the
  // choice that led here (acknowledge, don't evaluate). Null on the first gate.
  const [leadIn, setLeadIn] = useState<string | null>(null);

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
    try {
      await api.recordChoice({
        storyId: story.id,
        gateId: input.gate.id,
        choiceId: input.choice.id,
        rejectedChoiceId: input.rejected?.id,
        responseMs: input.responseMs,
      });
    } catch (e: any) {
      if (e?.detail?.error === "consent_required") {
        navigate("/consent");
        return;
      }
      throw e;
    }
    setSplit(await api.split(story.id));
    setDecided({ gate: input.gate, choice: input.choice });
    setPhase("decided");
  }

  function advance() {
    if (!story || !decided) return;
    const nextId = decided.choice.next_gate_id;
    const next = nextId ? story.gates.find((g) => g.id === nextId) ?? null : null;
    if (next && !decided.gate.is_terminal) {
      // carry the remembered narration from the choice into the next beat
      setLeadIn(decided.choice.lead_in_text ?? null);
      setGate(next);
      setPhase("playing");
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

      {phase === "playing" && gate && (
        <>
          {leadIn && (
            <p className="leading-relaxed text-slate-400 italic">{leadIn}</p>
          )}
          <Gate gate={gate} onDecide={handleDecide} />
        </>
      )}

      {phase === "decided" && decided && (
        <div className="space-y-4">
          <p className="text-lg leading-relaxed">{decided.gate.body}</p>
          <SocialSplit
            choices={decided.gate.choices}
            split={split}
            yourChoiceId={decided.choice.id}
          />
          <button
            onClick={advance}
            className="w-full rounded-xl bg-slate-100 px-4 py-3 font-medium text-slate-900"
          >
            Continue
          </button>
        </div>
      )}

      {phase === "done" && (
        <div className="space-y-6 border-t border-slate-800 pt-6">
          <ShareCard storyId={story.id} title={story.title} date={story.publish_date} />
        </div>
      )}
    </div>
  );
}
