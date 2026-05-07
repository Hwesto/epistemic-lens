// Slides up from the bottom. NEW v0.6.1 layout:
//   - Top:    SMALL country attribution row (flag + outlet name in caps)
//   - Middle: BIG hero quote — the actual headline as quoted text
//   - Bottom: SMALLER framing line — short label / context

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

type Props = {
  // Multi-line; \n separates the small framing label (line 1) and
  // the smaller attribution sub-line (line 2). Used as the bottom
  // smaller text below the hero quote.
  onScreenText: string;
  // The exact outlet quote — now the HERO of the card.
  headlineQuoted?: string;
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
  const framingLine = lines[0] ?? ""; // "🇮🇷 IRAN: 'A shameful defeat for the US'"
  const attribLine = lines[1] ?? "";  // "Khamenei, via Iran International"

  return (
    <div
      style={{
        position: "absolute",
        bottom: 160,
        left: 50,
        right: 50,
        zIndex: 30,
        transform: `translateY(${translateY}px)`,
        opacity,
      }}
    >
      <div
        style={{
          background: "linear-gradient(180deg, rgba(8,16,28,0.95) 0%, rgba(0,0,0,0.97) 100%)",
          padding: "32px 38px",
          borderRadius: 20,
          borderLeft: "10px solid #ffb627",
          boxShadow: "0 22px 70px rgba(0,0,0,0.6)",
        }}
      >
        {/* Top row: framing summary as small attribution-style header */}
        {framingLine ? (
          <div
            style={{
              color: "#ffd166",
              fontFamily:
                "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif",
              fontSize: 30,
              fontWeight: 800,
              letterSpacing: "0.02em",
              lineHeight: 1.2,
              marginBottom: headlineQuoted ? 18 : 0,
            }}
          >
            {framingLine}
          </div>
        ) : null}

        {/* HERO: the actual quoted headline. Larger, white, serif feel. */}
        {headlineQuoted ? (
          <div
            style={{
              color: "white",
              fontFamily: "Georgia, 'Times New Roman', serif",
              fontSize: 44,
              fontWeight: 700,
              lineHeight: 1.15,
              letterSpacing: "-0.005em",
              padding: "12px 0",
              borderTop: "1px solid rgba(255,255,255,0.18)",
              borderBottom: attribLine
                ? "1px solid rgba(255,255,255,0.18)"
                : "none",
            }}
          >
            <span style={{ color: "#ffb627", marginRight: 6 }}>“</span>
            {headlineQuoted}
            <span style={{ color: "#ffb627", marginLeft: 6 }}>”</span>
          </div>
        ) : null}

        {/* Bottom row: small attribution */}
        {attribLine ? (
          <div
            style={{
              marginTop: 14,
              color: "#9fb3cc",
              fontSize: 22,
              fontWeight: 600,
              fontFamily: "Inter, system-ui, sans-serif",
              letterSpacing: "0.04em",
              textTransform: "uppercase",
            }}
          >
            {attribLine}
          </div>
        ) : null}
      </div>
    </div>
  );
};
