# Web redesign — card-first draft

**Branch:** `claude/web-card-first-draft` (off main, trashable)
**Status:** design artifact for review. Not wired to the backend yet.
**Target merge branch:** `claude/merge-analytics-integration-xdbJs` (the active integration of `main` × audit × v8 — currently at meta-v8.5.2 with 8 PRs already landed). When this design is picked up, it goes into THAT branch, not main directly.

**Brand:** "The Same Story" — consumer-facing. The technical repo name `epistemic-lens` stays for the methodology pages and the GitHub repo.

## What this is

A complete shape-change for the static site. The current `web/app.js` is a researcher-shaped multi-story dashboard. This replaces it with a **single-card daily moment**, designed for a non-researcher reader who arrives on mobile, scans for 5 seconds, and either screenshots/shares or taps into the depth.

The technical depth (trajectory, frame matrix, voices, methodology pin) doesn't go away — it moves to the story permalink at `/<date>/<story-key>/`. The home page becomes one card.

## What's in here

```
web/
├── README.md                 ← this file
├── index.html                ← home page · single card · server-rendered by build_index
├── styles.css                ← site shell + 7 card archetypes · ~540 lines · no build step
├── app.js                    ← ~50 lines · share / copy / keyboard nav only
├── samples/
│   ├── index.html            ← menu — open this first
│   ├── word.html             ← Word archetype preview
│   ├── paradox.html          ← Paradox archetype preview
│   ├── silence.html          ← Silence archetype preview
│   ├── shift.html            ← Shift archetype preview
│   ├── sources.html          ← Sources archetype preview (NEW — needs merge-branch data)
│   ├── tilt.html             ← Tilt archetype preview (NEW — needs merge-branch data)
│   └── echo.html             ← Echo archetype preview (Mondays only)
└── screenshots/              ← Playwright renders (desktop + share + mobile) for review
```

Open `web/samples/index.html` in a browser. Everything renders standalone — no server, no build, no dependencies.

## The brand

**"The Same Story"** — consumer-facing name for the project.
Tagline: *"how the world told the same news today"*.

The technical name `epistemic-lens` stays for the GitHub repo and methodology pages. "The Same Story" is what readers see.

## The seven card archetypes

Each card is a single screenshot-ready unit. The daily cron picks ONE based on what's most striking. Rotation prevents fatigue; reader doesn't know what shape they'll get tomorrow.

| Archetype | Pulled from (merge-branch schemas) | Availability |
|---|---|---|
| **Word** | Within-language LLR distinctive vocab. Each row carries an italic bracketed translation (added 11 May, see screenshots). | Daily — always available, fallback |
| **Paradox** | `analysis.paradox` (opposing-bloc convergence) | Rare (~1 in 4 days) |
| **Silence** | `coverage.schema.json` (4-state) + `analysis.silences`. Big-absent-flag-with-X design (redesigned 11 May). | Frequent when ≥10 buckets cover a story |
| **Shift** | `trajectory.schema.json` + frame-id sequence + PR 5's article-level provenance | Needs 5+ days of story history |
| **Sources** | `sources.schema.json` + PR 3's `speaker_affiliation_bucket` / `speaker_affiliation_kind` | Daily — every story with quotes |
| **Tilt** | `tilt.schema.json` + PR 7's second anchor (`bucket_mean` alongside wire) | Weekly (Mondays or Fridays) |
| **Echo** | `cross_outlet_lag.py` output (CCF). No schema pinned yet on the merge branch — needs `lag.schema.json` before this card ships. | Mondays only |

Selection priority (in `build_index.pick_todays_card()`):
1. Monday + strong tilt drift → Tilt
2. Monday + strong CCF → Echo
3. Strong paradox today → Paradox
4. Sharp silence (≥10 buckets covering, 1 doesn't) → Silence
5. Outlet with stark speaker-type imbalance (e.g. 0 civilians) → Sources
6. Story with 5+ days trajectory + frame change → Shift
7. Fallback → Word (always works)

(Tilt and Echo could share Monday with a sub-priority based on signal strength; or alternate weeks.)

## How the next LLM should integrate this

The merge plan (separate document) has a PR sequence. This belongs in **a PR after PR 1 (schemas_hash retrofit)** because it touches build_index.

### Required backend additions

In `publication/build_index.py`:

```python
def pick_todays_card(date: str, stories: list) -> dict:
    """Selector — returns one of {kind: word|paradox|silence|shift|echo, ...payload}.
    Output stamped with meta_version; the choice is reproducible + challengeable."""

def render_card_html(card_data: dict, template_path: Path) -> str:
    """Server-side render: read the card-template HTML, inject card_data, return HTML."""

def render_card_png(card_html: str, out_path: Path, width=1200, height=675) -> Path:
    """Playwright screenshot at fixed 1200x675 → social-share PNG."""

def write_index_html(card_html: str, today_strip: list, archive: list) -> None:
    """Compose the home page: card + 'Also today' strip + archive + footer."""

def render_today_strip(stories_today: list, picked_key: str) -> str:
    """Render the 4-tile 'Also today' strip below the daily card.
    Inputs: today's stories minus the one picked for the daily card.
    Each entry needs: key (for URL), card_kind (the archetype the picker
    WOULD have used for THIS story), event_summary, finding_synthesis.
    Returns empty string if there are no other stories — production
    omits the entire section in that case."""
```

### Required new schemas (Stage 14 discipline)

Wire these into `schemas_hash`:

- `today.schema.json` — the daily-card-pick artifact (`api/today.json`)
- `card.schema.json` — the card-payload shape (one of 7 archetype variants via `oneOf` on `kind`)

### Required new fields on existing `analysis.schema.json`

- `event_summary` — optional string. One short neutral-voice paraphrase of what happened (~12-20 words). Used by:
  - the card's kicker line (between headline and content)
  - the "Also today" strip's primary headline for each other story

  If absent on legacy artifacts, build_index falls back to the first sentence of `analysis.tldr`. New stories should populate `event_summary` explicitly — the prompt should ask for it as a separate field from `tldr` so the editorial tone of tldr can be distinct from the neutral-voice event paraphrase.

### Required new fields on `index.schema.json` per-story entries

Currently `api/<date>/index.json.stories[]` carries `{key, title, n_buckets, n_articles, has, artifacts, top_isolation_bucket, paradox}`. Add:

- `event_summary` — copied from the story's `analysis.event_summary`
- `card_kind` — which archetype the picker WOULD have chosen for THIS story (`"word" | "paradox" | "silence" | "shift" | "sources" | "tilt" | "echo"`). Computed via the same `pick_todays_card()` logic applied per-story not per-day. Needed for the "Also today" strip's badge.
- `finding_synthesis` — optional short string (~10-15 words) — the framing punchline, used as secondary text in the "Also today" tile. Could be derived from the archetype's content (e.g. for a Word card story: "Six words across six countries" — auto-generated, doesn't need a new LLM call).

### Required new artifacts written by build_index

- `api/today.json` — today's card pick (meta_version stamped)
- `api/today.png` — Playwright screenshot, 1200×675, used for og:image + share
- `api/<date>/card.json` + `api/<date>/card.png` — per-date archive entries
- `api/<date>/<story>/card.png` — story-specific share image used on the permalink

### Required Playwright dep

New entry in `requirements.txt` (core, not video):

```
playwright>=1.40,<2.0   # server-side PNG generation for share cards
```

Plus a post-install step in CI: `playwright install chromium --with-deps`.

### Required CSS classes consumed by the JS

The selector and Playwright renderer interact with these stable class names:

- `.card` — wraps every card
- `.card--{kind}` — modifier per archetype (`word|paradox|silence|shift|echo`)
- `.card-eyebrow`, `.card-headline`, `.card-content`, `.card-byline` — scaffold
- Per-archetype content classes documented in `styles.css` comments

If the next LLM restructures the CSS, keep these names — `app.js` and the Playwright template read them.

## Copyright posture

The cards are built around:
- Distinctive vocab words (facts, our analysis) — Word card
- Short verbatim quotes ≤25 words, attributed — Paradox + Echo cards
- Coverage facts (which bucket did/didn't cover) — Silence card
- Frame labels from our pinned codebook — Shift card

What we never put on a card:
- Full article body text
- Source-article images / logos beyond flag emojis
- Quotes longer than ~25 words
- Unattributed text in display type

## What's NOT in this branch

Deliberately out of scope for this design draft:

- Permalink page (`/<date>/<story>/`) — that's a separate larger redesign of the existing dashboard logic
- Archive grid page (`/archive/`)
- Methodology and corrections pages
- The Playwright PNG generation code itself (just the template the LLM should consume)
- The selector logic itself (just the data contract)
- Wiring to the v8 branch's data outputs

The next LLM should treat this as a **visual spec + scaffold** for the home page only. The rest extends naturally from here.

## Open design questions for the next LLM

1. **Aspect ratio on mobile.** The card uses `aspect-ratio: 1200/675` at ≥720px and grows naturally below. Worth checking on real phones — may need to drop the aspect ratio entirely on mobile and let content set height.
2. **Dark mode.** The `@media (prefers-color-scheme: dark)` block exists but hasn't been verified to look good for every archetype, especially Silence (the grayed-out flag treatment is light-mode-tuned).
3. **RTL languages.** The Word card displays Arabic and Chinese inline. Browser handles this OK on its own but RTL text in a left-aligned word column may want explicit `dir="auto"`.
4. **The accent color.** `#b03a1f` (newspaper red) is a starting point. Worth a brand call.
5. **Brand mark typography.** Currently just letter-spaced uppercase. A small SVG monogram might earn its place if the project sticks.

## Suggested first action for the next LLM

1. Open `web/samples/index.html` in a browser. Walk all SEVEN archetypes (Word, Paradox, Silence, Shift, Sources, Tilt, Echo).
2. Read the merge branch's existing `web/` — it currently has the old multi-story dashboard plus `corrections.html` and `methodology-challenge.html`. Decide which to keep:
   - **Keep** `corrections.html` + `methodology-challenge.html` (they're the credibility layer; this design doesn't replace them)
   - **Replace** `index.html`, `app.js`, `styles.css` with the versions from this branch
   - **Add** the `samples/` and `screenshots/` directories as design reference (optional — can delete after integration if desired)
3. Read the merge branch's `analytical/within_language_llr.py`, `analytical/source_attribution.py`, `analytical/tilt_index.py`, `analytical/longitudinal.py` to understand the data feeding the cards.
4. Write `publication/build_index.pick_todays_card()` against the merge-branch data shapes — selector priority documented in the table above.
5. Pin a new schema: `today.schema.json` for the card-pick artifact (`api/today.json`). Add to `meta.schemas_hash` (existing discipline on the merge branch).
6. Add Playwright. Render the first PNG. Compare to the HTML — they should look identical.
7. Replace the merge branch's `web/index.html` with the server-rendered version that inlines today's card. Methodology + corrections pages stay as-is.
8. The `lag.schema.json` is NOT yet pinned on the merge branch — the Echo card can be deferred to a follow-up PR that adds it.

Trash this branch when done; the files are meant to be cherry-picked, not merged as-is.

## Specifically what to keep vs replace on the merge branch's web/

```
merge-branch's web/                 action
─────────────────────────────────   ───────────────────────────────────────
index.html                          REPLACE with this branch's home page
app.js                              REPLACE with this branch's minimal app.js
styles.css                          REPLACE with this branch's styles.css (~540 lines, 7 archetypes)
corrections.html                    KEEP — accountability layer from PR 6+
methodology-challenge.html          KEEP — accountability layer from PR 6+
(no samples/)                       OPTIONAL — bring across for reference, can delete later
(no screenshots/)                   OPTIONAL — bring across for review, can delete later
```

If `methodology-challenge.html` and `corrections.html` use different design tokens, port them to the `--bg / --ink / --accent` variable set in this branch's `styles.css` for visual consistency — they can keep their layout, just adopt the palette.
