// Slides up from the bottom and shows the actual quoted headline.
// Stays on-screen during scenes that focus on a country.

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

type Props = {
  onScreenText: string; // multi-line; \n separates lines
  headlineQuoted?: string; // exact outlet headline (smaller, italicised)
};

export const QuoteCard: React.FC<Props> = ({ onScreenText, headlineQuoted }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const slide = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 90 },
  });
  const translateY = interpolate(slide, [0, 1], [320, 0]);
  const opacity = interpolate(slide, [0, 1], [0, 1]);

  const lines = onScreenText.split("\n");

  return (
    <div
      style={{
        position: "absolute",
        bottom: 200,
        left: 60,
        right: 60,
        zIndex: 30,
        transform: `translateY(${translateY}px)`,
        opacity,
      }}
    >
      <div
        style={{
          background: "linear-gradient(180deg, rgba(8,16,28,0.92) 0%, rgba(0,0,0,0.96) 100%)",
          padding: "32px 40px",
          borderRadius: 18,
          borderLeft: "8px solid #ffb627",
          boxShadow: "0 18px 60px rgba(0,0,0,0.55)",
        }}
      >
        {lines.map((line, i) => {
          // First line bigger, second line slightly smaller
          const isFirst = i === 0;
          return (
            <div
              key={i}
              style={{
                color: "white",
                fontFamily:
                  "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif",
                fontSize: isFirst ? 60 : 36,
                fontWeight: isFirst ? 900 : 700,
                lineHeight: 1.15,
                letterSpacing: isFirst ? "-0.01em" : "0.02em",
                marginTop: i === 0 ? 0 : 18,
                opacity: i === 0 ? 1 : 0.85,
              }}
            >
              {line}
            </div>
          );
        })}
        {headlineQuoted ? (
          <div
            style={{
              marginTop: 22,
              paddingTop: 18,
              borderTop: "1px solid rgba(255,255,255,0.18)",
              color: "#ffe4a6",
              fontSize: 22,
              fontStyle: "italic",
              fontFamily:
                "Georgia, 'Times New Roman', serif",
              lineHeight: 1.35,
            }}
          >
            “{headlineQuoted}”
          </div>
        ) : null}
      </div>
    </div>
  );
};
