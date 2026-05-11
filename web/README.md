# Web redesign — card-first draft

**Branch:** `claude/web-card-first-draft` (off main, trashable)
**Status:** design artifact for review. Not wired to the backend yet.
**For:** integration into the 3-way merge between `main`, `claude/review-branch-commercial-MFTEU` (audit / v2.9.0), and `claude/review-stress-test-06asX` (analytical / v8.0.0).

## What this is

A complete shape-change for the static site. The current `web/app.js` is a researcher-shaped multi-story dashboard. This replaces it with a **single-card daily moment**, designed for a non-researcher reader who arrives on mobile, scans for 5 seconds, and either screenshots/shares or taps into the depth.

The technical depth (trajectory, frame matrix, voices, methodology pin) doesn't go away — it moves to the story permalink at `/<date>/<story-key>/`. The home page becomes one card.

## What's in here

```
web/
├── README.md                 ← this file
├── index.html                ← home page · single card · server-rendered by build_index
├── styles.css                ← site shell + 5 card archetypes · ~350 lines · no build step
├── app.js                    ← ~50 lines · share / copy / keyboard nav only
└── samples/
    ├── index.html            ← menu — open this first
    ├── word.html             ← Word archetype preview
    ├── paradox.html          ← Paradox archetype preview
    ├── silence.html          ← Silence archetype preview
    ├── shift.html            ← Shift archetype preview
    └── echo.html             ← Echo archetype preview (Mondays only)
```

Open `web/samples/index.html` in a browser. Everything renders standalone — no server, no build, no dependencies.

## The brand

**"The Same Story"** — consumer-facing name for the project.
Tagline: *"how the world told the same news today"*.

The technical name `epistemic-lens` stays for the GitHub repo and methodology pages. "The Same Story" is what readers see.

## The five card archetypes

Each card is a single screenshot-ready unit. The daily cron picks ONE based on what's most striking. Rotation prevents fatigue; reader doesn't know what shape they'll get tomorrow.

| Archetype | Pulled from | Availability |
|---|---|---|
| **Word** | Within-language LLR distinctive vocab (`bucket_distinctive_vocab_llr`) | Daily — always available, fallback |
| **Paradox** | `analysis.paradox` field (opposing-bloc convergence detection) | Rare (~1 in 4 days) |
| **Silence** | Coverage matrix (4-state) + `analysis.silences` | Frequent when ≥10 buckets cover a story |
| **Shift** | Longitudinal trajectory + frame-id sequence | Needs 5+ days of story history |
| **Echo** | Weekly cross-outlet lag CCF (`lag/<a>__<b>.json`) | **Mondays only** (weekly job) |

Selection priority (in `build_index.pick_todays_card()`):
1. Monday + strong CCF → Echo
2. Strong paradox today → Paradox
3. Sharp silence (≥10 buckets covering, 1 doesn't) → Silence
4. Story with 5+ days trajectory + frame change → Shift
5. Fallback → Word (always works)

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

def write_index_html(card_html: str, archive: list) -> None:
    """Compose the home page shell + inline today's card HTML + the archive strip."""
```

### Required new schemas (Stage 14 discipline)

Wire these into `schemas_hash`:

- `today.schema.json` — the daily-card-pick artifact (`api/today.json`)
- `card.schema.json` — the card-payload shape (one of 5 archetype variants via `oneOf` on `kind`)

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

1. Open `web/samples/index.html` in a browser. Walk all five archetypes.
2. Read the audit branch's `docs/AUDIT_BACKLOG.md` for context on the methodology discipline.
3. Read the v8 branch's `analytical/longitudinal.py` and `analytical/within_language_llr.py` to understand the data feeding the Word and Shift cards.
4. Write `publication/build_index.pick_todays_card()` against the v8 data shapes.
5. Add Playwright. Render the first PNG. Compare to the HTML — they should look identical.
6. Replace the existing `web/index.html` with the server-rendered version that inlines today's card.

Trash this branch when done; the files are meant to be cherry-picked, not merged as-is.
