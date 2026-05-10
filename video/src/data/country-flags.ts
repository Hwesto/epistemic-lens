// Map from on-screen-text patterns to ISO 3166-1 alpha-2 country codes.
// Used by FramingVideo.inferCountry() when a scene's `country` field is
// not explicit. Each entry matches either the unicode flag emoji or a
// word-boundary text mention. Order matters only when patterns overlap;
// keep more-specific patterns earlier.
//
// To extend: add a new tuple. Keep entries one-per-line for grep.

export const COUNTRY_FLAG_MAP: Array<[RegExp, string]> = [
  [/🇺🇸|\bUSA\b|\bUnited States\b/, "us"],
  [/🇬🇧|\bUK\b|\bBritain\b/, "uk"],
  [/🇫🇷|\bFrance\b/, "fr"],
  [/🇩🇪|\bGermany\b/, "de"],
  [/🇮🇹|\bItaly\b/, "it"],
  [/🇪🇸|\bSpain\b/, "es"],
  [/🇷🇺|\bRussia\b/, "ru"],
  [/🇺🇦|\bUkraine\b/, "ua"],
  [/🇮🇷|\bIran\b/, "ir"],
  [/🇮🇱|\bIsrael\b/, "il"],
  [/🇱🇧|\bLebanon\b/, "lb"],
  [/🇸🇦|\bSaudi\b/, "sa"],
  [/🇶🇦|\bQatar\b/, "qa"],
  [/🇪🇬|\bEgypt\b/, "eg"],
  [/🇹🇷|\bTurkey|Türkiye\b/, "tr"],
  [/🇮🇳|\bIndia\b/, "in"],
  [/🇵🇰|\bPakistan\b/, "pk"],
  [/🇨🇳|\bChina\b/, "cn"],
  [/🇯🇵|\bJapan\b/, "jp"],
  [/🇰🇷|\bSouth Korea\b/, "kr"],
  [/🇰🇵|\bNorth Korea\b/, "kp"],
  [/🇹🇼|\bTaiwan\b/, "tw"],
  [/🇮🇩|\bIndonesia\b/, "id"],
  [/🇵🇭|\bPhilippines\b/, "ph"],
  [/🇦🇺|\bAustralia\b/, "au"],
  [/🇨🇦|\bCanada\b/, "ca"],
  [/🇲🇽|\bMexico\b/, "mx"],
  [/🇧🇷|\bBrazil\b/, "br"],
  [/🇿🇦|\bSouth Africa\b/, "za"],
  [/🇰🇪|\bKenya\b/, "ke"],
  [/🇳🇬|\bNigeria\b/, "ng"],
  [/🇻🇦|\bVatican\b/, "va"],
  [/🇬🇪|\bGeorgia\b/, "ge"],
];
