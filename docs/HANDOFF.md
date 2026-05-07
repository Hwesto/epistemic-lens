# Epistemic Lens — Handoff Context

**For starting a fresh Claude Code session.** This doc captures everything an
incoming session needs to understand the project state without rereading
months of conversation.

---

## TL;DR

- **Repo**: `hwesto/epistemic-lens`
- **Active branch**: `claude/fresh-pull-analysis-9k2p`
- **Latest tag**: `v0.5.0`
- **Latest commit**: `417b77a` (v0.7.1 — Gemini-feedback pass)
- **What it is**: a daily news-framing analysis pipeline that pulls RSS from
  235 outlets across 54 country/region buckets, extracts article body text,
  builds per-story framing-comparison briefings, and (newly) renders branded
  60-second short-form videos comparing how 5+ countries told the same story.
- **Total cost to run**: $0/month using free local TTS (Kokoro), free Remotion
  rendering, and free GitHub Actions cron.
- **Where the user wants to pivot now**: away from video production refinement,
  back to **deeper framing analysis of the actual data**. They want to look at
  what the data is telling us and find better ways to frame what we present,
  before optimising more video polish.

---

## What's built and working

### Data pipeline (Python, all at repo root)

```
ingest.py              fetch 235 RSS feeds → snapshots/<date>.json
extract_full_text.py   trafilatura body extraction + Wayback fallback;
                       writes signal_text() helper that returns body|summary|
                       title gracefully (so a paywalled outlet still
                       contributes its headline framing)
dedup.py               URL canon + title near-dup collapsing
daily_health.py        per-bucket alerts (volume_drop, low_extraction)
feed_rot_check.py      weekly persistent-rot detection
build_briefing.py      detect canonical stories (hormuz_iran, turner_cnn,
                       lebanon_buffer, hantavirus_cruise, etc.) and write
                       briefings/<date>_<story>.json with up to 2 distinct
                       framings per bucket (Jaccard novelty filter)
gdelt_pull.py          GDELT 2.0 GKG firehose + DOC API breadth supplement
analysis.py            cross-day operational metrics (country pair
                       correlations, silence audit, framing keyword counts)
analysis2.py           cluster framing comparisons
source_audit.py        static + live audit of source list with grade table
```

### Video pipeline (Remotion + Python wrapper)

```
synthesize_voiceover.py       multi-provider TTS (kokoro default, piper
                              fallback, elevenlabs cloud option). Per-scene
                              speech_rate. Outputs WAV/MP3 + durations.json
generate_music_bed.py         pure-Python ambient drone (no external deps)
render_video.py               merges durations + props, shells out to
                              `npx remotion render`
video_template/               Remotion + TypeScript project
  src/Root.tsx                composition registry
  src/FramingVideo.tsx        scene orchestration + camera dolly
  src/types.ts                VideoScriptProps, Scene, ParadoxSide types
  src/cameraPresets.ts        35 country [lon, lat, zoom, flag, label]
  src/useCameraDolly.ts       shared camera-interpolation hook (camera arrives
                              in first 30% of scene, then sits still)
  src/components/
    WorldMap.tsx              real-country shapes (TopoJSON), active-country
                              highlight, greyed non-focal countries
    CountryPin.tsx            pulsing flag pin
    QuoteCard.tsx             v0.6.1 hero-quote layout: small framing label
                              top + LARGE serif quote middle + attribution
    TitleCard.tsx             opening hook with line-stagger reveal
    OutroCard.tsx             closing CTA
    Captions.tsx              TikTok-style burned-in subtitles (48px)
    IntroSting.tsx            3s logo-flash sting (uses public/intro_sting.mp3)
    TopNewsBar.tsx            full-width news ticker bar at top of frame,
                              cycles world_tickers one at a time (28px)
    ParadoxCard.tsx           split-screen climax: top half + "BOTH AGREE"
                              red bar + bottom half (used when scene_type=
                              "paradox")
```

### GitHub Actions

```
.github/workflows/daily.yml         07:00 UTC: ingest → extract → dedup →
                                    daily_health → commit
.github/workflows/weekly_rot.yml    Sundays 09:00 UTC: rot check → commit
.github/workflows/ci.yml            push/PR: unit + edge tests; e2e on main
```

---

## Coverage at a glance

**235 feeds, 54 buckets, 16+ languages, 6 continents.** See `docs/COVERAGE.md`
for the full grade table. Highlights:

- **A+/A**: USA (15), India (15, both populist + liberal), Germany (10, incl.
  Bild + AfD-aligned), UK (9, incl. tabloid)
- **A-**: Canada (5), UK
- **B+/B**: Russia native (Lenta/Kommersant + Komsomolskaya Pravda), Australia
  with Murdoch press, Italy, Spain, Indonesia (Tempo/CNN/Tribunnews), Brazil
  (Folha + O Globo + G1 + BBC Brasil)
- **B-/C+**: Mexico (5 ES outlets after fixes), Pakistan (incl. Bol News
  populist), Taiwan/HK (incl. Liberty Times), Japan (Asahi/Mainichi/Nikkei
  stub-only), South Korea (Chosun finally landed), Iran state + opposition
- **C/D**: Most of Africa (1.4B people, ~6 outlets), some Caucasus

**6 structural categories beyond country buckets**: opinion_magazines (FP/FA/
Atlantic/Politico EU/Conversation), pan_arab (MEE/MEMO), pan_african
(AfricaNews/Africa Report), asia_pacific_regional (Diplomat/Asia Times),
state_tv_intl (France 24 AR/ES, Sputnik, RT Africa), religious_press (Vatican
News, Religion News Service), telegram_proxies (5 channels via rsshub).

**Persistent gaps**: TV news transcripts everywhere (CCTV, Pervyi Kanal, Press
TV), Pakistani Urdu native press (RSS dead), Yomiuri Shimbun (RSS dead),
Korean Big 3 conservatives' English editions, WeChat/Douyin.

---

## What we've actually learned from the data

Real cross-bloc framing patterns surfaced from the 39+ days of snapshots:

### 1. The Russia "two faces" finding

Russian-language Russia (Lenta, Kommersant, RIA Novosti, Novaya Gazeta Europe)
runs a fundamentally different editorial agenda from the English-export face
(TASS / RT / Moscow Times / Meduza). Top 5 Lenta headlines on 2026-05-06:
weather warnings, escaped lecher-teacher recaptured, pop singer apartment
purchase, woman burned by boiling water, new cold wave. **Top 5 TASS English**
the same day: Ukraine-NATO rifts, Iran-IRGC Hormuz security, UAE graphene,
228 US military facilities damaged by Iran, "brave Zaporozhye journalists."

**Implication**: previous "China-Russia low similarity" findings were on
English-export only. Russia's domestic press isn't engaging with the same
narratives at all.

### 2. South Korea is a "news island"

Even with full v0.5 coverage, South Korea misses ~85% of major cross-country
stories. Yonhap and Korea Herald are intensely peninsula-focused. Confirmed
across every multi-day analysis — this is structural, not a feed gap.

### 3. The Foreign Affairs ↔ RT paradox (Hormuz)

The single most striking finding: on 2026-05-06's Iran-deal coverage, the US
foreign-policy establishment magazine (Foreign Affairs) and Russian state TV
(RT) reached the *exact same* analytical conclusion — "Iran proved it can
close the strait, the IRGC stays, the deal is a face-saving pause for the US."
Different tones (FA cool analysis vs RT gloating) but identical strategic
read. This became the climax of the first video.

### 4. Country-pair Jaccard surprises

- **Iran State ↔ Iran Opposition**: highest semantic similarity of any pair
  (0.654). They cover the same stories with opposite valences — perfect
  adversarial mirror.
- **Iran Opposition ↔ Saudi Arabia** (0.639) — confirms Iran International's
  Saudi-funding angle.
- **Qatar ↔ Israel** (0.638) — both Middle-East-news-saturated.
- **Wire Services ↔ India** (0.39 J) — Indian English press is heavily
  wire-dependent.
- **China ↔ Russia (export)** (0.34) — surprisingly LOW. Despite political
  alignment, their English-export agendas barely overlap.

### 5. Propaganda lexicon fingerprints (per 1000 headlines)

| Country | regime | aggression | terrorist | martyr | Zionist |
|---|---|---|---|---|---|
| Iran State | 25 | 17 | 16 | **31** | **54** |
| USA | 17 | 0 | 1 | 0 | 0 |
| Israel | 12 | 1 | 7 | 0 | 3 |
| Saudi (incl Al Arabiya) | 4 | 0 | 0 | 0 | 0 |
| China | 0.5 | 0 | 0 | 0 | 0 |
| Russia (export) | 6 | 1 | 3 | 0 | 0 |

"Zionist" + "martyr" are exclusive Iran State signatures. "Regime" is
USA + Iran State (they call each other regimes — symmetric delegitimation).
Saudi pumps "ceasefire" hard (68/1000 headlines) — geopolitical peace push.

### 6. Iran blackout signature

Iran state feeds went 0-items/day from 2026-03-25 to 2026-04-08, then
recovered in stages. Iran-opposition (Iran International + RFE/RL) ran 30
items/day throughout — they filled the void during the blackout. Visible
as a clean step function in `daily_health.py` output.

---

## Three videos rendered for 2026-05-06

In `videos/`:

| File | Story | Length | Key reveal |
|---|---|---|---|
| `2026-05-06_01_hormuz.mp4` (9.1 MB) | Strait of Hormuz / one-page memo | ~47s | PARADOX: Foreign Affairs ↔ RT both conclude Iran won (split-card climax) |
| `2026-05-06_02_turner.mp4` (12.2 MB) | Ted Turner death | ~52s | UK Independent: Trump's tribute is actually "a shot at CNN" |
| `2026-05-06_03_lebanon_buffer.mp4` (14.2 MB) | Israeli buffer zone S. Lebanon | ~62s | Mada Masr's "occupying" word + Pope Leo XIV calling priests + IDF chief's "historic opportunity to reshape region" |

Hormuz is at v0.7.1 (post-Gemini polish: top news bar, paradox split-card,
conflict-first hook "WHO WON THE HORMUZ WAR?"). Turner and Lebanon still at
v0.7.0 (older list-style structure without the paradox card).

---

## Voice / audio current state

- **Default**: Kokoro `bm_george` (British male broadcaster, free local ONNX,
  no crackling, ~50ms per sentence on CPU).
- **Tested alternatives**: Piper alan-medium (crackled), ElevenLabs Brian
  (free tier blocked from container's datacenter IP).
- **Music**: pure-Python ambient drone in A-minor (`generate_music_bed.py`).
- **Captions**: TikTok-style 48px burned-in subtitles, chunked by punctuation.
- **Intro sting**: user-provided 3.03s MP3 → custom logo flash with 4-frame
  black flash hard cut into title.

**Limitation user identified**: Kokoro is a flat-prosody model. It can't do
sarcasm, dramatic pauses, or word-level emphasis. For real broadcaster tone
the path is either:
- ElevenLabs v3 with `[skeptical]` / `[sarcastic]` / `[dramatic]` audio tags
  (works free tier but blocked from container — needs to run on user's home
  machine)
- Chatterbox or F5-TTS open-source with voice cloning (~10 min setup on a
  machine with C++ build tools — container lacks `gcc` for `encodec` /
  `antlr4-python3-runtime` deps)

---

## Where the user wants to go next

> "I think we need to go back to the data and really look at what we can do
> to frame it."

The video stack works. The data is rich. **The bottleneck right now is
analytical, not production.**

Suggested next moves the incoming session could explore:

### A. Deeper framing analysis (most leveraged)
- For a single recent day's snapshot, do a full LLM-grade framing pass on
  the body text of every cross-bloc story (top 10 stories × ~15 articles
  each). Use Claude API or interactive Claude Code session.
- Surface the paradoxes / contradictions like the Foreign Affairs ↔ RT one.
  Those are the actual content of the channel.
- Build `analyze_paradoxes.py` — for each story, find pairs of outlets from
  different blocs whose body text shares strong analytical conclusions
  despite opposite political alignment.

### B. Long-tail framings (we keep finding)
- The `lebanon_buffer` story had 4 buckets covering it but the highest
  framing-divergence of the day. The cron currently picks "top by country
  count" — that misses the most editorially distinct stories.
- New `select_stories.py` heuristic: weight by *framing-divergence score*,
  not just bucket count. A 5-bucket story with extreme disagreement may be
  more video-worthy than a 27-bucket Reuters-syndication clone.

### C. Story arc / multi-day tracking
- Track how a story's framing matrix evolves over 7-14 days. The Hormuz
  framing was wildly different on day 1 (US strikes start) vs day 64
  (deal near). Build day-by-day animations of the framing matrix.

### D. Silence as a feature
- For each big story, make "the absence" the angle: "Why hasn't China
  covered Bucha?", "Why did India ignore the Khashoggi follow-up?". The
  data already has this — `analysis.py` silence audit is the seed.

### E. Editorial source-graph
- Build a graph of which outlets cite which outlets / wire services.
  Reuters appears in everyone; Iran International cites Saudi state media;
  Wire-via-Google-News stub feeds give us titles only. The graph tells you
  where original reporting lives vs where it's syndicated.

### F. Counter-factual blind-spot tracking
- For each big story, what would each country's coverage look like if we
  removed the wire services? Answers "what does this country's *original*
  reporting say?" The wire-cleaning is already trivial via the
  `is_google_news` / `is_stub` flags.

---

## Where to start a new session

If the new session opens with this doc:

1. `git pull` on `claude/fresh-pull-analysis-9k2p`
2. Read `docs/ARCHITECTURE.md` for system overview
3. Read `docs/COVERAGE.md` for the source list grade table
4. Read this file (`docs/HANDOFF.md`) for state + insights
5. The latest snapshot is in `snapshots/<date>.json`; latest briefings in
   `briefings/<date>_<story>.json`
6. Decide which of A-F (or your own direction) to pursue
7. Don't get pulled back into video polish unless the user explicitly asks —
   the user's stated goal is **better framing analysis from the data**

## Key files for fresh-eye review

| File | Why it matters |
|---|---|
| `feeds.json` | The 235-feed source list (v0.5.0) |
| `snapshots/2026-05-06.json` | Latest pull with all extraction annotations |
| `briefings/2026-05-06_*.json` | Today's per-story corpora |
| `video_scripts/2026-05-06_*.json` | Hand-authored video scripts (the framing analysis I produced manually) |
| `docs/ARCHITECTURE.md` | Pipeline diagram + JSON schemas |
| `docs/COVERAGE.md` | Per-bucket grade table + structural blind spots |
| `docs/OPERATIONS.md` | Daily/weekly/manual procedures |

## Open known issues / decisions

- ElevenLabs API key was shared in chat (`sk_dc3b...`) — user was advised to
  rotate. Don't assume it's still valid.
- ElevenLabs free tier is blocked from datacenter IPs (incl. Anthropic's
  container + GitHub Actions runners). For ElevenLabs use, must run from
  user's home machine.
- `npx remotion still` does NOT go through `render_video.py`'s audio-merge
  step — to preview a frame from the actual rendered video timing, write
  merged props to a temp file first. Render via `render_video.py` is the
  authoritative timing.
- `framing_pass.py` (the Claude API automation that would write daily video
  scripts) is *unbuilt*. Hand-authored scripts so far. Worth building only
  after audience signals format works (i.e. after first 7 real posts).
- `gdelt_pull.py` DOC API path got rate-limited in testing; bulk-GKG works
  fine. Production runs need >2s spacing between DOC calls.
