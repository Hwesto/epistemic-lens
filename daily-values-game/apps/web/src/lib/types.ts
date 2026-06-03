import type { Axis } from "./axes";

export type AxisLoadings = Partial<Record<Axis | string, number>>;

export interface Choice {
  id: string;
  label: string;
  next_gate_id: string | null;
  // Remembered narration shown when you arrive at next_gate having taken this
  // choice (acknowledge, never evaluate). Null for choices into anchors / terminal.
  lead_in_text?: string | null;
  // axis_loadings are NOT sent to the client during play — they are a measurement
  // detail and revealing them would bias the choice. They live server-side only.
}

export interface Gate {
  id: string;
  sequence: number;
  body: string;
  art_url: string | null;
  is_terminal: boolean;
  choices: Choice[];
}

export interface Story {
  id: string;
  publish_date: string;
  genre: string | null;
  title: string;
  body: string;
  art_url: string | null;
  gates: Gate[];
}

export interface Split {
  // choice_id -> percentage (0..100), the cached social split
  [choiceId: string]: number;
}

export interface ProfileAxis {
  axis: Axis;
  score: number; // -1..1 estimate
  confidence: number; // 0..1, rough in v1
}

export interface Profile {
  framework_version_id: number;
  scored_at: string;
  axes: ProfileAxis[];
  // honest hedge surfaced in the UI (§9): this is "your read so far", not a verdict.
  hedge: string;
}
