// Paradox climax frame — TWO outlets shown SIDE BY SIDE with their
// receipt headlines, divided by a "BOTH AGREE" bar. This is the
// moment the video earns its "could every one be telling the truth?"
// question.
//
// Triggered by the script's paradox scene. Pass the two outlets and
// their exact-headline quotes. Animates in: top half drops down, bottom
// half rises up, "BOTH AGREE" bar slams in horizontally.

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

type Side = {
  flag: string;
  outlet: string;
  quote: string;
  accent_color?: string;
};

type Props = {
  top: Side;
  bottom: Side;
  middle_label?: string;
};

export const ParadoxCard: React.FC<Props> = ({
  top,
  bottom,
  middle_label = "BOTH AGREE",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Top drops in from above, bottom rises from below, with stagger.
  const topSpring = spring({
    frame: Math.max(0, frame - 3),
    fps,
    config: { damping: 14, stiffness: 100 },
  });
  const bottomSpring = spring({
    frame: Math.max(0, frame - 8),
    fps,
    config: { damping: 14, stiffness: 100 },
  });
  // Middle "BOTH AGREE" bar slams in horizontally last
  const middleSpring = spring({
    frame: Math.max(0, frame - 18),
    fps,
    config: { damping: 12, stiffness: 130 },
  });

  const topY = interpolate(topSpring, [0, 1], [-280, 0]);
  const bottomY = interpolate(bottomSpring, [0, 1], [280, 0]);
  const middleScale = interpolate(middleSpring, [0, 1], [0.5, 1]);

  return (
    <>
      {/* Top half — first outlet */}
      <div
        style={{
          position: "absolute",
          top: 130,
          left: 50,
          right: 50,
          minHeight: 540,
          background:
            top.accent_color ||
            "linear-gradient(180deg, rgba(15,20,40,0.96) 0%, rgba(5,10,25,0.98) 100%)",
          borderRadius: 22,
          border: "3px solid rgba(255,255,255,0.12)",
          boxShadow: "0 22px 60px rgba(0,0,0,0.7)",
          padding: "32px 40px",
          transform: `translateY(${topY}px)`,
          opacity: topSpring,
          zIndex: 30,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", marginBottom: 18 }}>
          <span style={{ fontSize: 70, marginRight: 16 }}>{top.flag}</span>
          <span
            style={{
              color: "#ffb627",
              fontSize: 32,
              fontWeight: 900,
              fontFamily: "Inter, system-ui",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
            }}
          >
            {top.outlet}
          </span>
        </div>
        <div
          style={{
            color: "white",
            fontFamily: "Georgia, 'Times New Roman', serif",
            fontSize: 50,
            fontWeight: 700,
            lineHeight: 1.16,
            letterSpacing: "-0.01em",
          }}
        >
          <span style={{ color: "#ffb627" }}>“</span>
          {top.quote}
          <span style={{ color: "#ffb627" }}>”</span>
        </div>
      </div>

      {/* Middle "BOTH AGREE" bar */}
      <div
        style={{
          position: "absolute",
          top: 880,
          left: 50,
          right: 50,
          height: 90,
          background:
            "linear-gradient(90deg, rgba(220,30,40,1) 0%, rgba(255,80,30,1) 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 14,
          boxShadow: "0 8px 28px rgba(220,30,40,0.55)",
          transform: `scale(${middleScale})`,
          opacity: middleSpring,
          zIndex: 32,
        }}
      >
        <div
          style={{
            color: "white",
            fontFamily: "Inter, system-ui",
            fontSize: 46,
            fontWeight: 900,
            letterSpacing: "0.22em",
            textShadow: "0 2px 6px rgba(0,0,0,0.45)",
          }}
        >
          {middle_label}
        </div>
      </div>

      {/* Bottom half — second outlet */}
      <div
        style={{
          position: "absolute",
          top: 1010,
          left: 50,
          right: 50,
          minHeight: 540,
          background:
            bottom.accent_color ||
            "linear-gradient(180deg, rgba(15,20,40,0.96) 0%, rgba(5,10,25,0.98) 100%)",
          borderRadius: 22,
          border: "3px solid rgba(255,255,255,0.12)",
          boxShadow: "0 22px 60px rgba(0,0,0,0.7)",
          padding: "32px 40px",
          transform: `translateY(${bottomY}px)`,
          opacity: bottomSpring,
          zIndex: 30,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", marginBottom: 18 }}>
          <span style={{ fontSize: 70, marginRight: 16 }}>{bottom.flag}</span>
          <span
            style={{
              color: "#ffb627",
              fontSize: 32,
              fontWeight: 900,
              fontFamily: "Inter, system-ui",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
            }}
          >
            {bottom.outlet}
          </span>
        </div>
        <div
          style={{
            color: "white",
            fontFamily: "Georgia, 'Times New Roman', serif",
            fontSize: 50,
            fontWeight: 700,
            lineHeight: 1.16,
            letterSpacing: "-0.01em",
          }}
        >
          <span style={{ color: "#ffb627" }}>“</span>
          {bottom.quote}
          <span style={{ color: "#ffb627" }}>”</span>
        </div>
      </div>
    </>
  );
};
