// Top-level composition that consumes a video_scripts/<date>_<n>.json
// (matching VideoScriptProps) and orchestrates scenes with a continuous
// camera dolly across the world map.

import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import { VideoScriptProps, Scene } from "./types";
import { presetFor, WORLD, CameraPreset } from "./cameraPresets";
import { WorldMapBackground } from "./components/WorldMap";
import { CountryPin } from "./components/CountryPin";
import { QuoteCard } from "./components/QuoteCard";
import { TitleCard } from "./components/TitleCard";
import { OutroCard } from "./components/OutroCard";

// Heuristic: infer a country code from a scene's text fields if not set.
// Looks for flag emoji or known country labels.
const COUNTRY_FLAG_MAP: Array<[RegExp, string]> = [
  [/🇺🇸|\bUSA\b|\bUnited States\b/, "us"],
  [/🇬🇧|\bUK\b|\bBritain\b/, "uk"],
  [/🇫🇷|\bFrance\b/, "fr"],
  [/🇩🇪|\bGermany\b/, "de"],
  [/🇮🇹|\bItaly\b/, "it"],
  [/🇪🇸|\bSpain\b/, "es"],
  [/🇷🇺|\bRussia\b/, "ru"],
  [/🇺🇦|\bUkraine\b/, "ua"],
  [/🇮🇷|\bIran\b/, "ir"],
  [/🇮🇱|\bIsrael\b/, "il"],
  [/🇱🇧|\bLebanon\b/, "lb"],
  [/🇸🇦|\bSaudi\b/, "sa"],
  [/🇶🇦|\bQatar\b/, "qa"],
  [/🇪🇬|\bEgypt\b/, "eg"],
  [/🇹🇷|\bTurkey|Türkiye\b/, "tr"],
  [/🇮🇳|\bIndia\b/, "in"],
  [/🇵🇰|\bPakistan\b/, "pk"],
  [/🇨🇳|\bChina\b/, "cn"],
  [/🇯🇵|\bJapan\b/, "jp"],
  [/🇰🇷|\bSouth Korea\b/, "kr"],
  [/🇰🇵|\bNorth Korea\b/, "kp"],
  [/🇹🇼|\bTaiwan\b/, "tw"],
  [/🇮🇩|\bIndonesia\b/, "id"],
  [/🇵🇭|\bPhilippines\b/, "ph"],
  [/🇦🇺|\bAustralia\b/, "au"],
  [/🇨🇦|\bCanada\b/, "ca"],
  [/🇲🇽|\bMexico\b/, "mx"],
  [/🇧🇷|\bBrazil\b/, "br"],
  [/🇿🇦|\bSouth Africa\b/, "za"],
  [/🇰🇪|\bKenya\b/, "ke"],
  [/🇳🇬|\bNigeria\b/, "ng"],
  [/🇻🇦|\bVatican\b/, "va"],
  [/🇬🇪|\bGeorgia\b/, "ge"],
];

function inferCountry(scene: Scene): string | undefined {
  if (scene.country) return scene.country;
  const haystack = `${scene.on_screen_text} ${scene.headline_quoted ?? ""}`;
  for (const [re, code] of COUNTRY_FLAG_MAP) {
    if (re.test(haystack)) return code;
  }
  return undefined;
}

// Heuristic: classify each scene by the role its on_screen_text plays.
type SceneType = "title" | "world_intro" | "country" | "outro";
function classifyScene(scene: Scene, idx: number, total: number): SceneType {
  const txt = scene.on_screen_text.toLowerCase();
  if (idx === 0) return "title";
  if (idx === total - 1) return "outro";
  if (idx === 1 && !inferCountry(scene)) return "world_intro";
  if (inferCountry(scene)) return "country";
  return "world_intro";
}

// Each scene's duration (in seconds) — derived from the "0:00-0:05"
// time field in the script, or 8s default.
function parseTimeRange(t: string): { start: number; end: number } {
  const m = t.match(/(\d+):(\d+)-(\d+):(\d+)/);
  if (!m) return { start: 0, end: 8 };
  const start = parseInt(m[1]) * 60 + parseInt(m[2]);
  const end = parseInt(m[3]) * 60 + parseInt(m[4]);
  return { start, end };
}

export const FramingVideo: React.FC<VideoScriptProps> = (props) => {
  const { fps } = useVideoConfig();
  const { scenes, story_title, story_date, story_one_liner } = props;

  // Compute frame ranges for each scene. Prefer measured audio duration
  // (set by render_video.py from synthesize_voiceover.py durations.json)
  // when present — this guarantees the visual matches the voice. Fall
  // back to the script's "0:00-0:05" time range for scenes without audio.
  let cursor = 0;
  const sceneRanges: Array<{ from: number; durationInFrames: number }> = [];
  for (const s of scenes) {
    let seconds: number;
    if (typeof s.duration_seconds === "number" && s.duration_seconds > 0) {
      // Add a small buffer (0.4s) so the next scene doesn't start while
      // voiceover is still trailing off
      seconds = s.duration_seconds + 0.4;
    } else {
      const { start, end } = parseTimeRange(s.time);
      seconds = Math.max(2, end - start);
    }
    const durationInFrames = Math.round(seconds * fps);
    sceneRanges.push({ from: cursor, durationInFrames });
    cursor += durationInFrames;
  }

  return (
    <AbsoluteFill style={{ background: "black" }}>
      {scenes.map((scene, i) => {
        const range = sceneRanges[i];
        const type = classifyScene(scene, i, scenes.length);
        const country = inferCountry(scene);
        const preset = presetFor(country);

        // Determine camera trajectory for THIS scene's duration:
        //   from = preset of previous country (or WORLD)
        //   to   = preset of THIS scene's country (or WORLD)
        const prevCountry = i > 0 ? inferCountry(scenes[i - 1]) : undefined;
        const startPreset: CameraPreset = prevCountry
          ? presetFor(prevCountry)
          : WORLD;
        const endPreset = preset;

        return (
          <Sequence
            key={i}
            from={range.from}
            durationInFrames={range.durationInFrames}
          >
            {scene.audio ? (
              <Audio src={staticFile(scene.audio)} />
            ) : null}
            <WorldMapBackground
              startPreset={startPreset}
              endPreset={endPreset}
              durationInFrames={range.durationInFrames}
              highlightCountry={country}
            />
            {type === "title" ? (
              <TitleCard text={scene.on_screen_text} storyDate={story_date} />
            ) : type === "outro" ? (
              <OutroCard text={scene.on_screen_text} />
            ) : type === "country" ? (
              <>
                <CountryPin flag={preset.flag} label={preset.label} />
                <QuoteCard
                  onScreenText={scene.on_screen_text}
                  headlineQuoted={scene.headline_quoted}
                />
              </>
            ) : (
              <QuoteCard
                onScreenText={scene.on_screen_text}
                headlineQuoted={scene.headline_quoted}
              />
            )}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

// Helper exposed for Root.tsx so the composition's durationInFrames
// can be derived from the script's scenes.
export function totalDurationInFrames(props: VideoScriptProps, fps: number): number {
  let total = 0;
  for (const s of props.scenes) {
    let seconds: number;
    if (typeof s.duration_seconds === "number" && s.duration_seconds > 0) {
      seconds = s.duration_seconds + 0.4;
    } else {
      const { start, end } = parseTimeRange(s.time);
      seconds = Math.max(2, end - start);
    }
    total += Math.round(seconds * fps);
  }
  return total || Math.round((props.duration_seconds || 60) * fps);
}
