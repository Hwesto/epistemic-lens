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

// Camera dolly that arrives FAST. Default `dollyFraction = 0.30` means
// the camera completes its full pan/zoom by 30% of the scene's duration,
// then sits still for the remaining 70%. This means the voiceover lands
// on a SETTLED frame instead of mid-flight — much less "flying through
// continents while speaking" feel.
//
// Pass `dollyFraction = 1.0` to restore the slow cinematic dolly across
// the whole scene (used for title/world/outro scenes that want motion).
export function useCameraDolly(
  start: CameraPreset,
  end: CameraPreset,
  durationInFrames: number,
  dollyFraction: number = 0.30,
): CameraState {
  const frame = useCurrentFrame();
  const dollyEndFrame = Math.max(1, Math.round(durationInFrames * dollyFraction));
  const t = interpolate(frame, [0, dollyEndFrame], [0, 1], {
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
