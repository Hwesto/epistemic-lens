# Epistemic Lens v0.5

Cross-national news framing analysis + automated short-form video generation.

> Pull RSS from **235 outlets across 54 country/region buckets** (16+ languages,
> 6 continents) → extract article bodies → cluster cross-bloc stories → write
> framing-comparison briefings → render daily 60-second vertical videos with
> AI voice + ambient music + burned-in captions. Total cost: $0/mo.

## Quick start

```bash
# Clone and install Python deps
git clone <repo> && cd epistemic-lens
pip install -r requirements.txt

# Install Node deps for the video template (one-time)
cd video_template && npm install && cd ..

# Run today's full pipeline
python ingest.py                        # 235 feeds → snapshots/<date>.json (~2 min)
python extract_full_text.py             # +body text on top stories (~3 min)
python dedup.py                         # collapse near-duplicate items
python daily_health.py                  # health snapshot + alerts
python build_briefing.py                # briefings/<date>_<story>.json

# Pick top 3 stories, write their video_scripts/*.json (manual or via Claude Code)

# Render with voice + music + captions
python synthesize_voiceover.py video_scripts/<date>_*.json   # Piper TTS, free
python render_video.py video_scripts/<date>_*.json            # Remotion → MP4

# Done. Videos in videos/<date>_*.mp4 (~30 MB each, 60-90 s)
```

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full pipeline diagram.
Short version:

```
ingest.py ─→ extract_full_text.py ─→ dedup.py ─→ daily_health.py
                                                       │
                                                       ▼
                                              build_briefing.py
                                                       │
                                                       ▼
                                            briefings/<date>_*.json
                                                       │
                              [hand-write or Claude Code session per day]
                                                       │
                                                       ▼
                                          video_scripts/<date>_*.json
                                                       │
                              ┌────────────────────────┼────────────────────────┐
                              ▼                        ▼                        ▼
                    synthesize_voiceover.py    generate_music_bed.py    Remotion template
                    (Piper TTS, local, free)   (pure Python, free)      (video_template/)
                              │                        │                        │
                              └────────────────────────┴────────────────────────┘
                                                       │
                                                       ▼
                                                videos/<id>.mp4
```

## Coverage

235 feeds across 54 buckets. 49+ buckets reliably extract full body text per day.
See [`docs/COVERAGE.md`](docs/COVERAGE.md) for the country-by-country grade table.

Highlights:
- **Mass-tabloid press**: Daily Mail (UK), Bild (DE), Komsomolskaya Pravda (RU)
- **Right-populist**: Daily Wire / Breitbart (US), Republic World / Aaj Tak (IN), Junge Freiheit (DE), Sky News Australia
- **Multi-language native**: Russian-language Russia, Hindi (Aaj Tak, Bhaskar), Korean (Chosun), Spanish (5 Mexican papers, El País, La Nación)
- **Pan-regional**: Middle East Eye, AfricaNews, The Diplomat
- **Religious + state-TV**: Vatican News, France 24 AR/ES, Sputnik International, RT Africa

## Operations

See [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the daily/weekly cron flow,
GitHub Actions setup, and feed-rot detection.

## Tests

```bash
python -m unittest tests.py tests_edge.py     # 45 tests, no network needed (~12 s)
python tests_e2e.py                            # full pipeline smoke (live, ~6 s)
```

See [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) for what's covered.

## File map

```
epistemic-lens/
├── README.md                       ← you are here
├── feeds.json                      ← source list (v0.5.0, 235 feeds)
├── requirements.txt
├── .github/workflows/
│   ├── daily.yml                   ← daily cron (07:00 UTC)
│   ├── weekly_rot.yml              ← Sundays 09:00 UTC
│   └── ci.yml                      ← unit tests on push
│
├── ingest.py                       ← v0.4 parallel async fetcher
├── extract_full_text.py            ← trafilatura body extraction + Wayback fallback
├── dedup.py                        ← URL canon + title near-dup collapse
├── daily_health.py                 ← post-pull health + bucket alerts
├── feed_rot_check.py               ← weekly rot detection
├── build_briefing.py               ← per-story corpus assembler
├── synthesize_voiceover.py         ← free local Piper TTS
├── generate_music_bed.py           ← pure-Python ambient drone
├── render_video.py                 ← Remotion render orchestrator
├── analysis.py / analysis2.py      ← cross-day analytical cuts
├── source_audit.py                 ← static + live audit of source list
├── baseline_pin.py                 ← snapshot baseline for A/B
├── gdelt_pull.py                   ← GDELT 2.0 breadth supplement
├── tests.py / tests_edge.py / tests_e2e.py
│
├── video_template/                 ← Remotion + React video renderer
│   ├── package.json
│   ├── src/{Root,FramingVideo,types,cameraPresets}.tsx
│   └── src/components/{WorldMap,CountryPin,QuoteCard,TitleCard,OutroCard,Captions}.tsx
│
├── snapshots/                      ← daily output (RSS + extraction + dedup + health)
├── briefings/                      ← daily story corpora
├── video_scripts/                  ← daily video script JSONs
├── videos/                         ← rendered MP4s (gitignored except stills/)
│
├── docs/
│   ├── ARCHITECTURE.md             ← full pipeline diagram
│   ├── COVERAGE.md                 ← country grade table
│   ├── OPERATIONS.md               ← cron + manual run procedures
│   └── TEST_REPORT.md              ← what's tested + known gaps
│
└── archive/                        ← historical artefacts (kept, not for daily use)
```

## Costs

| Component | Cost |
|---|---|
| Python deps (requests, trafilatura, sentence-transformers, etc.) | $0 |
| Piper TTS + Amy voice (local ONNX) | $0 |
| Remotion + headless Chromium | $0 |
| Music bed (synthesized in Python) | $0 |
| GitHub Actions (public repo, unlimited free minutes) | $0 |
| **Total** | **$0/mo** |

Optional upgrades:
- ElevenLabs Creator (~$22/mo) for higher-prosody voice
- Sora/Runway API (~$50-300/mo) for AI-generated hero shots
- Anthropic API (~$10-30/mo) for automated framing extraction

## Versioning

| Version | Date | Highlights |
|---|---|---|
| 0.2 | Mar 2026 | Initial: 51 feeds, 16 buckets, sequential ingest, Iran-war coverage |
| 0.4 | May 2026 | 138 feeds, 47 buckets, parallel ingest, full-text extraction, dedup, GDELT bolt-on, GH Actions |
| 0.4.2 | May 2026 | +50 gap-fix feeds (tabloid + populist + native-language) |
| 0.4.3 | May 2026 | Structural diversification (opinion magazines, pan-Arab, pan-African, Asia-Pacific, religious press, telegram proxies) |
| **0.5.0** | **May 2026** | **Cleanup release. Briefing builder + voice + music + captions + video template. End-to-end pipeline at $0/mo.** |
