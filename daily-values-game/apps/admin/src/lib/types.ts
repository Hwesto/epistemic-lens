// Editor-side story shape. Mirrors apps/api/src/import.ts StoryInput (keep in
// sync). next_sequence wires a choice to the gate it leads to.
export interface ChoiceInput {
  label: string;
  next_sequence?: number | null;
  axis_loadings?: Record<string, number>; // may include `self_enhancement` (v2)
  is_defection?: boolean; // v2: costed self-interest option
  cni_role?: "consequences" | "norms" | "inaction" | null; // v2: CNI route
}

export interface GateInput {
  sequence: number;
  body: string;
  is_terminal?: boolean;
  conflict_edge?: string | null;
  scope_variant?: string | null;
  framing_variant?: string | null;
  process_frame?: "rule" | "outcome" | null;
  is_anchor?: boolean;
  anchor_id?: string | null;
  is_exploratory?: boolean;
  choices: ChoiceInput[];
}

export interface StoryInput {
  publish_date: string;
  genre?: string | null;
  title: string;
  body: string;
  status?: "draft" | "scheduled" | "live" | "archived";
  gates: GateInput[];
}

export interface CoverageEdge {
  conflict_edge: string;
  gates_authored: number;
  stories_touching: number;
  scope_variants_hit: number;
  framing_variants_hit: number;
  choice_events_recorded: number;
  has_anchor: boolean;
  target_reps: number;
  under_target: boolean;
}

export interface AnchorRow {
  anchor_id: string;
  conflict_edge: string;
  instances: number;
  distinct_dates: number;
  plays: number;
}

export interface StoryListItem {
  id: string;
  publish_date: string | null;
  title: string;
  genre: string | null;
  status: string;
  gate_count: number;
}
