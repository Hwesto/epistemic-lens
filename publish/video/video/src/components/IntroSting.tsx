// Intro sting — 3 seconds, plays user-provided audio with a logo flash
// + channel name. Designed to be visually distinctive enough that
// returning viewers recognise the channel before the first frame of
// the actual story.

import React from "react";
import { Audio, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

type Props = {
  audioFile: string;          // file in public/, e.g. "intro_sting.mp3"
  channelName: string;        // big bold text, e.g. "DAILY FRAMINGS"
  durationInFrames: number;
};

export const IntroSting: React.FC<Props> = ({ audioFile, channelName, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Three-stage animation:
  //  0   -> 12 frames: logo zooms in (anticipation), background dark
  //  12  -> 30 frames: bass-drop reveal, channel name punches in
  //  30  -> end:       hold + slight zoom-out for transition
  const stage = frame < 12 ? "anticipation" : frame < 30 ? "drop" : "hold";

  // Background: deep red+black gradient that breathes
  const bgPulse = (frame % (fps * 1.5)) / (fps * 1.5);
  const bgIntensity = interpolate(bgPulse, [0, 1], [0.7, 1.0]);

  // Logo scale via spring
  const logoScale = spring({
    frame,
    fps,
    config: { damping: 8, stiffness: 80, mass: 0.8 },
  });

  // Channel name fade-in starting at frame 12
  const nameOpacity = interpolate(frame, [12, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const nameTranslate = interpolate(frame, [12, 24], [40, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Subtitle fade
  const subtitleOpacity = interpolate(frame, [22, 32], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Slight outro zoom on the last 18 frames so transition to title scene
  // doesn't feel like a hard cut.
  const exitScale = interpolate(
    frame,
    [durationInFrames - 18, durationInFrames],
    [1, 1.12],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: `radial-gradient(circle at center, rgba(70,${
          Math.floor(20 * bgIntensity)
        },${Math.floor(30 * bgIntensity)},1) 0%, rgba(15,5,8,1) 70%, #000 100%)`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      <Audio src={staticFile(audioFile)} />

      {/* Logo: a stylised concentric "broadcasting" mark */}
      <div
        style={{
          transform: `scale(${logoScale * exitScale})`,
          marginBottom: 40,
          width: 220,
          height: 220,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg width="220" height="220" viewBox="0 0 220 220">
          <defs>
            <radialGradient id="core" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#fff" stopOpacity="1" />
              <stop offset="60%" stopColor="#ffd166" stopOpacity="1" />
              <stop offset="100%" stopColor="#b07000" stopOpacity="1" />
            </radialGradient>
          </defs>
          {/* Outer broadcasting rings */}
          {[110, 90, 72].map((r, i) => (
            <circle
              key={r}
              cx="110"
              cy="110"
              r={r}
              fill="none"
              stroke="#ffb627"
              strokeWidth={3 - i * 0.5}
              opacity={0.5 - i * 0.1}
            />
          ))}
          {/* Core */}
          <circle cx="110" cy="110" r="48" fill="url(#core)" />
          {/* Tick mark — gives it a 'launch' / 'broadcast' feel */}
          <text
            x="110"
            y="125"
            textAnchor="middle"
            fontSize="56"
            fontWeight="900"
            fill="#0a0a0a"
            fontFamily="Inter, system-ui"
          >
            ◉
          </text>
        </svg>
      </div>

      {/* Channel name */}
      <div
        style={{
          color: "white",
          fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif",
          fontSize: 100,
          fontWeight: 900,
          letterSpacing: "0.02em",
          opacity: nameOpacity,
          transform: `translateY(${nameTranslate}px) scale(${exitScale})`,
          textShadow: "0 6px 28px rgba(0,0,0,0.85)",
          textAlign: "center",
          lineHeight: 1.0,
        }}
      >
        {channelName}
      </div>

      {/* Subtitle / tagline */}
      <div
        style={{
          color: "#ffb627",
          fontFamily: "Inter, system-ui",
          fontSize: 32,
          fontWeight: 800,
          letterSpacing: "0.35em",
          opacity: subtitleOpacity,
          marginTop: 24,
          transform: `scale(${exitScale})`,
        }}
      >
        SAME NEWS · FIVE STORIES
      </div>
    </div>
  );
};
