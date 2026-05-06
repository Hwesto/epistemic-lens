// Pulsing country pin overlay — appears centered on the screen since
// the WorldMap already pans to the country. Adds a soft halo + flag.

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const CountryPin: React.FC<{ flag: string; label: string }> = ({
  flag,
  label,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scaleIn = spring({ frame, fps, config: { damping: 12 } });
  // Continuous pulse ring
  const pulse = (frame % (fps * 1.5)) / (fps * 1.5);
  const ringOpacity = interpolate(pulse, [0, 1], [0.6, 0]);
  const ringScale = interpolate(pulse, [0, 1], [1, 2.6]);

  return (
    <div
      style={{
        position: "absolute",
        top: "50%",
        left: "50%",
        transform: `translate(-50%, -50%) scale(${scaleIn})`,
        zIndex: 20,
      }}
    >
      {/* Pulse ring */}
      <div
        style={{
          position: "absolute",
          width: 180,
          height: 180,
          borderRadius: "50%",
          border: "4px solid #ffb627",
          left: -90,
          top: -90,
          transform: `scale(${ringScale})`,
          opacity: ringOpacity,
        }}
      />
      {/* Pin core */}
      <div
        style={{
          width: 110,
          height: 110,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, #ffd166 0%, #ffb627 60%, #b07000 100%)",
          boxShadow: "0 0 50px 8px rgba(255, 183, 39, 0.55)",
          left: -55,
          top: -55,
          position: "absolute",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 60,
        }}
      >
        {flag}
      </div>
      {/* Label below */}
      <div
        style={{
          position: "absolute",
          top: 70,
          left: -200,
          width: 400,
          textAlign: "center",
          color: "white",
          fontSize: 28,
          fontWeight: 800,
          letterSpacing: "0.15em",
          textShadow: "0 2px 8px rgba(0,0,0,0.85)",
        }}
      >
        {label}
      </div>
    </div>
  );
};
