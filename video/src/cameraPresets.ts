// Pre-defined "camera positions" on the world map.
// coordinates are [lon, lat] in degrees; zoom is 1.0 = whole world.
//
// Used by FramingVideo to interpolate between scenes. Every Scene
// optionally specifies a `country` field; we look it up here. Scenes
// without `country` show the WORLD overview.
//
// To add a country, just append to this map. The flag emoji is used
// in QuoteCard / pin labels; the [lon, lat] drives the camera dolly.

export type CameraPreset = {
  center: [number, number]; // [longitude, latitude]
  zoom: number; // 1.0 = world; 4.0 = country-level zoom
  flag: string;
  label: string;
};

export const WORLD: CameraPreset = {
  center: [0, 20],
  zoom: 1.0,
  flag: "🌍",
  label: "WORLD",
};

export const PRESETS: Record<string, CameraPreset> = {
  // North America
  us: { center: [-95, 38], zoom: 3.5, flag: "🇺🇸", label: "USA" },
  ca: { center: [-95, 55], zoom: 3, flag: "🇨🇦", label: "CANADA" },
  mx: { center: [-100, 23], zoom: 4, flag: "🇲🇽", label: "MEXICO" },
  // South America
  br: { center: [-50, -10], zoom: 3, flag: "🇧🇷", label: "BRAZIL" },
  ar: { center: [-65, -34], zoom: 3, flag: "🇦🇷", label: "ARGENTINA" },
  // Europe
  uk: { center: [-2, 54], zoom: 5, flag: "🇬🇧", label: "UK" },
  fr: { center: [2, 47], zoom: 5, flag: "🇫🇷", label: "FRANCE" },
  de: { center: [10, 51], zoom: 5, flag: "🇩🇪", label: "GERMANY" },
  it: { center: [12, 42], zoom: 5, flag: "🇮🇹", label: "ITALY" },
  es: { center: [-3, 40], zoom: 5, flag: "🇪🇸", label: "SPAIN" },
  va: { center: [12.45, 41.9], zoom: 7, flag: "🇻🇦", label: "VATICAN" },
  // Eastern Europe / FSU
  ru: { center: [60, 60], zoom: 2.5, flag: "🇷🇺", label: "RUSSIA" },
  ua: { center: [32, 49], zoom: 4, flag: "🇺🇦", label: "UKRAINE" },
  ge: { center: [43, 42], zoom: 5, flag: "🇬🇪", label: "GEORGIA" },
  hu: { center: [19, 47], zoom: 5, flag: "🇭🇺", label: "HUNGARY" },
  // Middle East
  ir: { center: [53, 32], zoom: 4, flag: "🇮🇷", label: "IRAN" },
  il: { center: [35, 31], zoom: 6, flag: "🇮🇱", label: "ISRAEL" },
  lb: { center: [36, 34], zoom: 6, flag: "🇱🇧", label: "LEBANON" },
  sa: { center: [45, 24], zoom: 4, flag: "🇸🇦", label: "SAUDI ARABIA" },
  ae: { center: [54, 24], zoom: 5, flag: "🇦🇪", label: "UAE" },
  qa: { center: [51.2, 25.3], zoom: 7, flag: "🇶🇦", label: "QATAR" },
  tr: { center: [35, 39], zoom: 4, flag: "🇹🇷", label: "TURKEY" },
  eg: { center: [30, 27], zoom: 4, flag: "🇪🇬", label: "EGYPT" },
  iq: { center: [44, 33], zoom: 5, flag: "🇮🇶", label: "IRAQ" },
  sy: { center: [38, 35], zoom: 5, flag: "🇸🇾", label: "SYRIA" },
  // South Asia
  in: { center: [78, 22], zoom: 3, flag: "🇮🇳", label: "INDIA" },
  pk: { center: [70, 30], zoom: 4, flag: "🇵🇰", label: "PAKISTAN" },
  // East Asia
  cn: { center: [105, 35], zoom: 2.5, flag: "🇨🇳", label: "CHINA" },
  jp: { center: [138, 36], zoom: 4, flag: "🇯🇵", label: "JAPAN" },
  kr: { center: [127, 36], zoom: 5, flag: "🇰🇷", label: "S. KOREA" },
  kp: { center: [127, 40], zoom: 5, flag: "🇰🇵", label: "N. KOREA" },
  tw: { center: [121, 24], zoom: 6, flag: "🇹🇼", label: "TAIWAN" },
  // SE Asia
  id: { center: [113, -2], zoom: 3, flag: "🇮🇩", label: "INDONESIA" },
  ph: { center: [122, 13], zoom: 4, flag: "🇵🇭", label: "PHILIPPINES" },
  // Oceania
  au: { center: [134, -25], zoom: 2.5, flag: "🇦🇺", label: "AUSTRALIA" },
  // Africa
  za: { center: [25, -29], zoom: 3, flag: "🇿🇦", label: "S. AFRICA" },
  ke: { center: [38, 0], zoom: 4, flag: "🇰🇪", label: "KENYA" },
  ng: { center: [8, 9], zoom: 3, flag: "🇳🇬", label: "NIGERIA" },
};

export function presetFor(code?: string): CameraPreset {
  if (!code) return WORLD;
  return PRESETS[code.toLowerCase()] || WORLD;
}
