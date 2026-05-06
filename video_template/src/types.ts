// Schema mirrors video_scripts/<date>_<n>.json — produced by build_briefing.py
// + framing_pass.py (or hand-authored).

export type Scene = {
  scene: number;
  time: string; // "0:00-0:05" — informational only, durations come from durationInFrames below
  voiceover: string;
  visual_brief?: string;
  on_screen_text: string;
  headline_quoted?: string;
  // Optional country code for camera focus (us / ir / cn / ru / pk / il / etc.)
  // If absent, the scene shows the world overview (used for Hook + Outro).
  country?: string;
  // Audio (set by render_video.py from synthesize_voiceover.py output)
  audio?: string;        // staticFile-relative path under public/, e.g. "voiceovers/<id>/scene_01.wav"
  duration_seconds?: number; // measured WAV duration; overrides `time` if set
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
  fact_check_provenance?: FactCheckProvenance;
};
