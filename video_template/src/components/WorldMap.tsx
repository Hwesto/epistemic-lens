// Simple SVG world map background with smooth pan/zoom.
// Uses an embedded simplified Equirectangular projection so we have
// no external data-fetch latency at render time.

import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { CameraPreset } from "../cameraPresets";

// Equirectangular: x = (lon + 180) / 360 * width, y = (90 - lat) / 180 * height
// for an 1800×900 base canvas.
const BASE_W = 1800;
const BASE_H = 900;
function lonLatToXY(lon: number, lat: number): [number, number] {
  return [((lon + 180) / 360) * BASE_W, ((90 - lat) / 180) * BASE_H];
}

// Inline simplified continent SVG paths (very rough — purpose is a
// recognisable map silhouette, not cartographic accuracy). Loaded once.
// Source: simplified from Natural Earth public-domain data.
const LAND_PATH = `
M 280 180 L 350 130 L 470 110 L 550 130 L 600 180 L 650 230 L 680 290 L 700 350
L 700 410 L 680 460 L 640 510 L 600 540 L 560 560 L 480 560 L 410 540 L 360 500
L 320 450 L 290 380 L 280 300 Z
M 720 200 L 800 150 L 920 130 L 1050 145 L 1180 170 L 1280 220 L 1320 280 L 1300 360
L 1240 420 L 1200 480 L 1180 560 L 1150 620 L 1120 680 L 1080 720 L 1020 760
L 960 800 L 900 820 L 840 800 L 780 760 L 740 700 L 720 640 L 700 560 L 680 480
L 700 380 L 720 280 Z
M 1340 280 L 1400 240 L 1480 220 L 1560 240 L 1620 280 L 1660 340 L 1660 420
L 1620 480 L 1560 520 L 1480 540 L 1400 520 L 1340 480 L 1300 420 L 1300 340 Z
M 1500 600 L 1560 580 L 1620 600 L 1660 660 L 1660 720 L 1620 760 L 1560 760
L 1500 720 L 1480 660 Z
M 100 480 L 180 460 L 260 480 L 320 540 L 320 620 L 280 700 L 220 740
L 160 720 L 100 660 L 80 580 Z
`;

export const WorldMapBackground: React.FC<{
  startPreset: CameraPreset;
  endPreset: CameraPreset;
  durationInFrames: number;
}> = ({ startPreset, endPreset, durationInFrames }) => {
  const frame = useCurrentFrame();

  const t = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });
  const lon = interpolate(t, [0, 1], [startPreset.center[0], endPreset.center[0]]);
  const lat = interpolate(t, [0, 1], [startPreset.center[1], endPreset.center[1]]);
  const zoom = interpolate(t, [0, 1], [startPreset.zoom, endPreset.zoom], {
    easing: (x) => 1 - Math.pow(1 - x, 3), // ease-out cubic
  });

  const [cx, cy] = lonLatToXY(lon, lat);

  // 9:16 viewport math: we render BASE_W x BASE_H but only show a
  // portrait-aspect slice centered on the current camera.
  const viewWidthRatio = 1080 / 1920; // 0.5625
  const viewW = BASE_W / zoom;
  const viewH = viewW / viewWidthRatio;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background:
          "radial-gradient(ellipse at center, #0a1929 0%, #050b14 70%, #000 100%)",
        overflow: "hidden",
      }}
    >
      <svg
        width="100%"
        height="100%"
        viewBox={`${cx - viewW / 2} ${cy - viewH / 2} ${viewW} ${viewH}`}
        preserveAspectRatio="xMidYMid slice"
        style={{ position: "absolute", inset: 0 }}
      >
        {/* Latitude grid lines */}
        {[-60, -30, 0, 30, 60].map((lat) => {
          const [, y] = lonLatToXY(0, lat);
          return (
            <line
              key={`lat${lat}`}
              x1={0}
              y1={y}
              x2={BASE_W}
              y2={y}
              stroke="#1a3553"
              strokeWidth={1}
              opacity={0.3}
            />
          );
        })}
        {/* Longitude grid lines */}
        {[-120, -60, 0, 60, 120].map((lon) => {
          const [x] = lonLatToXY(lon, 0);
          return (
            <line
              key={`lon${lon}`}
              x1={x}
              y1={0}
              x2={x}
              y2={BASE_H}
              stroke="#1a3553"
              strokeWidth={1}
              opacity={0.3}
            />
          );
        })}
        {/* Land masses */}
        <path d={LAND_PATH} fill="#0f2a44" stroke="#1f4a78" strokeWidth={2} />
      </svg>

      {/* Subtle vignette */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.55) 100%)",
          pointerEvents: "none",
        }}
      />
    </div>
  );
};
