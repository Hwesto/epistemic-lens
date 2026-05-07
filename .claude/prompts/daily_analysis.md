# Daily Framing Analysis — Claude Code prompt

You are doing the **daily cross-country framing analysis** for the Epistemic
Lens dataset. You run on cron once a day, after the ingest + briefing pipeline
has produced today's corpora.

Your output is a markdown file per story in `analyses/<DATE>_<story_key>.md`.
That file is the **canonical analytical product** of this project. Downstream
formats (videos, carousels, newsletter posts) all derive from it later — do
not write a video script.

---

## Inputs

For each story you analyse:

- `briefings/<DATE>_<story_key>.json` — corpus. Each entry has:
  - `bucket` (country/region key like `usa`, `iran_opposition`)
  - `feed` (outlet name)
  - `lang`
  - `title`
  - `link`
  - `signal_level` (`body` | `summary` | `title`)
  - `signal_text` (the article body or fallback)
- `briefings/<DATE>_<story_key>_metrics.json` — precomputed numbers:
  - `pairwise_jaccard` (sorted, all bucket pairs)
  - `isolation` (per-bucket mean similarity, ascending = most isolated first)
  - `bucket_exclusive_vocab` (terms appearing in only one bucket, count ≥ 3)
  - `bucket_token_counts`, `n_buckets`, `n_articles`
- `docs/HORMUZ_CORRELATION.md` — **gold-standard exemplar**. Match its
  structure, voice, and density exactly.

---

## Procedure

1. List today's date with `date -u +%Y-%m-%d`.
2. Find every `briefings/<DATE>_*.json` that is **not** a `_metrics.json`.
3. For each briefing where `n_buckets >= 5`:
   a. Read the briefing and its `_metrics.json`.
   b. Read every `signal_text` in the corpus carefully — do not skim.
   c. Define 6–10 frames specific to **this** story by what the corpus
      actually contains. Do not reuse Hormuz's frame set.
   d. Build the bucket × frame matrix by reading the text. A bucket carries
      a frame if at least one of its articles makes that frame's claim.
   e. Identify 2–4 narrative arcs that group buckets together.
   f. Look for a **paradox**: a pair of buckets from opposing political blocs
      that arrive at the same analytical conclusion. Quote both verbatim.
      If no genuine paradox exists in the corpus, write "(none in this
      corpus)" — **do not invent one**.
   g. List buckets that should plausibly cover this story but didn't (or
      whose top item points elsewhere). This is silence-as-data.
   h. Write the file.
4. Skip stories with `n_buckets < 5` and note the skip in your final summary.
5. After all files are written, print a one-line summary per file: story key,
   n_buckets, paradox found (yes/no), output path.
6. Do **not** commit, push, or run git. The workflow handles that.

---

## Required output structure

The file must contain these sections **in this order**, matching
`docs/HORMUZ_CORRELATION.md`:

1. **Header block** (H1 + bold lines):
   - Story title
   - Date
   - Source (path to briefing JSON)
   - Coverage stats (n_buckets, n_articles, n_with_body)

2. **TL;DR** — 3–6 sentences. Lead with the single most surprising finding
   in the corpus, not a summary of the topic.

3. **Frame matrix (`<n> buckets × <m> frames`)** — fenced code block, fixed
   width, X for present and `.` for absent. Define your column abbreviations
   inline. Sort rows alphabetically.

4. **Frame totals across buckets** — table: `Frame | # buckets | Note`.
   The "Note" is your one-sentence interpretation per frame.

5. **The N story arcs** (where N is 2–4) — one `### Arc i — <name>` per
   arc, each with:
   - A blockquote of the characteristic lead sentence (verbatim from the
     corpus).
   - **Carriers**: list of outlet names.
   - One short paragraph on why this arc matters.

6. **Pairwise framing similarity (Jaccard, vocabulary overlap)** — fenced
   code block, top 15 pairs from `metrics.pairwise_jaccard`. Use the numbers
   verbatim. Annotate noteworthy pairs with `← <one-line reason>`.

7. **Most isolated buckets** — fenced code block, top 8 from
   `metrics.isolation`. Numbers verbatim. Then one paragraph explaining
   whether the isolation is linguistic (different language) or genuinely
   editorial (distinct framing).

8. **Bucket-exclusive vocabulary** — table:
   `Bucket | Distinctive terms | What it reveals`. Pull the top 3–5 terms
   per bucket from `metrics.bucket_exclusive_vocab`. Skip buckets with
   nothing exclusive.

9. **The paradox** (or "No paradox in this corpus") — H2 section with the
   pair you identified, both quotes verbatim, attribution per outlet, and
   a one-paragraph interpretation. If no paradox exists, briefly explain
   why (e.g. "all buckets converge on the same wire framing").

10. **What's missing (silence as data)** — bulleted list of buckets that
    plausibly should have covered this and didn't, with one line each on
    what their top item *was* about.

11. **Most striking single-outlet findings** — numbered list of up to 10
    items, each: `**<Outlet>**: <one-sentence finding>`.

12. **Candidate angles for downstream rendering** — 3–4 H3 angles, each a
    short paragraph. These are framings you could build a video, carousel,
    or essay around. Do **not** write the script — describe the angle.

13. **Recap of method** — one paragraph naming the briefing source, the
    metrics file, and the limitations (e.g. "frame assignment by reading
    body text, not regex").

14. **Bottom line** — 2–3 sentences restating the headline finding.

---

## Hard rules

- **Verbatim quotes only.** Every blockquote must be copy-pasted from a
  `signal_text` field. No paraphrase, no composite sentences. Cite the
  outlet next to the quote.
- **Numbers from metrics.json only.** Never invent a Jaccard score or a
  bucket count. If a number isn't in the metrics file, don't put one in
  the analysis.
- **Frames are story-specific.** Re-derive the frame set every time. Do
  not reuse Hormuz frames (US_VICTORY, IRAN_VICTORY, etc.).
- **No video scripts.** This file is the analysis. Downstream formats
  consume it later.
- **No padding.** Better to write `(none)` than to fill a section with
  generic prose.
- **One file per story.** Write to `analyses/<DATE>_<story_key>.md`. Do
  not create extra files.
- **Skip <5 bucket stories.** Note the skip; do not write a partial file.
