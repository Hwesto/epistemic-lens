// Schema mirrors video_scripts/<date>_<n>.json — produced by build_briefing.py
// + framing_pass.py (or hand-authored).

export type Scene = {
  scene: number;
  time: string;
  voiceover: string;
  visual_brief?: string;
  on_screen_text: string;
  headline_quoted?: string;
  country?: string;
  audio?: string;
  duration_seconds?: number;
};

// Ambient ticker — small headline that floats over a non-focal country
// to show "the rest of the world is also reporting today". Should be
// real headlines from the same date's snapshot for credibility.
export type WorldTicker = {
  country_code: string; // 2-letter, e.g. "br", "jp"
  headline: string;     // <80 chars ideal
  outlet?: string;      // small attribution, optional
};

export type FactCheckProvenance = {
  primary_event_source?: string;
  supporting_quotes_per_frame?: Array<{
    frame: string;
    outlet: string;
    exact_headline: string;
  }>;
  briefing_corpus?: string;
};

export type VideoScriptProps = {
  video_id: string;
  story_date: string;
  story_title: string;
  story_one_liner?: string;
  duration_seconds: number;
  scenes: Scene[];
  // Optional 3-second intro sting (logo flash + branded audio) prepended
  // before scene 1. Set to "intro_sting.mp3" to use the bundled file.
  intro_sting_audio?: string;
  intro_sting_seconds?: number; // default 3
  channel_name?: string; // displayed in the sting (default "DAILY FRAMINGS")
  // Ambient world tickers — shown on the map throughout the video
  world_tickers?: WorldTicker[];
  fact_check_provenance?: FactCheckProvenance;
};
