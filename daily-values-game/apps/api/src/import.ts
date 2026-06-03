// Reusable story importer. Loads a pipeline-authored, fully-tagged story into
// the DB, stamping every choice's loadings with the active framework_version and
// wiring next_gate_id across gates by `next_sequence` (two-pass).
//
// Shared by the admin import endpoint and the dev seed script so both take the
// exact same path. Caller supplies a transaction (sql.begin) — anchor protection
// and append-only invariants are enforced by the DB triggers regardless.

export interface StoryChoiceInput {
  label: string;
  next_sequence?: number | null; // sequence of the gate this choice leads to
  axis_loadings?: Record<string, number>; // may include a `self_enhancement` key (v2)
  is_defection?: boolean; // v2: the costed self-interest option
  cni_role?: "consequences" | "norms" | "inaction" | null; // v2: CNI process route
}

export interface StoryGateInput {
  sequence: number;
  body: string;
  art_url?: string | null;
  is_terminal?: boolean;
  conflict_edge?: string | null;
  scope_variant?: string | null;
  framing_variant?: string | null;
  process_frame?: "rule" | "outcome" | null;
  is_anchor?: boolean;
  anchor_id?: string | null;
  is_exploratory?: boolean;
  choices?: StoryChoiceInput[];
}

export interface StoryInput {
  publish_date: string;
  genre?: string | null;
  title: string;
  body: string;
  art_url?: string | null;
  audio_url?: string | null;
  status?: "draft" | "scheduled" | "live" | "archived";
  gates: StoryGateInput[];
}

// `tx` is a postgres.js transaction (or sql instance). Returns the new ids.
export async function importStory(
  tx: any,
  story: StoryInput
): Promise<{ story_id: string; framework_version_id: number }> {
  const fw = await tx<{ id: number }[]>`
    select id from framework_versions order by id desc limit 1
  `;
  if (fw.length === 0) {
    throw new Error("no framework_version seeded — run db:seed first");
  }
  const frameworkVersionId = fw[0].id;

  const [s] = await tx<{ id: string }[]>`
    insert into stories (publish_date, genre, title, body, art_url, audio_url, status)
    values (${story.publish_date}, ${story.genre ?? null}, ${story.title},
            ${story.body}, ${story.art_url ?? null}, ${story.audio_url ?? null},
            ${story.status ?? "scheduled"})
    returning id
  `;

  // first pass: insert gates (next_gate_id wired in the second pass by sequence)
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

  // second pass: choices, stamped with the framework_version. `position` is the
  // index in the authoring array → authored order == stored == served order.
  for (const g of story.gates) {
    const gateId = gateIdBySeq.get(g.sequence)!;
    const choices = g.choices ?? [];
    for (let i = 0; i < choices.length; i++) {
      const c = choices[i];
      const nextGateId = c.next_sequence ? gateIdBySeq.get(c.next_sequence) ?? null : null;
      await tx`
        insert into choices
          (gate_id, label, position, next_gate_id, axis_loadings, is_defection, cni_role, framework_version_id)
        values
          (${gateId}, ${c.label}, ${i}, ${nextGateId}, ${tx.json(c.axis_loadings ?? {})},
           ${c.is_defection ?? false}, ${c.cni_role ?? null}, ${frameworkVersionId})
      `;
    }
  }

  return { story_id: s.id, framework_version_id: frameworkVersionId };
}
