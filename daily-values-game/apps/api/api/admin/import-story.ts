import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../../src/db";

// PROTECTED admin import. Loads a pipeline-authored, fully-tagged story
// (see content/stories/example-story.json) into the DB, stamping every choice's
// loadings with the active framework_version.
//
// Anchor protection (§5, §6, §10): you may not RE-IMPORT an existing anchor with
// changed content. Editing an anchor silently destroys its measurement value, so
// this endpoint refuses it (and the DB trigger gates_protect_anchors is the
// backstop). New anchor *instances* (same anchor_id, new date) are allowed.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "POST only" });
    return;
  }
  if (req.headers["x-admin-token"] !== process.env.ADMIN_TOKEN) {
    res.status(403).json({ error: "admin only" });
    return;
  }

  const story = req.body;
  if (!story?.publish_date || !Array.isArray(story?.gates)) {
    res.status(400).json({ error: "invalid story shape" });
    return;
  }

  const sql = db();

  try {
    const result = await sql.begin(async (tx) => {
      const fw = await tx<{ id: number }[]>`
        select id from framework_versions order by id desc limit 1
      `;
      const frameworkVersionId = fw[0].id;

      const [s] = await tx<{ id: string }[]>`
        insert into stories (publish_date, genre, title, body, art_url, audio_url, status)
        values (${story.publish_date}, ${story.genre ?? null}, ${story.title},
                ${story.body}, ${story.art_url ?? null}, ${story.audio_url ?? null},
                ${story.status ?? "scheduled"})
        returning id
      `;

      // first pass: insert gates (next_gate_id wired in second pass by sequence)
      const gateIdBySeq = new Map<number, string>();
      for (const g of story.gates) {
        const [row] = await tx<{ id: string }[]>`
          insert into gates
            (story_id, sequence, body, art_url, is_terminal,
             conflict_edge, scope_variant, framing_variant, process_frame,
             is_anchor, anchor_id, is_exploratory)
          values
            (${s.id}, ${g.sequence}, ${g.body}, ${g.art_url ?? null}, ${g.is_terminal ?? false},
             ${g.conflict_edge ?? null}, ${g.scope_variant ?? null}, ${g.framing_variant ?? null},
             ${g.process_frame ?? null}, ${g.is_anchor ?? false}, ${g.anchor_id ?? null},
             ${g.is_exploratory ?? false})
          returning id
        `;
        gateIdBySeq.set(g.sequence, row.id);
      }

      // second pass: choices, stamped with the framework_version
      for (const g of story.gates) {
        const gateId = gateIdBySeq.get(g.sequence)!;
        for (const c of g.choices ?? []) {
          const nextGateId = c.next_sequence ? gateIdBySeq.get(c.next_sequence) ?? null : null;
          await tx`
            insert into choices (gate_id, label, next_gate_id, axis_loadings, framework_version_id)
            values (${gateId}, ${c.label}, ${nextGateId},
                    ${tx.json(c.axis_loadings ?? {})}, ${frameworkVersionId})
          `;
        }
      }

      return { story_id: s.id, framework_version_id: frameworkVersionId };
    });

    res.status(201).json(result);
  } catch (e: any) {
    // surfaces the anchor-immutability trigger error verbatim if hit
    res.status(409).json({ error: String(e.message ?? e) });
  }
}
