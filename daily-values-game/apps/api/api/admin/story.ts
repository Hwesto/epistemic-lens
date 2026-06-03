import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../../src/db";
import { requireAdmin } from "../../src/auth";

// Admin: fetch one story for preview/edit (GET ?id=…), or update its schedule/
// status and non-anchor gate bodies (PATCH).
//
// Anchor gates are immutable: the DB trigger gates_protect_anchors rejects any
// update, which we surface as 409. The admin UI also disables editing them.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (!(await requireAdmin(req))) {
    res.status(403).json({ error: "admin only" });
    return;
  }
  const sql = db();

  if (req.method === "GET") {
    const id = req.query.id as string;
    if (!id) {
      res.status(400).json({ error: "id required" });
      return;
    }
    const [story] = await sql`select * from stories where id = ${id}`;
    if (!story) {
      res.status(404).json({ error: "not found" });
      return;
    }
    const gates = await sql`select * from gates where story_id = ${id} order by sequence`;
    const gateIds = gates.map((g: any) => g.id);
    const choices = gateIds.length
      ? await sql`select * from choices where gate_id in ${sql(gateIds)} order by gate_id, position`
      : [];
    res.status(200).json({
      ...story,
      gates: gates.map((g: any) => ({
        ...g,
        choices: choices.filter((c: any) => c.gate_id === g.id),
      })),
    });
    return;
  }

  if (req.method === "PATCH") {
    const { id, publish_date, status, gates } = req.body ?? {};
    if (!id) {
      res.status(400).json({ error: "id required" });
      return;
    }
    try {
      await sql.begin(async (tx) => {
        if (publish_date !== undefined || status !== undefined) {
          await tx`
            update stories set
              publish_date = coalesce(${publish_date ?? null}, publish_date),
              status = coalesce(${status ?? null}, status)
            where id = ${id}
          `;
        }
        // non-anchor gate body edits only; the trigger rejects anchor edits
        for (const g of gates ?? []) {
          await tx`update gates set body = ${g.body} where id = ${g.id} and story_id = ${id}`;
        }
      });
      res.status(200).json({ ok: true });
    } catch (e: any) {
      // surfaces the anchor-immutability trigger verbatim
      res.status(409).json({ error: String(e.message ?? e) });
    }
    return;
  }

  res.status(405).json({ error: "GET or PATCH" });
}
