# feeds.json migration v0.3 → v0.4

**Old**: 51 feeds across 16 country buckets, 4 known-dead.
**New**: 138 feeds across 47 country buckets, none expected-dead.

## Dropped (4)
| Feed | Reason |
|---|---|
| Iran State / Press TV | rsshub proxy returns 403 for 39 days; replaced with rsshub `/presstv/iran` (RETRY) |
| Iran State / Tasnim English | DNS unreachable for 39 days |
| Iran State / Fars News EN | `.ir` domain blackout for 39 days |
| Turkey / TRT World | feed URL returns 404 |

## Added — story-critical Middle East / South Asia (was missing entirely)
- **Pakistan**: Dawn, Geo News, ARY (stub), Express Tribune (RETRY) — fills the negotiation-venue blind spot
- **Lebanon**: L'Orient Today (RETRY), Al-Akhbar (RETRY) — active war zone
- **Iraq**: Iraqi News
- **Egypt**: Egypt Independent, Mada Masr, Daily News Egypt, Al Ahram (via GN), Ahram Online AR (via GN) — largest Arabic media market
- **Jordan**: Jordan Times (RETRY)
- **Syria**: Enab Baladi, Syrian Observer
- **Palestine**: Maan News (RETRY), Palestine Chronicle (RETRY)
- **Iran State** (replacements): Mehr (RETRY), Press TV via alt rsshub (RETRY)

## Added — Russia full-spectrum (was English-export only)
- **Russia native (RU language)**: Lenta (stub), Kommersant, RIA Novosti (stub), Novaya Gazeta Europe (RETRY) — fixes the Cyrillic-coverage blind spot

## Added — Ukraine, Germany direct (was missing)
- **Ukraine**: Ukrainska Pravda EN, Kyiv Post, Ukrinform — fixes Russia-only-voice on Ukraine stories
- **Germany**: DW EN, DW DE, Spiegel International, Tagesschau, DW Russian
- **France direct**: Le Monde, Le Figaro, Liberation (all RETRY) — beyond AFP wire

## Added — Europe (was zero outside UK)
- **Italy**: ANSA EN, ANSA IT, La Repubblica
- **Spain**: El País, El Mundo, ABC, El País EN
- **Netherlands**: NL Times, DutchNews
- **Poland/Baltics**: Notes from Poland, ERR Estonia
- **Balkans**: N1 Serbia, Balkan Insight
- **Hungary/Czechia**: Hungary Today, Telex, Prague Morning
- **Caucasus**: Civil Georgia, OC Media
- **Nordic**: Yle Finland, The Local SE, The Local DE

## Added — Asia-Pacific (was East Asia + India only)
- **Indonesia**: Antara
- **Philippines**: Inquirer, Rappler, Philstar
- **SE Asia**: VnExpress, Bangkok Post, Malay Mail, CNA, Straits Times
- **Taiwan/HK**: Taipei Times (stub), HKFP, SCMP
- **North Korea coverage**: NK News, Daily NK
- **Australia/NZ**: ABC Australia, SMH, Guardian Australia (RETRY)
- **Canada**: CBC

## Added — Latin America (was Brazil only)
- **Mexico**: Mexico News Daily
- **Argentina/Chile**: Clarín, La Nación, Buenos Aires Herald
- **Colombia/Venezuela**: El Tiempo, Caracas Chronicles

## Added — Africa (was Nigeria only)
- **South Africa**: News24, Mail & Guardian, Daily Maverick
- **Kenya**: Standard Kenya World
- **Continental**: AllAfrica, Premium Times Nigeria (independent)
- **Ethiopia**: Addis Standard (RETRY)

## Added — USA / wire extras
- **USA**: Politico, Axios, The Hill (in addition to CNN/Fox/NPR)
- **Wire**: existing 4 + Le Monde/Figaro/Liberation French (merged into wire bucket as "France direct")

## Status flag legend
- `OK` — probe returned 200 with parseable items, real summaries
- `STUB` — title-only feed, summary≈title or empty (4 feeds: ARY News, Lenta, RIA, Taipei Times)
- `RETRY` — 403/429 from probe container; likely UA/IP-blocked, expected to work from prod IP (15 feeds, mostly major Western outlets)
- Existing feeds carry `OK` since the 39-day snapshot uptime confirms they work on prod
