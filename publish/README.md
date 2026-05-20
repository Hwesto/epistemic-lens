# publish/ — Downstream content layer

This directory is the **publication side** of Epistemic Lens. It consumes
the research-data outputs of `core/` (briefings, analyses, sources) and
produces:

- Human-readable markdown
- Twitter / Threads / IG / LinkedIn drafts
- Long-form blog posts (LLM-written)
- The public JSON API tree served from GitHub Pages
- The static landing page at `hwesto.github.io/epistemic-lens/`
- Staged drafts for downstream poster bots

It's intentionally **separable** from the research core. The core
produces the data; this layer turns it into shipped content. In a
future refactor it could move to its own repo.

---

## Layout

```
publish/
├── README.md                          ← this file
├── render/                            ← analysis JSON → human/social outputs
│   ├── analysis_md.py                 ← analyses/<DATE>_<lineage_id>.json → MD
│   ├── sources_md.py                  ← source-attribution → MD
│   ├── thread.py                      ← analysis → X/Threads draft (template, no LLM)
│   ├── carousel.py                    ← analysis → IG/LinkedIn carousel (template)
│   ├── source_attribution.py          ← consumes sources/ artefacts
│   ├── stamp_long_drafts.py           ← stamps meta_version onto long-form
│   ├── translate.py                   ← machine translation for non-EN renders
│   └── prompts/
│       └── draft_long.md              ← long-form prose prompt (Sonnet)
│
├── api/                               ← public JSON tree → GitHub Pages
│   ├── build_index.py                 ← assembles api/ tree from data/
│   ├── page_renderers.py              ← per-page HTML renders
│   ├── card_renderers.py              ← card-format renders
│   ├── site_config.py                 ← landing-page configuration
│   ├── card_picker.json               ← picks which cards land on home
│   ├── today_picker.json              ← picks which clusters are "today's top"
│   └── schemas/                       ← JSON schemas served at /api/schema/
│       ├── analysis.schema.json
│       ├── briefing.schema.json
│       └── ...etc
│
├── distribute/                        ← poster-bot staging
│   ├── stage.py                       ← drafts/ → distribution/pending/
│   ├── publish.py                     ← post-approval publisher (manual gate)
│   ├── x_poster.py                    ← X/Twitter integration
│   └── youtube_shorts.py              ← shorts uploader (dormant)
│
├── web/                               ← static landing page (Pages root)
│   ├── index.html
│   ├── styles.css
│   └── app.js
│
├── video/                             ← Remotion + Python orchestrators (dormant)
│   ├── synthesize_voiceover.py
│   ├── render_video.py
│   ├── generate_music_bed.py
│   └── (Remotion React project)
│
└── video_scripts/                     ← per-day video scripts (when active)
```

---

## What it consumes

From `data/` (produced by `core/`):

- `data/analyses/<DATE>_<lineage_id>.json` — Claude's framing analyses
  (canonical product)
- `data/briefings/<DATE>_<lineage_id>.json` — per-cluster corpora
- `data/sources/<DATE>_<lineage_id>.json` — per-quote speaker attribution
- `data/coverage/<DATE>.json` — per-story × per-feed coverage matrix
- `data/trajectory/<lineage_id>.json` — frame-share trajectories per
  story over time

From `core/config/`:

- `meta_version.json` — methodology pin (stamped onto every published artefact)
- `outlets.json` — outlet metadata (used by renders to look up
  country/lang/lean for display)

---

## What it produces

For each day's top-salience clusters:

```
hwesto.github.io/epistemic-lens/api/<DATE>/<lineage_id>/
  briefing.json     ← from data/briefings/
  analysis.json     ← from data/analyses/
  analysis.md       ← rendered for human reading
  thread.json       ← X/Threads draft
  carousel.json     ← IG/LinkedIn deck
  long.json         ← LinkedIn/Substack long-form (Sonnet-written)
```

Plus the static site at `hwesto.github.io/epistemic-lens/` with a
landing page, a per-day index, and a JSON schema catalogue at
`/api/schema/`.

---

## How it runs

The `daily.yml` workflow runs this layer's `render` + `publish_api`
jobs **after** `core/`'s `analyze_render` completes. The split is
visible in the workflow as distinct job names; if you ever want to
extract this to its own repo, the surface area is:

- **Inputs:** the `data/` directory tree (or just the `analyses/`,
  `briefings/`, `sources/` subdirs)
- **Outputs:** the `api/` build tree + the staged drafts in
  `distribution/pending/`
- **Pins:** the `meta_version.json` from `core/config/` (stamped onto
  output JSON)

---

## What's NOT here

- The story matcher (lives in `core/cluster/`) — clustering is research-layer
- The framing analysis Claude prompts (`core/analyze/prompts/`) — same
- The LaBSE / e5 embedding model invocations (`core/embed/`) — same
- Calibration infrastructure — retired in v10 (canonical_stories.json gone)

`render/source_attribution.py` and `render/stamp_long_drafts.py` are
publication-layer helpers that consume `data/sources/` and
`data/drafts/long.json`. They live here because they're about RENDERING
the data, not producing it.

---

## Future work (deferred from v10)

- Retire `video/` if it stays dormant past v11
- Move `publish/` to its own repo once the data product matures
- Headline-body sensationalism index surface (already computed in
  `core/analyze/divergence.py`; not yet rendered)
- Auto-promotion UX for lineages that have persisted 30+ days (a
  human-review interface for the lineage tracker output in
  `data/archive/persistent_lineages_*.json`)
