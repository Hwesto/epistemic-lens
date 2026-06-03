import type { VercelRequest, VercelResponse } from "@vercel/node";
import { db } from "../../src/db";
import { importStory } from "../../src/import";

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
    const result = await sql.begin((tx) => importStory(tx, story));
    res.status(201).json(result);
  } catch (e: any) {
    // surfaces the anchor-immutability trigger error verbatim if hit
    res.status(409).json({ error: String(e.message ?? e) });
  }
}
