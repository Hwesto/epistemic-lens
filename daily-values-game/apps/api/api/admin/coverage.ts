import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../../src/db";
import { requireAdmin } from "../../src/auth";

// Admin: the coverage tracker (the PLAN step of the pipeline). Reads the
// `coverage` and `anchor_health` views (db/schema.sql) and flags under-target
// edges against a per-edge rep target (§5 baseline ~5×).
const TARGET_REPS = Number(process.env.COVERAGE_TARGET_REPS ?? 5);

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (!(await requireAdmin(req))) {
    res.status(403).json({ error: "admin only" });
    return;
  }

  const sql = db();
  const coverage = await sql`
    select conflict_edge, gates_authored, stories_touching,
           scope_variants_hit, framing_variants_hit, choice_events_recorded, has_anchor
    from coverage order by conflict_edge
  `;
  const anchors = await sql`
    select anchor_id, conflict_edge, instances, distinct_dates, plays
    from anchor_health order by anchor_id
  `;

  const edges = coverage.map((c: any) => ({
    ...c,
    target_reps: TARGET_REPS,
    under_target: Number(c.gates_authored) < TARGET_REPS,
  }));

  res.status(200).json({ target_reps: TARGET_REPS, edges, anchors });
}
