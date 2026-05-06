// Shared camera-dolly interpolation hook — used by both WorldMap and
// WorldTickers so the tickers stay in lockstep with the panning map.
// Both components are inside the same Sequence so they see the same
// sequence-local frame, which makes their interpolation outputs match.

import { interpolate, useCurrentFrame } from "remotion";
import { CameraPreset } from "./cameraPresets";

export type CameraState = {
  lon: number;
  lat: number;
  zoom: number;
};

export function useCameraDolly(
  start: CameraPreset,
  end: CameraPreset,
  durationInFrames: number,
): CameraState {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: (x) => 1 - Math.pow(1 - x, 3),
  });
  return {
    lon: interpolate(t, [0, 1], [start.center[0], end.center[0]]),
    lat: interpolate(t, [0, 1], [start.center[1], end.center[1]]),
    zoom: interpolate(t, [0, 1], [start.zoom, end.zoom]),
  };
}
