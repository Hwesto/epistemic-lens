// World map with REAL country shapes from world-atlas TopoJSON.
// Uses react-simple-maps + d3-geo equirectangular projection. Pans/zooms
// smoothly between camera presets. Highlights the active country.

import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { ComposableMap, Geographies, Geography } from "react-simple-maps";
import { CameraPreset } from "../cameraPresets";

// JSON import — bundled into the Remotion build at compile time.
import worldData from "../data/world-110m.json";

// Map our short country codes to ISO 3166 numeric IDs (which is how
// world-atlas/countries-110m.json identifies geometries via `id`).
// Used to highlight the currently-focused country.
const ISO_NUMERIC: Record<string, string> = {
  us: "840", ca: "124", mx: "484",
  br: "076", ar: "032",
  uk: "826", fr: "250", de: "276", it: "380", es: "724", va: "336",
  ru: "643", ua: "804", ge: "268", hu: "348",
  ir: "364", il: "376", lb: "422", sa: "682", ae: "784", qa: "634",
  tr: "792", eg: "818", iq: "368", sy: "760",
  in: "356", pk: "586",
  cn: "156", jp: "392", kr: "410", kp: "408", tw: "158",
  id: "360", ph: "608",
  au: "036",
  za: "710", ke: "404", ng: "566",
};

export const WorldMapBackground: React.FC<{
  startPreset: CameraPreset;
  endPreset: CameraPreset;
  durationInFrames: number;
  highlightCountry?: string; // 2-letter code, e.g. "us"
}> = ({ startPreset, endPreset, durationInFrames, highlightCountry }) => {
  const frame = useCurrentFrame();

  const t = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: (x) => 1 - Math.pow(1 - x, 3), // ease-out cubic
  });
  const lon = interpolate(t, [0, 1], [startPreset.center[0], endPreset.center[0]]);
  const lat = interpolate(t, [0, 1], [startPreset.center[1], endPreset.center[1]]);
  const zoom = interpolate(t, [0, 1], [startPreset.zoom, endPreset.zoom]);

  const highlightId = highlightCountry ? ISO_NUMERIC[highlightCountry] : null;

  // 9:16 viewport. Equirectangular default scale is 152.63 for a 360x180
  // world; we multiply by zoom to focus.
  const baseScale = 200;
  const scale = baseScale * zoom;

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
      <ComposableMap
        projection="geoEquirectangular"
        projectionConfig={{ center: [lon, lat], scale }}
        width={1080}
        height={1920}
        style={{ width: "100%", height: "100%" }}
      >
        {/* Latitude/longitude graticule */}
        <Graticule />
        <Geographies geography={worldData as any}>
          {({ geographies }) =>
            geographies.map((geo: any) => {
              const isHighlighted =
                highlightId && String(geo.id) === highlightId;
              return (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  style={{
                    default: {
                      fill: isHighlighted ? "#3b6fa6" : "#0f2a44",
                      stroke: isHighlighted ? "#ffd166" : "#1f4a78",
                      strokeWidth: isHighlighted ? 2.0 : 0.6,
                      outline: "none",
                    },
                    hover: { fill: "#3b6fa6", outline: "none" },
                    pressed: { fill: "#3b6fa6", outline: "none" },
                  }}
                />
              );
            })
          }
        </Geographies>
      </ComposableMap>

      {/* Subtle vignette to draw the eye to the centre */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at center, transparent 35%, rgba(0,0,0,0.6) 100%)",
          pointerEvents: "none",
        }}
      />
    </div>
  );
};

// Simple latitude/longitude graticule lines under the countries.
const Graticule: React.FC = () => (
  <g style={{ pointerEvents: "none" }}>
    {[-60, -30, 0, 30, 60].map((lat) => (
      <line
        key={`lat${lat}`}
        x1={-180}
        y1={lat}
        x2={180}
        y2={lat}
        stroke="#142a45"
        strokeWidth={0.4}
        opacity={0.4}
      />
    ))}
  </g>
);
