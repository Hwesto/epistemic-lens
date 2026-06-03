import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../../src/db";
import { requireAdmin } from "../../src/auth";

// Admin: list stories (optionally filtered by status), newest scheduled first.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (!(await requireAdmin(req))) {
    res.status(403).json({ error: "admin only" });
    return;
  }

  const status = req.query.status as string | undefined;
  const sql = db();

  const rows = status
    ? await sql`
        select s.id, s.publish_date, s.title, s.genre, s.status,
               count(g.id) as gate_count
        from stories s left join gates g on g.story_id = s.id
        where s.status = ${status}
        group by s.id order by s.publish_date desc nulls last`
    : await sql`
        select s.id, s.publish_date, s.title, s.genre, s.status,
               count(g.id) as gate_count
        from stories s left join gates g on g.story_id = s.id
        group by s.id order by s.publish_date desc nulls last`;

  res.status(200).json(rows);
}
