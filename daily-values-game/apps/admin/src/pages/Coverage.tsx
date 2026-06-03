import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { CoverageEdge, AnchorRow } from "../lib/types";

// The PLAN step (§6): which edge / scope / framing is under-target, and the
// health of each anchor family. Reads the coverage + anchor_health views.
export default function Coverage() {
  const [edges, setEdges] = useState<CoverageEdge[]>([]);
  const [anchors, setAnchors] = useState<AnchorRow[]>([]);
  const [target, setTarget] = useState(5);

  useEffect(() => {
    api.coverage().then((c) => {
      setEdges(c.edges);
      setAnchors(c.anchors);
      setTarget(c.target_reps);
    });
  }, []);

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-1 text-lg font-semibold">Coverage</h2>
        <p className="mb-3 text-sm text-slate-500">
          Each spine edge wants ~{target} reps before a baseline. Rows under target
          are highlighted — write those next.
        </p>
        {edges.length === 0 ? (
          <p className="text-sm text-slate-500">No edges authored yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-slate-500">
              <tr>
                <th className="py-1">Edge</th>
                <th>Reps</th>
                <th>Scopes</th>
                <th>Framings</th>
                <th>Plays</th>
                <th>Anchor</th>
              </tr>
            </thead>
            <tbody>
              {edges.map((e) => (
                <tr
                  key={e.conflict_edge}
                  className={e.under_target ? "text-amber-400" : "text-slate-200"}
                >
                  <td className="py-1 font-mono">{e.conflict_edge}</td>
                  <td>
                    {e.gates_authored}/{target}
                  </td>
                  <td>{e.scope_variants_hit}</td>
                  <td>{e.framing_variants_hit}</td>
                  <td>{e.choice_events_recorded}</td>
                  <td>{e.has_anchor ? "★" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2 className="mb-1 text-lg font-semibold">Anchor health</h2>
        <p className="mb-3 text-sm text-slate-500">
          Invariant re-runs across dates — the ruler for drift &amp; test–retest.
        </p>
        {anchors.length === 0 ? (
          <p className="text-sm text-slate-500">No anchors planted yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-slate-500">
              <tr>
                <th className="py-1">Anchor</th>
                <th>Edge</th>
                <th>Instances</th>
                <th>Dates</th>
                <th>Plays</th>
              </tr>
            </thead>
            <tbody>
              {anchors.map((a) => (
                <tr key={a.anchor_id} className="text-slate-200">
                  <td className="py-1 font-mono">{a.anchor_id}</td>
                  <td className="font-mono">{a.conflict_edge}</td>
                  <td>{a.instances}</td>
                  <td>{a.distinct_dates}</td>
                  <td>{a.plays}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
