# Handoff to the integration LLM

**Source branch:** `claude/web-card-first-draft` at commit `22e20dd`
**Target branch:** `claude/merge-analytics-integration-xdbJs` (currently at meta-v8.5.2)

This is a complete card-first redesign of the static site, designed against the actively-merging analytical pipeline. **Not a wholesale merge** — files are meant to be cherry-picked into the target branch's `web/` directory.

## TL;DR for the LLM

The current `web/` on the merge branch is a researcher-shaped multi-story dashboard. Replace it with a **single-card daily moment** + an **"Also today" strip** for cross-story discovery. The brand is **"The Same Story"** (consumer surface); `epistemic-lens` stays as the technical name on methodology pages.

Walk `web/samples/index.html` in a browser to see all 7 card archetypes. Walk `web/screenshots/` for the rendered references.

## What ships in this handoff

```
web/
├── HANDOFF.md            ← this file
├── README.md             ← detailed integration notes (also worth reading)
├── index.html            ← home page · single daily card · "Also today" strip · archive · footer
├── styles.css            ← shell + 7 card archetypes + Also-today strip (~600 lines, no build)
├── app.js                ← ~50 lines · share / copy / keyboard nav
├── samples/              ← 7 standalone archetype previews + a menu
└── screenshots/          ← Playwright renders at desktop/share/mobile sizes for review
```

## The seven card archetypes

The daily picker chooses ONE based on what's most striking. Rotation prevents fatigue.

| # | Archetype | Source data (merge-branch schemas) | Availability |
|---|---|---|---|
| 1 | **Word** | within-language LLR distinctive vocab | Daily fallback (always works) |
| 2 | **Paradox** | `analysis.paradox` (opposing-bloc convergence) | Rare (~1/4 days) |
| 3 | **Silence** | `coverage.schema.json` + `analysis.silences` | When ≥10 buckets cover one story |
| 4 | **Shift** | `trajectory.schema.json` + PR 5 article-provenance | Needs 5+ days of story history |
| 5 | **Sources** | `sources.schema.json` + PR 3 speaker affiliation | Daily |
| 6 | **Tilt** | `tilt.schema.json` + PR 7 second anchor | Weekly (Mondays/Fridays) |
| 7 | **Echo** | `cross_outlet_lag.py` output (NO schema yet) | Mondays — DEFER until `lag.schema.json` lands |

Selector priority (in `build_index.pick_todays_card()`):
1. Monday + strong tilt drift → **Tilt**
2. Monday + strong CCF correlation → **Echo** (once lag schema exists)
3. Strong paradox today → **Paradox**
4. Sharp silence (≥10 buckets covering, 1 doesn't) → **Silence**
5. Outlet with stark speaker imbalance (e.g. 0 civilians) → **Sources**
6. Story with 5+ day trajectory + frame change → **Shift**
7. Fallback → **Word** (always available from LLR)

## Card reading order (the structural template)

Every card has five elements in this order:

```
[BRAND] [DATE]
[EYEBROW — the angle, e.g. "WHOSE VOICES GOT PLATFORMED"]
[HEADLINE — the framing finding, italic serif]
[KICKER — what actually happened, plain neutral voice]   ← THE STORY ANCHOR
[CONTENT — the receipts (words / quotes / flags / bars)]
[BYLINE — sources count · see-how link]
```

The kicker is the reader's entry into the story. It says *what happened* in plain English (~12-20 words, our paraphrase, neutral voice) BEFORE the framing finding lands. Without it, "guerra / accord / deal / 协议" is abstract; with it, the reader has context.

## Home page sequence

```
[DAILY CARD — single screen, hero]
[Share · Copy · Download · yesterday · archive]    ← actions
[ALSO TODAY — 2-4 mini-tiles of other stories analyzed today]   ← bridge
[THIS WEEK — 5-day archive of past daily cards]    ← deeper history
[FOOTER — methodology · corrections · subscribe · pin badge]
```

The "Also today" strip closes the cross-story gap. Each mini-tile shows: archetype badge + event paraphrase (primary text) + framing punchline (secondary). Tap → that story's permalink.

## Required backend additions

### 1. New Python in `publication/build_index.py`

```python
def pick_todays_card(date: str, stories: list) -> dict:
    """Returns {kind, ...payload} per the priority cascade above.
    Output is a stamped artifact (api/today.json) so the choice is
    reproducible + challengeable."""

def pick_per_story_card_kind(story: dict) -> str:
    """Apply the same archetype priority to a SINGLE story (not per-day).
    Returns the kind that would have been picked if this story had won
    the daily slot. Used to populate the 'Also today' strip badges."""

def render_card_html(card_data: dict, template_path: Path) -> str:
    """Server-side render: read card-template HTML, inject card_data."""

def render_card_png(card_html: str, out_path: Path,
                    width=1200, height=675) -> Path:
    """Playwright screenshot at fixed 1200x675 → social-share PNG.
    Add browser=chromium dependency."""

def render_today_strip(stories_today: list, picked_key: str) -> str:
    """Render the 4-tile 'Also today' strip. Empty string if no
    other stories — production omits the section entirely."""

def write_index_html(card_html: str, today_strip: str,
                     archive: list) -> None:
    """Compose the home page: card + actions + today_strip + archive."""
```

### 2. New schemas (Stage 14 discipline — add to `schemas_hash`)

- `today.schema.json` — shape of `api/today.json` (the daily card pick)
- `card.schema.json` — shape of the per-card payload (`oneOf` 7 archetype variants by `kind`)

### 3. New fields on existing schemas

**`analysis.schema.json`** — add optional `event_summary` field. The neutral-voice paraphrase of the event (~12-20 words). Used by the card kicker AND by the "Also today" strip. Production should add this to the agent prompt as a SEPARATE field from `tldr` (so the editorial tone of tldr stays distinct from the neutral-voice event paraphrase). Legacy artifacts without it: fall back to first sentence of `analysis.tldr`.

**`index.schema.json`** — add three per-story fields:
- `event_summary` — mirrors `analysis.event_summary`
- `card_kind` — which archetype the picker WOULD have chosen for THIS story (one of 7)
- `finding_synthesis` — short framing punchline (~10-15 words). Derived not LLM-generated. For Word card stories: "Six words across six countries". For Paradox: "Both said [X]". Etc.

### 4. New artifacts written by build_index

```
api/today.json                     ← daily card pick (meta_version stamped)
api/today.png                      ← 1200×675 Playwright share render
api/<date>/<story>/card.png        ← per-story share image, used on permalink
```

### 5. New dep in `requirements.txt` (core, not video)

```
playwright>=1.40,<2.0     # server-side PNG generation for share cards
```

Plus a CI step: `playwright install chromium --with-deps`.

## Stable contracts the JS reads

The minimal `app.js` reads these CSS class names. Don't rename them on integration:

- `.card` — wraps every card
- `.card--{kind}` — archetype modifier (`word|paradox|silence|shift|sources|tilt|echo`)
- `.card-eyebrow`, `.card-headline`, `.card-kicker`, `.card-content`, `.card-byline`
- `data-action="share"`, `data-action="copy-link"` — button hooks
- `a[rel="prev"]`, `a[rel="next"]` — keyboard nav hooks

## What's on the merge branch's current web/ — keep vs replace

| File | Action | Why |
|---|---|---|
| `index.html` | **REPLACE** with this branch's | Old dashboard shape |
| `app.js` | **REPLACE** with this branch's | Minimal ~50 lines vs the old 331-line dashboard |
| `styles.css` | **REPLACE** with this branch's | New card system + Also today strip + 7 archetypes |
| `corrections.html` | **KEEP** | Accountability layer from merge-branch PR 6+ |
| `methodology-challenge.html` | **KEEP** | Accountability layer from merge-branch PR 6+ |

If `corrections.html` + `methodology-challenge.html` use different CSS tokens than this branch's `--bg / --ink / --accent / --rule`, port them to the new tokens for visual consistency. Their layout/content stays; just the palette aligns.

## Copyright posture (already baked into the design)

The card system is built around:
- **Distinctive vocab words** (facts, our analysis) — Word card
- **Short verbatim quotes ≤25 words, attributed** — Paradox + Echo
- **Coverage facts** (which bucket did/didn't) — Silence
- **Frame labels from our pinned codebook** — Shift
- **Speaker counts and types** (numbers, our analysis) — Sources
- **Tilt scores** (log-odds, our analysis) — Tilt

Never on a card:
- Full article body text
- Source-article images / logos beyond flag emojis
- Quotes >25 words
- Unattributed text in display type

## Copyright posture for the kicker line specifically

The kicker is OUR paraphrase of what happened, neutral voice, no attribution needed. Treat it like the lead sentence of an analyst's summary — original creative work, not a reproduction of any source. The agent prompt for `event_summary` should explicitly say: "neutral one-sentence paraphrase, no verbatim quoting, no attribution required."

## Suggested integration sequence

This belongs as a PR (or PR sequence) on the merge branch AFTER the foundation PRs are stable. Suggested split:

**PR A — backend prep**
- Add `event_summary` field to `analysis.schema.json` (optional). Pin bump minor.
- Backfill existing analyses with first-sentence fallback (or null).
- Update the agent prompt to ask for `event_summary` as a separate field.
- Add `card_kind` + `finding_synthesis` to `index.schema.json` per-story entries. Pin bump minor.

**PR B — new schemas**
- Add `today.schema.json` + `card.schema.json` to `docs/api/schema/`.
- Wire into `schemas_hash`.
- Tests: TestSchemaCorpus auto-covers, but worth a TestCardSchema that validates each archetype variant.

**PR C — web replacement**
- Replace `web/index.html`, `web/app.js`, `web/styles.css` with this branch's.
- Bring `web/samples/` and `web/screenshots/` across as design reference (delete after if desired).
- Keep `corrections.html` + `methodology-challenge.html`; port their CSS tokens to align with the new palette.

**PR D — build_index extension**
- Add `pick_todays_card()`, `pick_per_story_card_kind()`, `render_card_html()`, `render_card_png()`, `render_today_strip()`, `write_index_html()`.
- Add Playwright dep + CI install step.
- Tests: TestBuildIndex extends to cover the new functions + the new fields on `index.json`.

**PR E — Echo card schema (deferred)**
- Add `lag.schema.json` for the `cross_outlet_lag.py` outputs.
- Wire `schemas_hash`.
- Echo card now formally contracted and can ship in the Monday rotation.

## Open design questions left for the integration LLM

1. **Aspect ratio on real mobile.** The card uses `aspect-ratio: 1200/675` at ≥720px viewports and grows naturally below. Worth verifying on real phones.
2. **Dark mode.** `@media (prefers-color-scheme: dark)` block exists but only minimally tested. The Silence card's grayed-flag treatment in particular needs a dark-mode check.
3. **RTL languages.** Arabic and Hebrew appear in the Word card. Browser handles inline RTL OK but the left-aligned word column may want explicit `dir="auto"` for RTL words.
4. **The accent color (`#b03a1f`).** Newspaper-red on cream paper. Worth a brand-call.
5. **`og:image` per archetype.** Each archetype could have a tuned share image at 1200×675. Right now they all use `/today.png`. Worth specifying.

## Trash policy

This branch (`claude/web-card-first-draft`) is **trashable** once integrated. Cherry-pick the files, take the screenshots as reference, delete the branch. Nothing here needs long-term maintenance — it's a design artifact, not source of truth.

