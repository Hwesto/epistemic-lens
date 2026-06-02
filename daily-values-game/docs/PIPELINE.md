# Content pipeline — experiment design + editorial

Not "a feature" — the operation the product lives or dies on. It is experiment
design **and** taste. LLM cost lives **only here** (~1 generation/day + offline
tagging, amortised across all users — trivial and fixed).

## The 7 steps (§6)

1. **PLAN** — Read the coverage tracker (`coverage` view): which edge / scope /
   framing is under-target? Is an anchor due for a re-run? Is an exploratory slot
   needed?
2. **DRAFT** — Opus drafts a dilemma targeting that exact cell (offline, batch).
3. **CURATE** — Human judges: stake-y? valence-neutral (no "right answer")? clean
   fork? not preachy? — **the bar AI is worst at and the product depends on.**
4. **TAG** — Assign `axis_loadings` (PRIOR) + edge/scope/framing/process/anchor/
   exploratory (Opus proposes, human confirms), stamped with `framework_version`.
5. **ASSET** — Art (constrained signature style) + audio (your voice).
6. **SCHEDULE** — Assign `publish_date`; everyone gets the same story that day.
7. **BUFFER** — Keep 30–90 stories scheduled ahead — **never write day-of.**

## The admin tool

Build a tiny internal admin tool (protected): plan against tracker → draft → edit
→ tag → preview → schedule. More important than half the user-facing features and
routinely forgotten. The import path is stubbed at
`apps/api/api/admin/import-story.ts`.

**Anchors are immutable.** The tool must prevent editing an anchor gate — editing
it silently destroys its measurement value. The DB enforces this too
(`gates_protect_anchors` trigger) and the import endpoint refuses anchor edits.

## The treadmill warning

The pipeline reduces the **writing** burden, not the **editorial** one. Curation
(taste, neutrality, clean forks) can't be automated and is the daily treadmill
that broke Wordle's solo founder — and yours is heavier (a crafted, tagged story
every day). **Staff and buffer it accordingly.**

The first ~30 stories are a hand-authored coverage sweep, **anchors planted from
day one.** After that, Opus drafts more; a human still curates every one.
