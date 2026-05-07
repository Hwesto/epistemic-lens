// Big bold opening hook with a typewriter-ish reveal.

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const TitleCard: React.FC<{
  text: string; // multi-line; \n separates
  storyDate?: string;
}> = ({ text, storyDate }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const lines = text.split("\n");
  // Snappy fade — full opacity by frame 4 (~130ms) to preserve TikTok hook
  const fadeIn = spring({ frame, fps, config: { damping: 200, stiffness: 220, mass: 0.4 } });

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        zIndex: 40,
      }}
    >
      <div
        style={{
          padding: 60,
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.0) 0%, rgba(0,0,0,0.7) 50%, rgba(0,0,0,0.0) 100%)",
          opacity: fadeIn,
          maxWidth: "92%",
        }}
      >
        {lines.map((line, i) => {
          const charDelay = i * 2; // very small stagger so all lines visible early
          const lineFade = interpolate(
            frame - charDelay,
            [0, 5],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          );
          return (
            <div
              key={i}
              style={{
                color: "white",
                fontFamily:
                  "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif",
                fontSize: 110,
                fontWeight: 900,
                lineHeight: 1.05,
                letterSpacing: "-0.02em",
                textShadow: "0 4px 20px rgba(0,0,0,0.85)",
                marginBottom: i < lines.length - 1 ? 12 : 0,
                opacity: lineFade,
                transform: `translateY(${interpolate(lineFade, [0, 1], [22, 0])}px)`,
              }}
            >
              {line}
            </div>
          );
        })}
        {storyDate ? (
          <div
            style={{
              color: "#ffb627",
              fontSize: 32,
              fontWeight: 700,
              letterSpacing: "0.25em",
              marginTop: 36,
              opacity: fadeIn,
            }}
          >
            {storyDate}
          </div>
        ) : null}
      </div>
    </div>
  );
};
