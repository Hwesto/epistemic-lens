// Ambient world tickers — small floating headlines positioned over
// non-focal countries on the map. Reinforces the "global newsroom"
// feel: while the camera focuses on USA, you can see Brazil and Japan
// also reporting today, with their actual headlines.
//
// Pulls from script.world_tickers (hand-authored from the day's
// snapshot data, or auto-populated by render_video.py from latest pull).
//
// Tickers stagger their fade-in/out so the screen doesn't feel busy,
// and they slowly drift up to feel "alive" without distracting.

import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { WorldTicker } from "../types";
import { presetFor } from "../cameraPresets";

type Props = {
  tickers: WorldTicker[];
  // Shared with WorldMap so tickers stay anchored to the same projected
  // coordinates even when the camera dollies.
  cameraLon: number;
  cameraLat: number;
  cameraZoom: number;
  focalCountry?: string; // skip ticker for this country
  totalDurationInFrames: number;
};

// Same equirectangular projection as WorldMap (BASE_W=1800, BASE_H=900)
// converted to viewport pixel offsets.
const BASE_W = 1080; // matches projectionConfig in WorldMap
const VIEW_W = 1080;
const VIEW_H = 1920;
const VIEWPORT_W_RATIO = VIEW_W / VIEW_H; // 0.5625 portrait

function projectLonLat(
  lon: number,
  lat: number,
  cameraLon: number,
  cameraLat: number,
  zoom: number
): { x: number; y: number; visible: boolean } {
  // Equirectangular: 1 degree of longitude at zoom=1 is BASE_W/360 px
  const baseScale = 200 * zoom; // matches WorldMap baseScale
  const dx = (lon - cameraLon) * baseScale * (Math.PI / 180);
  const dy = -(lat - cameraLat) * baseScale * (Math.PI / 180);
  const x = VIEW_W / 2 + dx;
  const y = VIEW_H / 2 + dy;
  // Hide tickers that fall outside the viewport (with some margin)
  const visible = x > -200 && x < VIEW_W + 200 && y > -100 && y < VIEW_H + 100;
  return { x, y, visible };
}

export const WorldTickers: React.FC<Props> = ({
  tickers,
  cameraLon,
  cameraLat,
  cameraZoom,
  focalCountry,
  totalDurationInFrames,
}) => {
  const frame = useCurrentFrame();
  if (!tickers || tickers.length === 0) return null;

  return (
    <>
      {tickers.map((t, idx) => {
        if (focalCountry && t.country_code === focalCountry) return null;
        const preset = presetFor(t.country_code);
        const proj = projectLonLat(
          preset.center[0],
          preset.center[1],
          cameraLon,
          cameraLat,
          cameraZoom,
        );
        if (!proj.visible) return null;

        // Stagger fade-in by ticker index: each ticker starts 8 frames after
        // the previous one. Each visible for ~70 frames (~2.3s) then fades.
        const startFrame = idx * 8;
        const visibleFrames = 90;
        const localFrame = frame - startFrame;
        const fadeIn = interpolate(localFrame, [0, 12], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        // Slow drift up
        const driftY = interpolate(localFrame, [0, 200], [0, -30], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        // Persistent fade-loop: each ticker pulses every ~5s
        const cyclePhase = (localFrame % 150) / 150;
        const cycleOpacity = interpolate(cyclePhase, [0, 0.1, 0.85, 1], [0, 1, 1, 0]);
        const opacity = fadeIn * cycleOpacity * 0.85;

        return (
          <div
            key={`${t.country_code}-${idx}`}
            style={{
              position: "absolute",
              left: proj.x,
              top: proj.y + driftY,
              transform: "translate(-50%, -50%)",
              pointerEvents: "none",
              zIndex: 14,
              opacity,
            }}
          >
            <div
              style={{
                background: "rgba(0,0,0,0.72)",
                border: "1px solid rgba(255, 182, 39, 0.25)",
                padding: "6px 12px",
                borderRadius: 8,
                fontFamily: "Inter, system-ui, sans-serif",
                fontSize: 16,
                fontWeight: 600,
                color: "#cce0ff",
                whiteSpace: "nowrap",
                maxWidth: 320,
                overflow: "hidden",
                textOverflow: "ellipsis",
                textShadow: "0 1px 2px rgba(0,0,0,0.9)",
              }}
            >
              <span style={{ marginRight: 6 }}>{preset.flag}</span>
              <span
                style={{
                  fontSize: 11,
                  letterSpacing: "0.15em",
                  color: "#ffb627",
                  fontWeight: 800,
                  marginRight: 6,
                }}
              >
                {preset.label}
              </span>
              <span style={{ fontSize: 14, fontWeight: 500 }}>
                {t.headline.length > 60
                  ? t.headline.slice(0, 58) + "…"
                  : t.headline}
              </span>
            </div>
          </div>
        );
      })}
    </>
  );
};
