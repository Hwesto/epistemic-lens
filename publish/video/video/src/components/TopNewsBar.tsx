// Top news ticker bar — fixed strip at the top of every scene that
// cycles through the script's `world_tickers` showing each as a
// FULL, READABLE "OTHER STORIES TODAY" item. Replaces the cluttered
// floating tickers from v0.7.0.
//
// Design philosophy (after Gemini critique): if a piece of information
// is on screen, it must be readable in <0.5s. Crammed 22px tickers
// over the map were noise. A single big ticker at the top, cycled
// every ~3.5s, is signal.
//
// Each ticker shows: animated "live" red dot + flag + country name +
// full headline. Slides in from the right with a small bounce.

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { WorldTicker } from "../types";
import { presetFor } from "../cameraPresets";

type Props = {
  tickers: WorldTicker[];
  // Skip this country's ticker — it's the focal country of the scene
  // and would be redundant in the bar.
  skipCountry?: string;
  totalDurationInFrames: number;
  // Show/hide the bar entirely (used for title and outro scenes)
  visible?: boolean;
};

const SECONDS_PER_TICKER = 3.5;

export const TopNewsBar: React.FC<Props> = ({
  tickers,
  skipCountry,
  totalDurationInFrames,
  visible = true,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const visibleTickers = (tickers || []).filter(
    (t) => !skipCountry || t.country_code !== skipCountry
  );
  if (!visible || visibleTickers.length === 0) return null;

  const framesPerTicker = SECONDS_PER_TICKER * fps;
  const idx = Math.floor(frame / framesPerTicker) % visibleTickers.length;
  const localFrame = frame - idx * framesPerTicker;

  const t = visibleTickers[idx];
  const preset = presetFor(t.country_code);

  // Slide-in from right with bounce
  const slide = spring({
    frame: localFrame,
    fps,
    config: { damping: 14, stiffness: 110 },
  });
  const translateX = interpolate(slide, [0, 1], [200, 0]);

  // Cross-fade out near end of each ticker's slot
  const fadeOut = interpolate(
    localFrame,
    [framesPerTicker - 8, framesPerTicker],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const opacity = Math.min(slide, fadeOut);

  // Pulsing red "live" dot
  const dotPhase = (frame % (fps * 1.4)) / (fps * 1.4);
  const dotPulse = 0.6 + 0.4 * Math.abs(Math.sin(dotPhase * Math.PI));

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        height: 92,
        background:
          "linear-gradient(180deg, rgba(0,0,0,0.92) 0%, rgba(8,16,28,0.95) 100%)",
        borderBottom: "3px solid #ffb627",
        boxShadow: "0 2px 14px rgba(0,0,0,0.6)",
        display: "flex",
        alignItems: "center",
        padding: "0 22px",
        zIndex: 50,
        opacity,
      }}
    >
      {/* "LIVE" badge with pulsing dot */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          marginRight: 18,
          padding: "8px 14px",
          background: "rgba(220,30,40,0.88)",
          borderRadius: 6,
        }}
      >
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: "white",
            opacity: dotPulse,
            marginRight: 8,
          }}
        />
        <div
          style={{
            color: "white",
            fontSize: 18,
            fontWeight: 900,
            letterSpacing: "0.18em",
            fontFamily: "Inter, system-ui",
          }}
        >
          LIVE
        </div>
      </div>

      {/* Country flag + label */}
      <div
        style={{
          fontSize: 36,
          marginRight: 10,
          transform: `translateX(${translateX * 0.3}px)`,
        }}
      >
        {preset.flag}
      </div>
      <div
        style={{
          color: "#ffb627",
          fontSize: 18,
          fontWeight: 900,
          letterSpacing: "0.18em",
          marginRight: 16,
          fontFamily: "Inter, system-ui",
          textTransform: "uppercase",
          transform: `translateX(${translateX * 0.5}px)`,
        }}
      >
        {preset.label}
      </div>

      {/* Headline */}
      <div
        style={{
          color: "white",
          fontSize: 28,
          fontWeight: 700,
          fontFamily: "Inter, system-ui",
          flex: 1,
          overflow: "hidden",
          whiteSpace: "nowrap",
          textOverflow: "ellipsis",
          textShadow: "0 1px 3px rgba(0,0,0,0.95)",
          transform: `translateX(${translateX}px)`,
        }}
      >
        {t.headline}
      </div>
    </div>
  );
};
