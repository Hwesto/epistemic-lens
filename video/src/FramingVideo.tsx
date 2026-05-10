// Top-level composition that consumes a video_scripts/<date>_<n>.json
// (matching VideoScriptProps) and orchestrates scenes with a continuous
// camera dolly across the world map, plus an optional intro sting.

import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import { VideoScriptProps, Scene } from "./types";
import { presetFor, WORLD, CameraPreset } from "./cameraPresets";
import { WorldMapBackground } from "./components/WorldMap";
import { CountryPin } from "./components/CountryPin";
import { QuoteCard } from "./components/QuoteCard";
import { TitleCard } from "./components/TitleCard";
import { OutroCard } from "./components/OutroCard";
import { Captions } from "./components/Captions";
import { IntroSting } from "./components/IntroSting";
import { TopNewsBar } from "./components/TopNewsBar";
import { ParadoxCard } from "./components/ParadoxCard";
import { useCameraDolly } from "./useCameraDolly";
import { COUNTRY_FLAG_MAP } from "./data/country-flags";

const DEFAULT_MUSIC_BED_FILE = "music_bed.wav";
const DEFAULT_MUSIC_BED_VOLUME = 0.10;

function inferCountry(scene: Scene): string | undefined {
  if (scene.country) return scene.country;
  // ONLY check on_screen_text — quoted headlines can mention "United
  // States" in another country's framing scene, which would falsely
  // resolve to USA. The on_screen_text is the canonical country label.
  for (const [re, code] of COUNTRY_FLAG_MAP) {
    if (re.test(scene.on_screen_text)) return code;
  }
  return undefined;
}

type SceneType = "title" | "world_intro" | "country" | "paradox" | "outro";
function classifyScene(scene: Scene, idx: number, total: number): SceneType {
  if (scene.scene_type === "paradox") return "paradox";
  if (idx === 0) return "title";
  if (idx === total - 1) return "outro";
  if (idx === 1 && !inferCountry(scene)) return "world_intro";
  if (inferCountry(scene)) return "country";
  return "world_intro";
}

function parseTimeRange(t: string): { start: number; end: number } {
  const m = t.match(/(\d+):(\d+)-(\d+):(\d+)/);
  if (!m) return { start: 0, end: 8 };
  const start = parseInt(m[1]) * 60 + parseInt(m[2]);
  const end = parseInt(m[3]) * 60 + parseInt(m[4]);
  return { start, end };
}

// Inner per-scene component so we can call useCameraDolly inside a
// Sequence. React hook rules require hooks at the top of a component.
const SceneInner: React.FC<{
  scene: Scene;
  type: SceneType;
  country?: string;
  startPreset: CameraPreset;
  endPreset: CameraPreset;
  durationInFrames: number;
  worldTickers?: VideoScriptProps["world_tickers"];
  storyDate?: string;
}> = ({ scene, type, country, startPreset, endPreset, durationInFrames, worldTickers, storyDate }) => {
  useCameraDolly(startPreset, endPreset, durationInFrames); // pre-warm for child components
  const preset = endPreset;

  // News bar is hidden on title (clean intro) and outro (clean close);
  // visible during all middle scenes.
  const newsBarVisible = type !== "title" && type !== "outro";

  return (
    <>
      {scene.audio ? <Audio src={staticFile(scene.audio)} /> : null}

      {/* Map is always present except during paradox split-card */}
      {type !== "paradox" ? (
        <WorldMapBackground
          startPreset={startPreset}
          endPreset={endPreset}
          durationInFrames={durationInFrames}
          highlightCountry={country}
        />
      ) : (
        // Paradox: deep dark gradient backdrop instead of map
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "radial-gradient(ellipse at center, #1a1530 0%, #050614 70%, #000 100%)",
          }}
        />
      )}

      {/* Top news bar — always-on context, big readable */}
      <TopNewsBar
        tickers={worldTickers || []}
        skipCountry={country}
        totalDurationInFrames={durationInFrames}
        visible={newsBarVisible}
      />

      {/* Burned-in captions for non-title/outro scenes (and not paradox
          which has its own large quote layout) */}
      {type !== "title" && type !== "outro" && type !== "paradox" && scene.voiceover ? (
        <Captions
          voiceover={scene.voiceover}
          durationInFrames={durationInFrames}
        />
      ) : null}

      {type === "title" ? (
        <TitleCard text={scene.on_screen_text} storyDate={storyDate} />
      ) : type === "outro" ? (
        <OutroCard text={scene.on_screen_text} />
      ) : type === "paradox" ? (
        scene.paradox_top && scene.paradox_bottom ? (
          <ParadoxCard
            top={scene.paradox_top}
            bottom={scene.paradox_bottom}
            middle_label={scene.paradox_label}
          />
        ) : null
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
    </>
  );
};

export const FramingVideo: React.FC<VideoScriptProps> = (props) => {
  const { fps } = useVideoConfig();
  const {
    scenes,
    story_date,
    intro_sting_audio,
    intro_sting_seconds = 3,
    channel_name = "DAILY FRAMINGS",
    world_tickers,
    music_bed_file = DEFAULT_MUSIC_BED_FILE,
    music_bed_volume = DEFAULT_MUSIC_BED_VOLUME,
  } = props;

  // Compute frame ranges for each scene.
  let cursor = 0;

  // Optional intro sting prepended before all scenes.
  // After the sting we insert a 4-frame BLACK FLASH (~133ms) for a hard
  // cut into the title — gives the viewer a sharp gear-shift between the
  // branded intro and the actual story.
  const stingFrames = intro_sting_audio
    ? Math.round(intro_sting_seconds * fps)
    : 0;
  const blackFlashFrames = stingFrames > 0 ? 4 : 0;
  const stingPlusFlashEnd = stingFrames + blackFlashFrames;
  cursor += stingPlusFlashEnd;

  const sceneRanges: Array<{ from: number; durationInFrames: number }> = [];
  for (const s of scenes) {
    let seconds: number;
    if (typeof s.duration_seconds === "number" && s.duration_seconds > 0) {
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
      {/* Continuous music bed — loops if shorter than the video.
          Volume is automatically lower under the intro sting since the
          sting's audio peaks above it. */}
      <Audio src={staticFile(music_bed_file)} volume={music_bed_volume} loop />

      {/* Optional intro sting + hard-cut black flash */}
      {intro_sting_audio ? (
        <>
          <Sequence from={0} durationInFrames={stingFrames}>
            <IntroSting
              audioFile={intro_sting_audio}
              channelName={channel_name}
              durationInFrames={stingFrames}
            />
          </Sequence>
          <Sequence from={stingFrames} durationInFrames={blackFlashFrames}>
            <AbsoluteFill style={{ background: "black" }} />
          </Sequence>
        </>
      ) : null}

      {/* Story scenes */}
      {scenes.map((scene, i) => {
        const range = sceneRanges[i];
        const type = classifyScene(scene, i, scenes.length);
        const country = inferCountry(scene);
        const preset = presetFor(country);

        const prevCountry = i > 0 ? inferCountry(scenes[i - 1]) : undefined;
        const startPreset: CameraPreset = prevCountry
          ? presetFor(prevCountry)
          : WORLD;
        const endPreset = preset;

        return (
          <Sequence key={i} from={range.from} durationInFrames={range.durationInFrames}>
            <SceneInner
              scene={scene}
              type={type}
              country={country}
              startPreset={startPreset}
              endPreset={endPreset}
              durationInFrames={range.durationInFrames}
              worldTickers={world_tickers}
              storyDate={story_date}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

// Helper exposed for Root.tsx so the composition's durationInFrames
// can be derived from the script's scenes (+ optional intro sting).
export function totalDurationInFrames(props: VideoScriptProps, fps: number): number {
  let total = 0;
  if (props.intro_sting_audio) {
    total += Math.round((props.intro_sting_seconds || 3) * fps) + 4; // sting + black flash
  }
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
