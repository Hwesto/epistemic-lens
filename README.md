# Epistemic Lens v0.4

Cross-national news comparison using multilingual embeddings. No translation needed.

## What it does

1. Pulls RSS feeds from **138 outlets across 47 country/region buckets** in 16+ languages
2. Embeds all articles into a shared vector space using `paraphrase-multilingual-MiniLM-L12-v2`
3. Auto-clusters articles by topic across languages
4. Scores convergence (adversarial agreement = likely facts)
5. Computes newspaper-to-newspaper similarity matrix (who echoes whom)
6. Generates a Claude-ready analysis prompt
7. (Optional) Cross-references against **GDELT 2.0** for global-coverage backstop

## Daily pipeline

```bash
python ingest.py          # fetch + embed + cluster (~1-2 min)
python dedup.py           # collapse near-duplicates within the day
python daily_health.py    # post-pull health snapshot
# Weekly:
python feed_rot_check.py  # detect persistent rot
# Optional:
python gdelt_pull.py gkg     # latest GDELT firehose snapshot
python gdelt_pull.py breadth # per-cluster global breadth check
```

## Automation (GitHub Actions)

Three workflows under `.github/workflows/`:

| Workflow | Trigger | Job |
|---|---|---|
| `daily.yml` | cron `0 7 * * *` UTC | ingest → dedup → daily_health → commit `snapshots/` |
| `weekly_rot.yml` | cron `0 9 * * 0` UTC (Sundays) | feed_rot_check → commit `review/` |
| `ci.yml` | push/PR on `main` & `claude/**` | unit + edge tests; e2e smoke only on main |

Each workflow caches the embedding model (~500MB) and pip wheels. Both cron jobs commit with `epistemic-lens-bot` and retry-on-conflict push (rebase + 3 attempts). Daily run posts a job summary with feeds / items / errors / bucket alerts to the GitHub Actions UI.

> **Note:** Scheduled workflows run from the default branch only. New workflow definitions take effect once merged to `main`.

## Daily outputs (in snapshots/)

| File | Purpose |
|---|---|
| `YYYY-MM-DD.json` | Raw items + per-feed metadata (`fetch_ms`, `http_status`, `bytes`, `error`) + per-item flags (`summary_chars`, `is_stub`, `is_google_news`, `published_age_hours`, `canonical_url`, `normalised_title`) |
| `YYYY-MM-DD_convergence.json` | Topic clusters with `country_count`, `mean_similarity`, `articles[]` |
| `YYYY-MM-DD_similarity.json` | Newspaper-to-newspaper similarity matrix |
| `YYYY-MM-DD_dedup.json` | Deduplicated item list with multi-source attribution |
| `YYYY-MM-DD_health.json` | Per-day health: errors, stubs, slow, bucket alerts |
| `YYYY-MM-DD_pull_report.md` | Human-readable pull summary |
| `YYYY-MM-DD_prompt.md` | Pre-rendered briefing prompt |

## Pipeline tunables (env vars)

| Var | Default | Effect |
|---|---|---|
| `MAX_ITEMS` | 50 | Items pulled per feed |
| `MAX_WORKERS` | 30 | Parallel fetch workers |
| `PER_HOST_DELAY` | 1.0 | Seconds between requests to same host |
| `FETCH_TIMEOUT` | 20 | Per-request timeout (s) |
| `SKIP_EMBED` | 0 | Set to `1` for fetch-only run (no model load) |
| `OUTPUT_DIR` | `snapshots` | Where to write daily files |
| `FEEDS_CONFIG` | `feeds.json` | Source feed list |

## Coverage (v0.4)

| Region | Buckets / outlets |
|---|---|
| North America | usa (CNN, Fox, NPR, Politico, Axios, Hill), canada (CBC) |
| Latin America | brazil (Folha, O Globo), mexico, argentina_chile, colombia_ven_peru |
| Western Europe | uk (BBC, Guardian, Telegraph), wire_services (Reuters, AP, AFP/F24, Le Monde, Le Figaro, Liberation), germany (DW EN/DE/RU, Spiegel, Tagesschau), italy, spain, netherlands_belgium |
| Eastern Europe | russia (TASS, RT, Meduza, Moscow Times), russia_native (Lenta, Kommersant, RIA, Novaya Gazeta), ukraine (Pravda EN, Kyiv Post, Ukrinform), poland_balt, balkans, hungary_central, belarus_caucasus |
| Nordic | nordic (Yle, Local SE/DE) |
| Middle East | iran_state (IRNA, Tehran Times, Mehr, Press TV alt), iran_opposition (Iran International, RFE/RL), israel (Haaretz, JPost, ToI, Ynet), qatar (Al Jazeera EN/AR), saudi_arabia (Arab News, Al Arabiya), turkey (Sabah, Hurriyet, Anadolu, Bianet, Hurriyet Daily), egypt (5 outlets), syria, palestine, jordan, lebanon, iraq |
| South Asia | india (TOI, NDTV, Hindu, Bhaskar), pakistan (Dawn, Geo, ARY, Express Tribune) |
| East Asia | china (CGTN, Xinhua, Global Times, People's Daily), japan (NHK, Japan Times), south_korea (Yonhap, Korea Herald), taiwan_hk (Taipei Times, HKFP, SCMP), korea_north (NK News, Daily NK) |
| SE Asia / Pacific | indonesia, philippines, vietnam_thai_my (CNA, Straits, Bangkok Post, VnExpress, Malay Mail), australia_nz |
| Africa | nigeria (Punch, Vanguard), south_africa, kenya, africa_other (AllAfrica, Premium Times, Addis) |

## Status flags in feeds.json

- `OK` — feed live, returns parseable items, real summaries
- `STUB` — title-only feed (Lenta, RIA, ARY News, Taipei Times) — useful for headline tracking, not for embedding nuance
- `RETRY` — 403/429 from probe container; expected to work from production IP. Examples: Guardian, Telegraph, Le Monde, Times of Israel, Times of India

## The principle

The propaganda is the data. Nothing is filtered or rated.

- **Convergence** across adversarial sources = closest thing to truth
- **Divergence** on the same story = framing / spin
- **Absence** from a story = editorial control

## Project history / version notes

- **v0.2** — initial 51-feed sequential pipeline, feedparser, MAX_ITEMS=10
- **v0.4** (this version) — 138 feeds, parallel fetch, per-domain rate limiting, retries, sitemap fallback, per-item quality flags, dedup layer, GDELT bolt-on, daily/weekly health scaffolding. xml.etree replaces feedparser as parser. See `migration_notes.md` for the v0.3 → v0.4 source diff and `before_after.md` for v0.2 → v0.4 coverage delta (8.2× items, +31 buckets, 0 → 170 Cyrillic titles).

## Files in repo

```
ingest.py              # main pipeline (fetch + embed + cluster)
dedup.py               # URL canon + title near-dup collapsing
daily_health.py        # post-pull health report
feed_rot_check.py      # weekly rot detection
gdelt_pull.py          # GDELT 2.0 breadth supplement
analysis.py            # cross-day analytical metrics (country pairs, silence audit)
analysis2.py           # framing comparison and cluster side-by-sides
source_audit.py        # static + live audit of source list
baseline_pin.py        # snapshot pre-refactor state for A/B
before_after.py        # produces before_after.md for v0.2 vs v0.4
candidate_probe.py     # initial candidate validation (Phase 2)
candidate_alternates.py# alternate-URL probes (Phase 2b)
merge_candidates.py    # Phase 3 merge into feeds.json
feeds.json             # 138 feeds across 47 buckets (v0.4.0)
feeds.json.bak         # rollback to v0.3 if needed
migration_notes.md     # v0.3 -> v0.4 source-list diff
before_after.md        # v0.2 -> v0.4 coverage validation
```
