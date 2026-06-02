import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../src/db";

// The social split as percentages per choice, for a story. Read constantly, so
// it must be cheap/cached (§10): served from daily_aggregates counters, not a
// scan of the event log. In prod, front this with Redis/KV.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  const storyId = req.query.story as string;
  if (!storyId) {
    res.status(400).json({ error: "story query param required" });
    return;
  }

  const sql = db();
  const rows = await sql<{ choice_id: string; count: number }[]>`
    select da.choice_id, da.count
    from daily_aggregates da
    join choices c on c.id = da.choice_id
    join gates  g on g.id = c.gate_id
    where da.story_id = ${storyId}
  `;

  // normalise within each gate so each gate's options sum to ~100%
  const byGate = await sql<{ choice_id: string; gate_id: string }[]>`
    select c.id as choice_id, c.gate_id
    from choices c join gates g on g.id = c.gate_id
    where g.story_id = ${storyId}
  `;
  const gateOf = new Map(byGate.map((r) => [r.choice_id, r.gate_id]));
  const gateTotals = new Map<string, number>();
  for (const r of rows) {
    const gate = gateOf.get(r.choice_id)!;
    gateTotals.set(gate, (gateTotals.get(gate) ?? 0) + Number(r.count));
  }

  const split: Record<string, number> = {};
  for (const r of rows) {
    const total = gateTotals.get(gateOf.get(r.choice_id)!) || 1;
    split[r.choice_id] = (Number(r.count) / total) * 100;
  }

  res.setHeader("Cache-Control", "public, s-maxage=30, stale-while-revalidate=300");
  res.status(200).json(split);
}
