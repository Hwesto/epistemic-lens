import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { SCOPE_VARIANTS, FRAMING_VARIANTS, PROCESS_FRAMES } from "../lib/axes";
import type { GateInput, StoryInput } from "../lib/types";

// The CURATE → TAG → PREVIEW → SCHEDULE surface (§6).
//   /new        → compose a new story (manual DRAFT: paste AI text, then curate)
//   /story/:id  → view/schedule an existing story; edit non-anchor gate bodies.
//                 Anchor gates are immutable (locked here; DB trigger backstops).
export default function Editor() {
  const { id } = useParams();
  return id ? <ExistingStory id={id} /> : <NewStory />;
}

// ---------------------------------------------------------------------------
// New story composer
// ---------------------------------------------------------------------------
const blankGate = (sequence: number): GateInput => ({
  sequence,
  body: "",
  is_terminal: sequence > 1,
  conflict_edge: "",
  scope_variant: "",
  framing_variant: "",
  process_frame: null,
  is_anchor: false,
  anchor_id: "",
  is_exploratory: false,
  choices: [{ label: "", next_sequence: null }, { label: "", next_sequence: null }],
});

function NewStory() {
  const [meta, setMeta] = useState({ title: "", genre: "", body: "", publish_date: "" });
  const [gates, setGates] = useState<GateInput[]>([blankGate(1)]);
  const [loadingsText, setLoadingsText] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);

  function setGate(i: number, patch: Partial<GateInput>) {
    setGates((gs) => gs.map((g, j) => (j === i ? { ...g, ...patch } : g)));
  }

  function submit() {
    setMsg(null);
    try {
      const payload: StoryInput = {
        ...meta,
        status: "draft",
        gates: gates.map((g) => ({
          ...g,
          conflict_edge: g.is_exploratory ? null : g.conflict_edge || null,
          scope_variant: g.scope_variant || null,
          framing_variant: g.framing_variant || null,
          anchor_id: g.is_anchor ? g.anchor_id || null : null,
          choices: g.choices.map((c, ci) => ({
            label: c.label,
            next_sequence: c.next_sequence,
            axis_loadings: parseLoadings(loadingsText[`${g.sequence}-${ci}`]),
            is_defection: c.is_defection ?? false,
            cni_role: c.cni_role ?? null,
            lead_in_text: c.lead_in_text?.trim() ? c.lead_in_text.trim() : null,
          })),
        })),
      };
      api
        .createStory(payload)
        .then((r) => setMsg(`Created story ${r.story_id}`))
        .catch((e) => setMsg(`Error: ${e?.detail?.error ?? e.message}`));
    } catch (e: any) {
      setMsg(`Invalid loadings JSON: ${e.message}`);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">New story</h2>
        <button
          disabled
          title="Offline LLM drafting — not wired yet"
          className="cursor-not-allowed rounded-lg border border-slate-700 px-3 py-1 text-sm text-slate-500"
        >
          Draft with Claude (soon)
        </button>
      </div>

      <div className="grid gap-3">
        <input
          placeholder="Title"
          value={meta.title}
          onChange={(e) => setMeta({ ...meta, title: e.target.value })}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2"
        />
        <div className="flex gap-3">
          <input
            placeholder="Genre"
            value={meta.genre}
            onChange={(e) => setMeta({ ...meta, genre: e.target.value })}
            className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2"
          />
          <input
            type="date"
            value={meta.publish_date}
            onChange={(e) => setMeta({ ...meta, publish_date: e.target.value })}
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2"
          />
        </div>
        <textarea
          placeholder="Story setup (paste your AI draft here, then curate — rich scene, clean fork)"
          value={meta.body}
          onChange={(e) => setMeta({ ...meta, body: e.target.value })}
          rows={4}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2"
        />
      </div>

      <div className="space-y-4">
        {gates.map((g, i) => (
          <GateEditor
            key={i}
            gate={g}
            loadingsText={loadingsText}
            setLoadingsText={setLoadingsText}
            isAnchorSequence={(seq) =>
              gates.some((x) => x.sequence === seq && x.is_anchor)
            }
            onChange={(patch) => setGate(i, patch)}
          />
        ))}
        <button
          onClick={() => setGates((gs) => [...gs, blankGate(gs.length + 1)])}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:border-slate-400"
        >
          + Add gate
        </button>
      </div>

      <Preview title={meta.title} body={meta.body} gates={gates} />

      <div className="flex items-center gap-3">
        <button
          onClick={submit}
          className="rounded-lg bg-slate-100 px-4 py-2 font-medium text-slate-900"
        >
          Create draft
        </button>
        {msg && <span className="text-sm text-slate-400">{msg}</span>}
      </div>
    </div>
  );
}

function GateEditor({
  gate,
  onChange,
  loadingsText,
  setLoadingsText,
  isAnchorSequence,
}: {
  gate: GateInput;
  onChange: (patch: Partial<GateInput>) => void;
  loadingsText: Record<string, string>;
  setLoadingsText: (f: (s: Record<string, string>) => Record<string, string>) => void;
  isAnchorSequence: (seq: number) => boolean;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-slate-800 p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-300">Gate {gate.sequence}</span>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={gate.is_terminal}
            onChange={(e) => onChange({ is_terminal: e.target.checked })}
          />
          terminal
        </label>
      </div>
      <textarea
        placeholder="The fork (keep options tight — one trade-off)"
        value={gate.body}
        onChange={(e) => onChange({ body: e.target.value })}
        rows={2}
        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
      />

      <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
        <input
          placeholder="conflict_edge (e.g. care__honesty)"
          disabled={gate.is_exploratory}
          value={gate.conflict_edge ?? ""}
          onChange={(e) => onChange({ conflict_edge: e.target.value })}
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 disabled:opacity-40"
        />
        <select
          value={gate.scope_variant ?? ""}
          onChange={(e) => onChange({ scope_variant: e.target.value })}
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1"
        >
          <option value="">scope…</option>
          {SCOPE_VARIANTS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          value={gate.framing_variant ?? ""}
          onChange={(e) => onChange({ framing_variant: e.target.value })}
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1"
        >
          <option value="">framing…</option>
          {FRAMING_VARIANTS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          value={gate.process_frame ?? ""}
          onChange={(e) =>
            onChange({ process_frame: (e.target.value || null) as GateInput["process_frame"] })
          }
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1"
        >
          <option value="">process…</option>
          {PROCESS_FRAMES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={gate.is_exploratory}
            onChange={(e) => onChange({ is_exploratory: e.target.checked })}
          />
          exploratory
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={gate.is_anchor}
            onChange={(e) => onChange({ is_anchor: e.target.checked })}
          />
          anchor
        </label>
      </div>

      {gate.is_anchor && (
        <div className="space-y-1">
          <input
            placeholder="anchor_id (e.g. anchor_care_honesty)"
            value={gate.anchor_id ?? ""}
            onChange={(e) => onChange({ anchor_id: e.target.value })}
            className="w-full rounded-lg border border-amber-800 bg-slate-900 px-2 py-1 text-sm"
          />
          <p className="text-xs text-amber-500">
            ⚠ Anchors are immutable once saved — editing later destroys their
            measurement value. Get the fork right now.
          </p>
        </div>
      )}

      <div className="space-y-2">
        {gate.choices.map((c, ci) => {
          const setChoice = (patch: Partial<typeof c>) =>
            onChange({ choices: gate.choices.map((x, j) => (j === ci ? { ...x, ...patch } : x)) });
          return (
            <div key={ci} className="space-y-1 rounded-lg border border-slate-800 p-2">
              <div className="grid grid-cols-12 gap-2">
                <input
                  placeholder={`Choice ${ci + 1}`}
                  value={c.label}
                  onChange={(e) => setChoice({ label: e.target.value })}
                  className="col-span-8 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
                />
                <input
                  placeholder="next seq"
                  value={c.next_sequence ?? ""}
                  onChange={(e) =>
                    setChoice({ next_sequence: e.target.value ? Number(e.target.value) : null })
                  }
                  className="col-span-2 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
                />
                <input
                  placeholder='loadings {"care":0.7}'
                  value={loadingsText[`${gate.sequence}-${ci}`] ?? ""}
                  onChange={(e) =>
                    setLoadingsText((s) => ({ ...s, [`${gate.sequence}-${ci}`]: e.target.value }))
                  }
                  className="col-span-12 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs"
                />
              </div>
              <div className="flex items-center gap-4 text-xs text-slate-400">
                <label
                  className={`flex items-center gap-1 ${gate.is_anchor ? "opacity-40" : ""}`}
                  title={gate.is_anchor ? "Anchors must stay defection-free" : ""}
                >
                  <input
                    type="checkbox"
                    disabled={gate.is_anchor}
                    checked={c.is_defection ?? false}
                    onChange={(e) => setChoice({ is_defection: e.target.checked })}
                  />
                  defection (costed self-interest)
                </label>
                <label className="flex items-center gap-1">
                  CNI:
                  <select
                    value={c.cni_role ?? ""}
                    onChange={(e) =>
                      setChoice({ cni_role: (e.target.value || null) as typeof c.cni_role })
                    }
                    className="rounded border border-slate-700 bg-slate-900 px-1 py-0.5"
                  >
                    <option value="">—</option>
                    <option value="consequences">consequences</option>
                    <option value="norms">norms</option>
                    <option value="inaction">inaction</option>
                  </select>
                </label>
              </div>
              {(() => {
                const targetsAnchor =
                  c.next_sequence != null && isAnchorSequence(c.next_sequence);
                return (
                  <textarea
                    placeholder={
                      targetsAnchor
                        ? "lead-in disabled — next beat is an anchor (must stay path-invariant)"
                        : "lead-in: what's read on the NEXT beat if this is chosen — acknowledge, don't evaluate"
                    }
                    disabled={targetsAnchor}
                    value={targetsAnchor ? "" : c.lead_in_text ?? ""}
                    onChange={(e) => setChoice({ lead_in_text: e.target.value })}
                    rows={2}
                    className="w-full rounded-lg border border-slate-800 bg-slate-900 px-2 py-1 text-xs italic text-slate-300 disabled:opacity-40"
                  />
                );
              })()}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Existing story: schedule + non-anchor body edits (anchors locked)
// ---------------------------------------------------------------------------
function ExistingStory({ id }: { id: string }) {
  const [story, setStory] = useState<any>(null);
  const [status, setStatus] = useState("");
  const [date, setDate] = useState("");
  const [bodies, setBodies] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api.story(id).then((s) => {
      setStory(s);
      setStatus(s.status);
      setDate(s.publish_date?.slice(0, 10) ?? "");
      setBodies(Object.fromEntries(s.gates.map((g: any) => [g.id, g.body])));
    });
  }, [id]);

  if (!story) return <p className="text-sm text-slate-500">Loading…</p>;

  function save() {
    setMsg(null);
    const gateEdits = story.gates
      .filter((g: any) => !g.is_anchor && bodies[g.id] !== g.body)
      .map((g: any) => ({ id: g.id, body: bodies[g.id] }));
    api
      .updateStory({ id, publish_date: date || undefined, status, gates: gateEdits })
      .then(() => setMsg("Saved"))
      .catch((e) => setMsg(`Error: ${e?.detail?.error ?? e.message}`));
  }

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">{story.title}</h2>

      <div className="flex items-center gap-3 text-sm">
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2"
        >
          {["draft", "scheduled", "live", "archived"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>

      <div className="space-y-3">
        {story.gates.map((g: any) => (
          <div key={g.id} className="rounded-xl border border-slate-800 p-3">
            <div className="mb-1 flex items-center gap-2 text-xs text-slate-500">
              <span>Gate {g.sequence}</span>
              {g.conflict_edge && <span className="font-mono">{g.conflict_edge}</span>}
              {g.is_anchor && <span className="text-amber-500">★ anchor (locked)</span>}
              {g.is_exploratory && <span>exploratory</span>}
            </div>
            <textarea
              value={bodies[g.id] ?? ""}
              disabled={g.is_anchor}
              onChange={(e) => setBodies((b) => ({ ...b, [g.id]: e.target.value }))}
              rows={2}
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm disabled:opacity-50"
            />
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <button onClick={save} className="rounded-lg bg-slate-100 px-4 py-2 font-medium text-slate-900">
          Save
        </button>
        {msg && <span className="text-sm text-slate-400">{msg}</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline preview (how the player sees it)
// ---------------------------------------------------------------------------
function Preview({ title, body, gates }: { title: string; body: string; gates: GateInput[] }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">Preview</p>
      <h3 className="text-xl font-semibold">{title || "Untitled"}</h3>
      <p className="mt-2 text-sm text-slate-300">{body}</p>
      {gates.map((g) => (
        <div key={g.sequence} className="mt-4">
          <p className="text-sm">{g.body}</p>
          <div className="mt-2 grid gap-2">
            {g.choices.map((c, i) => (
              <div key={i} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300">
                {c.label || <span className="text-slate-600">(empty choice)</span>}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function parseLoadings(text?: string): Record<string, number> {
  if (!text || !text.trim()) return {};
  const parsed = JSON.parse(text);
  if (typeof parsed !== "object" || parsed === null) throw new Error("must be an object");
  return parsed;
}
