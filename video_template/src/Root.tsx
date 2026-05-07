// Composition registry. The Python wrapper (render_video.py) calls
// `npx remotion render src/index.ts FramingVideo out/<name>.mp4
//   --props=<path-to-video_scripts/*.json>` so all inputs come in
// at render time.

import React from "react";
import { Composition } from "remotion";
import { FramingVideo, totalDurationInFrames } from "./FramingVideo";
import { VideoScriptProps } from "./types";

// A default props payload for `remotion studio` — used when previewing
// the template interactively (npm run dev). Real renders override this.
const defaultProps: VideoScriptProps = {
  video_id: "preview",
  story_date: "2026-05-06",
  story_title: "Preview",
  story_one_liner: "Preview composition",
  duration_seconds: 60,
  scenes: [
    {
      scene: 1,
      time: "0:00-0:05",
      voiceover: "Title hook",
      on_screen_text: "5 COUNTRIES.\n1 STORY.",
    },
    {
      scene: 2,
      time: "0:05-0:13",
      voiceover: "Setup",
      on_screen_text: "Today: the Strait of Hormuz",
    },
    {
      scene: 3,
      time: "0:13-0:22",
      voiceover: "USA",
      on_screen_text: "🇺🇸 USA: 'If they don't agree, the bombing starts'\nTrump, Truth Social",
      headline_quoted: "Trump warns 'much higher-level' bombing — Yonhap",
    },
    {
      scene: 4,
      time: "0:22-0:31",
      voiceover: "China",
      on_screen_text: "🇨🇳 CHINA: 'Blockade not in common interests'\nWang Yi, CGTN",
    },
    {
      scene: 5,
      time: "0:31-0:39",
      voiceover: "Russia",
      on_screen_text: "🇷🇺 RUSSIA: 'Tehran still holds the strategic edge'\nRT",
    },
    {
      scene: 6,
      time: "0:39-0:48",
      voiceover: "Iran",
      on_screen_text: "🇮🇷 IRAN: 'Compliance impossible'\nPezeshkian, via Republic World",
    },
    {
      scene: 7,
      time: "0:48-0:55",
      voiceover: "Pakistan",
      on_screen_text: "🇵🇰 PAKISTAN: 'Ferrying proposals between the sides'\nSydney Morning Herald",
    },
    {
      scene: 8,
      time: "0:55-1:00",
      voiceover: "Outro",
      on_screen_text: "Same news. Five stories.\nDaily framings. Follow.",
    },
  ],
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="FramingVideo"
        component={FramingVideo as any}
        // Duration is derived from the props' scenes; we register a
        // sensible default and let the renderer override per-render.
        durationInFrames={totalDurationInFrames(defaultProps, 30)}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={defaultProps}
        calculateMetadata={({ props }) => ({
          durationInFrames: totalDurationInFrames(
            props as VideoScriptProps,
            30,
          ),
        })}
      />
    </>
  );
};
