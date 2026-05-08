# Epistemic Lens

**Daily, automated, source-transparent cross-country news framing analysis.**

> Pull RSS from **235 outlets across 54 country/region buckets** (16+ languages, 6 continents) → extract article bodies → cluster cross-bloc stories → build per-story corpora with metrics (Jaccard, isolation, bucket-exclusive vocab) → run the daily Claude framing pass → render structured analyses, social drafts, and a public landing page. Daily cron runs unattended on GitHub Actions. Total ongoing cost: $0/mo + a Claude.ai subscription.

**Live front door:** [hwesto.github.io/epistemic-lens](https://hwesto.github.io/epistemic-lens/)

## Layered architecture

The codebase decomposes into four loosely-coupled concerns. Each evolves on its own schedule; the methodology pin (`meta_version.json`) keeps them honest.

| Concern | What it is | Files |
|---|---|---|
| **Ingestion** | RSS pull, body extraction, dedup, health, rot detection | `ingest.py`, `extract_full_text.py`, `dedup.py`, `daily_health.py`, `feed_rot_check.py`, `feeds.json` |
| **Analytical** | Story detection, metrics, daily Claude framing analysis (JSON-canonical), validation | `build_briefing.py`, `build_metrics.py`, `validate_analysis.py`, `restamp_analyses.py`, `meta.py`, `.claude/prompts/daily_analysis.md`, `docs/api/schema/analysis.schema.json` |
| **Publication** | Markdown render, template-based thread/carousel drafts, Sonnet long-form, public API + landing page, video stack | `render_analysis_md.py`, `render_thread.py`, `render_carousel.py`, `.claude/prompts/draft_long.md`, `web/`, `build_index.py`, `video_template/` (dormant) |
| **Methodology pin** | Cross-cutting integrity layer: every input that affects analytical output is hashed; every artifact carries the active `meta_version` | `meta_version.json`, `baseline_pin.py`, `stopwords.txt`, `canonical_stories.json`, `docs/METHODOLOGY.md`, schemas |

## Daily flow (07:00 UTC, fully unattended)

```
ingest    →  snapshot + briefings + metrics commit to main           ~8 min
analyze   →  Haiku writes JSON analyses + schema/citation/number     ~5 min
             validators + render markdown + commit
draft     →  Python templates write thread.json + carousel.json,     ~8 min
             Sonnet writes long-form prose
publish   →  build_index.py rebuilds api/ tree, copies web/*,        ~10 sec
             deploys to GitHub Pages
```

Workflow: `.github/workflows/daily.yml`. Every step subscription-billed via the OAuth token (`anthropics/claude-code-action@v1`); zero metered API spend. `workflow_dispatch` inputs `skip_ingest` / `skip_analyze` / `skip_draft` let you re-run downstream-only without burning fresh feed pulls or LLM calls.

## What lands on Pages each day

For each story (currently 3–5/day):

```
hwesto.github.io/epistemic-lens/<DATE>/<story_key>/
  briefing.json     ← per-bucket corpus (full bodies, dedup'd)
  metrics.json      ← Jaccard, isolation, bucket-exclusive vocab
  analysis.json     ← canonical structured analysis (schema-validated)
  analysis.md       ← rendered for human reading
  thread.json       ← X/Threads draft (template, no LLM)
  carousel.json     ← IG/LinkedIn deck (template, no LLM)
  long.json         ← LinkedIn/Substack long-form (Sonnet)
```

Plus per-date `index.json`, root `latest.json`, and the static landing page at `/`.

## Quick start (local development)

```bash
git clone <repo> && cd epistemic-lens
pip install -r requirements.txt

# Run today's ingest stage locally (matches the cron's first job)
python ingest.py
python extract_full_text.py
python dedup.py
python daily_health.py
python build_briefing.py
python build_metrics.py

# The analyze + draft + publish stages run via GitHub Actions in the cron.
# See docs/OPERATIONS.md for the one-time CLAUDE_CODE_OAUTH_TOKEN setup.

# Test
python -m unittest tests.py tests_edge.py    # 64 tests, no network (~1 s)
python tests_e2e.py                            # full pipeline smoke (live, ~6 s)
```

## Methodology pin

Every input that affects analytical output (feeds list, stopwords, prompts, embedding model, clustering hyperparameters, schema definitions, model identifiers) is hashed in `meta_version.json`. Every artifact (snapshot, briefing, metrics, analysis, draft) carries the active `meta_version` so longitudinal consumers know which era they're reading.

Bumping rules — `patch` (no output change), `minor` (forward-compatible), `major` (invalidates longitudinal comparison):

```bash
python baseline_pin.py --check                        # CI gate
python baseline_pin.py --bump minor --reason "..."    # bumper
```

CI's `meta-check.yml` workflow enforces hash match on every push/PR.

See `docs/METHODOLOGY.md` for the full policy.

## Coverage

235 feeds across 54 buckets. ~85% body-text extraction success on a typical day. See `docs/COVERAGE.md` for the country-by-country grade table. Highlights:

- **Mass-tabloid press**: Daily Mail (UK), Bild (DE), Komsomolskaya Pravda (RU)
- **Right-populist**: Daily Wire / Breitbart (US), Republic World / Aaj Tak (IN), Junge Freiheit (DE), Sky News Australia
- **Multi-language native**: Russian-language Russia, Hindi (Aaj Tak, Bhaskar), Korean (Chosun), Spanish (Mexico, Spain, Argentina)
- **Pan-regional**: Middle East Eye, AfricaNews, The Diplomat
- **State-TV / religious**: Vatican News, France 24 AR/ES, Sputnik International, RT Africa

## File map

```
epistemic-lens/
├── README.md
├── meta_version.json          ← methodology pin (the spine)
├── meta.py                    ← loader/asserter/stamper
├── baseline_pin.py            ← pin bumper / CI check
├── stopwords.txt              ← pinned (hashed)
├── canonical_stories.json     ← pinned (hashed)
├── feeds.json                 ← 235 feeds, 54 buckets (hashed)
│
├── .github/workflows/
│   ├── daily.yml              ← 4-job daily cron
│   ├── meta-check.yml         ← required check (validate-meta + unit-tests)
│   ├── ci.yml                 ← unit/edge/e2e on code paths only
│   └── weekly_rot.yml         ← Sundays — feed rot report
│
├── .claude/prompts/
│   ├── daily_analysis.md      ← analyze job (haiku, JSON output)
│   └── draft_long.md          ← long-form draft (sonnet, prose output)
│
├── docs/api/schema/
│   ├── analysis.schema.json   ← canonical analysis shape
│   ├── thread.schema.json
│   ├── carousel.schema.json
│   └── long.schema.json
│
├── ingest.py                  ← parallel async RSS fetcher
├── extract_full_text.py       ← trafilatura + Wayback fallback
├── dedup.py                   ← URL canon + title near-dup
├── daily_health.py            ← health snapshot + bucket alerts
├── feed_rot_check.py          ← weekly rot detection
├── build_briefing.py          ← per-story corpus assembler
├── build_metrics.py           ← Jaccard + isolation + exclusive vocab
├── validate_analysis.py       ← schema + citation + number reconciliation
├── restamp_analyses.py        ← refresh meta_version on agent JSON output
├── render_analysis_md.py      ← JSON analysis → human MD
├── render_thread.py           ← analysis JSON → thread draft (template)
├── render_carousel.py         ← analysis JSON → carousel draft (template)
├── build_index.py             ← assemble api/ tree for GitHub Pages
│
├── tests.py / tests_edge.py / tests_e2e.py
│
├── web/                       ← static landing page
│   ├── index.html
│   ├── styles.css
│   └── app.js
│
├── snapshots/                 ← daily ingest output (data, grows daily)
├── briefings/                 ← per-story corpora + metrics
├── analyses/                  ← per-story JSON + MD analyses
├── drafts/                    ← thread/carousel/long-form drafts
│
├── video_template/            ← Remotion + React (dormant; available for future video work)
│   ├── package.json
│   └── src/...
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── COVERAGE.md
│   ├── OPERATIONS.md
│   ├── METHODOLOGY.md
│   ├── API.md
│   └── archive/               ← retired exemplars + prompts
│
└── archive/
    ├── scripts/               ← retired one-off scripts (analysis.py, gdelt_pull.py, baseline_pin_v0.py)
    └── review/                ← per-feed audit decisions (rot history)
```

## Cost

| Component | Cost |
|---|---|
| GitHub Actions (public repo, generous free tier) | $0 |
| GitHub Pages (public repo) | $0 |
| Python deps + sentence-transformers (cached embedding model) | $0 |
| Daily Claude analyze + draft jobs (subscription-billed via OAuth token) | $0\* |
| **Total ongoing** | **$0/mo** |

\* Uses a Claude.ai Pro/Max subscription via `claude setup-token`. Pro is more than enough for the current ~8 LLM calls/day. Implied metered cost is ~$2.30/day.

## Setup checklist

See `URGENT.md` for the one-shot setup checklist (push the `meta-v1.0.0` tag, paste the OAuth token, enable Pages, configure the branch ruleset, smoke-test the chain). ~15 min total at a computer; cron then runs unattended forever.

## Versioning

| Version | Date | Highlights |
|---|---|---|
| 0.2 | Mar 2026 | Initial: 51 feeds, 16 buckets, sequential ingest, Iran-war coverage |
| 0.4 | May 2026 | 138 feeds, 47 buckets, parallel ingest, full-text extraction, dedup, GH Actions |
| 0.4.x | May 2026 | +50 gap-fix feeds (tabloid + populist + native-language), structural diversification |
| 0.5.0 | May 2026 | Cleanup release. Briefing builder + voice + music + captions + video template. End-to-end at $0/mo. |
| 0.6–0.7.x | May 2026 | Creative pass: BBC voice, intro sting, world tickers, hero-quote layout, paradox split |
| 0.8.0 | May 2026 | Daily analyze job in cron: Claude Code Action writes `analyses/<date>_<story>.md` |
| **meta-v1.0.0** | **May 2026** | **Methodology pin baseline.** 235 feeds + tokenizer + clustering + extraction + signal_text + 5 canonical stories + 4 prompts all hashed in `meta_version.json`. CI enforces drift detection. |
| meta-v1.1.0 | May 2026 | Phase 0: agent commits its own work (claude-code-action sandboxing fix) |
| meta-v1.2.0 | May 2026 | Phase 1: JSON-first analyses + render_analysis_md.py + archive HORMUZ exemplar |
| meta-v1.3.0 | May 2026 | Phase 3: template-based thread + carousel drafts; long-form → Sonnet |
| meta-v1.4.0 | May 2026 | Phase 4: editorial validator (citation grounding + number reconciliation) |
| **meta-v1.4.1** | **May 2026** | **Current. Bug-fix on meta_version stamping, full end-to-end pipeline green.** |
