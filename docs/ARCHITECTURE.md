# Architecture — Epistemic Lens v0.5

## System overview

```
                        ┌──────────────────────────────────┐
                        │  feeds.json  (235 feeds, 54 bk)  │
                        └────────────────┬─────────────────┘
                                         │
                ┌────────────────────────▼────────────────────────┐
                │  DATA PIPELINE                                  │
                │                                                 │
                │  ingest.py            → snapshots/<date>.json   │
                │   • parallel fetch (ThreadPool, 30 workers)     │
                │   • per-host rate limit + retries               │
                │   • xml.etree parser (RSS/Atom/RDF)             │
                │   • per-item flags: is_stub, is_google_news,    │
                │       summary_chars, published_age_hours        │
                │                                                 │
                │  extract_full_text.py                           │
                │   • trafilatura body extraction                 │
                │   • Wayback Machine fallback on 4xx             │
                │   • signal_text() helper: body | summary | title│
                │   • per-bucket coverage so every country has    │
                │       at least N items extracted daily          │
                │                                                 │
                │  dedup.py                                       │
                │   • URL canonicalisation (utm/m./www/GN)        │
                │   • title near-dup collapse                     │
                │                                                 │
                │  daily_health.py                                │
                │   • feed health + extraction stats              │
                │   • alerts: volume_drop + low_extraction        │
                │                                                 │
                │  feed_rot_check.py     (weekly)                 │
                │   • flags persistently broken feeds             │
                └────────────────┬────────────────────────────────┘
                                 │
                                 ▼
                ┌──────────────────────────────────┐
                │  build_briefing.py               │
                │   • detects canonical stories    │
                │   • per-story corpus with up to  │
                │     2 distinct framings/bucket   │
                │   • signal_text fallback chain   │
                └────────────────┬─────────────────┘
                                 │
                                 ▼
                  briefings/<date>_<story>.json
                                 │
        ┌────────────────────────┴────────────────────────┐
        │ [HUMAN STEP — for now]                          │
        │   Open the briefing, review framings,           │
        │   write video_scripts/<date>_<n>.json with      │
        │   8 scenes (hook + setup + 5 country framings   │
        │   + outro), each with voiceover + on_screen     │
        │   text + headline_quoted.                       │
        │                                                 │
        │   Future: framing_pass.py (Claude API) does     │
        │   this automatically. Skip until format is      │
        │   validated by audience.                        │
        └────────────────────────┬────────────────────────┘
                                 │
                                 ▼
                  video_scripts/<date>_<n>.json
                                 │
        ┌────────────────────────▼────────────────────────┐
        │  VIDEO PIPELINE                                 │
        │                                                 │
        │  synthesize_voiceover.py                        │
        │   • Piper TTS (local, offline ONNX)             │
        │   • per-scene WAV + durations.json metadata     │
        │   • free, no API key, no rate limits            │
        │                                                 │
        │  generate_music_bed.py    (one-time)            │
        │   • pure-Python synth ambient drone             │
        │   • 120s seamless loop                          │
        │                                                 │
        │  render_video.py                                │
        │   • merges per-scene audio into props           │
        │   • shells out to Remotion via npm              │
        │   • headless Chromium renders MP4               │
        │                                                 │
        │  video_template/   (Remotion + TypeScript)      │
        │   • WorldMap with real countries (TopoJSON)     │
        │   • Camera dolly between presets per scene      │
        │   • Country pin pulse + flag emoji              │
        │   • QuoteCard with framing + provenance         │
        │   • TikTok-style burned-in captions             │
        │   • Audio per scene + music bed                 │
        └────────────────┬────────────────────────────────┘
                         │
                         ▼
                videos/<id>.mp4   (1080×1920, ~30 MB, 60-90s)
                         │
                         ▼
                  [POSTING — manual]
                  TikTok / IG Reels / YT Shorts
```

## Data layer details

**Snapshot file shape** (`snapshots/<date>.json`):
```json
{
  "pulled_at": "2026-05-06T07:00:00Z",
  "date": "2026-05-06",
  "config_version": "0.5.0",
  "max_items": 50,
  "countries": {
    "usa": {
      "label": "United States",
      "feeds": [
        {
          "name": "CNN World",
          "lang": "en",
          "lean": "Centre-liberal",
          "fetch_ms": 1234,
          "http_status": 200,
          "bytes": 45000,
          "error": null,
          "item_count": 50,
          "items": [
            {
              "title": "...",
              "link": "https://...",
              "summary": "...",
              "published": "Tue, 06 May 2026 06:00:00 +0000",
              "id": "abc123ef",
              "summary_chars": 240,
              "is_stub": false,
              "is_google_news": false,
              "published_age_hours": 1.2,
              // After extract_full_text.py:
              "body_text": "...",
              "body_chars": 4200,
              "extraction_status": "FULL",
              "extraction_ms": 1500,
              "extraction_http": 200,
              "extraction_via_wayback": false,
              // After dedup.py:
              "canonical_url": "https://...",
              "normalised_title": "...",
              "url_dup_count": 1,
              "title_dup_count": 1
            }
          ]
        }
      ]
    }
  }
}
```

**Briefing file shape** (`briefings/<date>_<story>.json`):
```json
{
  "date": "2026-05-06",
  "story_key": "hormuz_iran",
  "story_title": "Strait of Hormuz / US-Iran deal",
  "n_buckets": 27,
  "n_articles_total": 41,
  "signal_breakdown": {"body": 24, "summary": 3},
  "corpus": [
    {
      "bucket": "usa",
      "feed": "Fox News World",
      "lang": "en",
      "title": "...",
      "link": "https://...",
      "signal_level": "body",
      "signal_text": "first 2500 chars of body or summary",
      "extraction_status": "FULL",
      "via_wayback": false
    }
  ]
}
```

**Video script shape** (`video_scripts/<date>_<n>.json`):
```json
{
  "video_id": "2026-05-06_01_hormuz",
  "story_date": "2026-05-06",
  "story_title": "Strait of Hormuz / Project Freedom paused",
  "rank": 1,
  "duration_seconds": 60,
  "scenes": [
    {
      "scene": 1,
      "time": "0:00-0:05",
      "voiceover": "Same news. Five very different stories.",
      "on_screen_text": "5 COUNTRIES.\n1 STORY.",
      "country": null
    },
    {
      "scene": 3,
      "time": "0:13-0:22",
      "voiceover": "United States. Trump on Truth Social: ...",
      "on_screen_text": "🇺🇸 USA: 'If they don't agree, the bombing starts'\nTrump, Truth Social",
      "headline_quoted": "Trump warns 'much higher-level' bombing — Yonhap"
    }
  ],
  "fact_check_provenance": {
    "supporting_quotes_per_frame": [
      {"frame": "USA", "outlet": "Yonhap News", "exact_headline": "..."}
    ],
    "briefing_corpus": "briefings/2026-05-06_hormuz_iran.json"
  }
}
```

## Component reference

### Remotion video template (`video_template/`)

| Component | Purpose |
|---|---|
| `Root.tsx` | Composition registry, default props for `npm run dev` |
| `FramingVideo.tsx` | Top-level: parses scenes, computes frame ranges, orchestrates camera dolly |
| `cameraPresets.ts` | 35 country `[lon, lat, zoom, flag, label]` presets |
| `WorldMap.tsx` | Dark equirectangular map with real country shapes + active-country highlight |
| `CountryPin.tsx` | Pulsing flag pin centered on the focused country |
| `QuoteCard.tsx` | Bottom slide-up card with framing + italic provenance |
| `TitleCard.tsx` | Opening hook with line-stagger reveal |
| `OutroCard.tsx` | Closing CTA with pulsing FOLLOW button |
| `Captions.tsx` | TikTok-style burned-in subtitles |
| `types.ts` | `VideoScriptProps`, `Scene` type definitions |

### Pipeline scripts

| Script | Reads | Writes |
|---|---|---|
| `ingest.py` | `feeds.json` | `snapshots/<date>.json` + `_pull_report.md` |
| `extract_full_text.py` | snapshot + optional `_convergence.json` | annotates snapshot in place; checkpoints every N |
| `dedup.py` | snapshot | `_dedup.json` + annotates items in place |
| `daily_health.py` | snapshot + last 7 days | `_health.json` |
| `feed_rot_check.py` | last 7 `_health.json` | `archive/review/rot_report_<date>.md` |
| `build_briefing.py` | latest snapshot | `briefings/<date>_<story>.json` |
| `synthesize_voiceover.py` | `video_scripts/<id>.json` | `video_template/public/voiceovers/<id>/scene_*.wav` + `durations.json` |
| `generate_music_bed.py` | (none) | `video_template/public/music_bed.wav` |
| `render_video.py` | `video_scripts/<id>.json` + `durations.json` | `videos/<id>.mp4` |

## Status flags in feeds.json

| Flag | Meaning |
|---|---|
| `OK` | Feed live, returns parseable items, real summaries |
| `STUB` | Title-only feed (Lenta, RIA, ARY News, Taipei Times). Useful for headline tracking, weak for embedding nuance |
| `RETRY` | 403/429 from probe container; expected to work from production IP. Mostly major Western outlets behind anti-bot |
| `OK + extraction via Wayback` | Live feed but article body retrieved via web.archive.org because the live host blocks |

## Pipeline cadence

| Cadence | Job | Action |
|---|---|---|
| Daily 07:00 UTC | `daily.yml` | ingest → extract → dedup → health → commit |
| Sundays 09:00 UTC | `weekly_rot.yml` | feed rot check → commit `archive/review/rot_report_<date>.md` |
| Push to main / claude-* | `ci.yml` | unit + edge tests; e2e on main only |
| On-demand (until A3 built) | manual or Claude Code session | build_briefing → write video_scripts → synthesize → render → post |
