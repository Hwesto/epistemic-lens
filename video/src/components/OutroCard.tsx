// Closing card with channel handle + CTA.

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const OutroCard: React.FC<{
  text: string;
  handle?: string;
}> = ({ text, handle = "@daily-framings" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fade = spring({ frame, fps, config: { damping: 14 } });
  const ctaPulse = (frame % (fps * 0.8)) / (fps * 0.8);
  const ctaScale = interpolate(ctaPulse, [0, 0.5, 1], [1, 1.06, 1]);

  const lines = text.split("\n");

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
        opacity: fade,
        zIndex: 50,
      }}
    >
      {lines.map((line, i) => (
        <div
          key={i}
          style={{
            color: "white",
            fontFamily: "Inter, system-ui, sans-serif",
            fontSize: i === 0 ? 90 : 56,
            fontWeight: 900,
            lineHeight: 1.1,
            marginBottom: 14,
            textShadow: "0 4px 16px rgba(0,0,0,0.85)",
          }}
        >
          {line}
        </div>
      ))}
      <div
        style={{
          marginTop: 60,
          background: "#ffb627",
          color: "#0a1929",
          padding: "26px 56px",
          borderRadius: 60,
          fontFamily: "Inter, system-ui, sans-serif",
          fontSize: 42,
          fontWeight: 900,
          letterSpacing: "0.05em",
          transform: `scale(${ctaScale})`,
          boxShadow: "0 12px 36px rgba(0,0,0,0.4)",
        }}
      >
        FOLLOW {handle.toUpperCase()}
      </div>
    </div>
  );
};
