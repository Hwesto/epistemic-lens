import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../src/db";
import { currentUserId } from "../src/auth";
import { scoreProfile, REVEAL_HEDGE, type ScoredEvent } from "../src/scoring";

// Derive the profile by RE-SCORING from the immutable log under the active
// framework_version. The profile is a disposable view (§4) — we recompute it
// rather than trusting a stored value. This is also exactly how Phase-2
// recalibration works: same read of the log, smarter scoring function.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  const userId = await currentUserId(req);
  if (!userId) {
    res.status(401).json({ error: "auth required" });
    return;
  }

  const sql = db();

  // active framework = latest version
  const fw = await sql<{ id: number }[]>`
    select id from framework_versions order by id desc limit 1
  `;
  if (fw.length === 0) {
    res.status(500).json({ error: "no framework_version seeded" });
    return;
  }
  const frameworkVersionId = fw[0].id;

  // pull the loadings of every option this user actually TOOK, under the active
  // framework. Reading the immutable event log — never an editable summary.
  const events = await sql<{ axis_loadings: Record<string, number> }[]>`
    select c.axis_loadings
    from choice_events ce
    join choices c on c.id = ce.choice_id
    where ce.user_id = ${userId}
      and c.framework_version_id = ${frameworkVersionId}
  `;

  const scored: ScoredEvent[] = events.map((e) => ({ loadings: e.axis_loadings }));
  const axes = scoreProfile(scored);

  // persist the derived view (recomputable; safe to overwrite — it is NOT the asset)
  await sql`
    insert into profiles (user_id, framework_version_id, axis_scores, axis_confidence, consistency)
    values (
      ${userId}, ${frameworkVersionId},
      ${sql.json(Object.fromEntries(axes.map((a) => [a.axis, a.score])))},
      ${sql.json(Object.fromEntries(axes.map((a) => [a.axis, a.confidence])))},
      ${sql.json({})}
    )
    on conflict (user_id, framework_version_id) do update
      set axis_scores = excluded.axis_scores,
          axis_confidence = excluded.axis_confidence,
          scored_at = now()
  `;

  res.status(200).json({
    framework_version_id: frameworkVersionId,
    scored_at: new Date().toISOString(),
    axes,
    hedge: REVEAL_HEDGE,
  });
}
