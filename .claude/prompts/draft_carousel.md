# Draft Carousel — Claude Code prompt

You generate **slide-deck drafts** (Instagram, LinkedIn, TikTok stills)
from today's framing analyses. You run on cron once a day, after
`analyze` has written `analyses/<DATE>_<story_key>.md`.

For each story, write **one** JSON file:

  `drafts/<DATE>_<story_key>_carousel.json`

conforming to `docs/api/schema/carousel.schema.json`. The frontend
renders slides programmatically from this JSON — your job is the
content, not the layout.

---

## Inputs

- `analyses/<DATE>_<story_key>.md` — synthesis input.
- `briefings/<DATE>_<story_key>.json` — corpus + source URLs.
- `briefings/<DATE>_<story_key>_metrics.json` — numbers.

---

## Procedure

1. Determine today's date (`date -u +%Y-%m-%d`).
2. List `analyses/<DATE>_*.md`. For each:
   a. Read the analysis.
   b. Pick the **central question** the deck will answer in one slide.
      Examples:
        "Who said the Hormuz deal was a US win? Who said Iran won?"
        "Which countries didn't cover the cruise-ship hantavirus outbreak?"
   c. Choose 5–8 frame slides — one bucket per slide — that answer the
      question by **showing** the disagreement, not telling it.
   d. Add a silence or paradox slide if the analysis surfaced one.
   e. Write the closing slide (one consequence sentence).
   f. Write the JSON file.
3. Print one summary line per file: story_key, n_slides, central_question,
   output_path.
4. **Commit and push your work** (uncommitted writes do not persist):

       git add drafts/
       git diff --cached --quiet && exit 0
       DATE=$(date -u +%Y-%m-%d)
       N=$(ls drafts/${DATE}_*_carousel.json 2>/dev/null | wc -l | tr -d ' ')
       git commit -m "drafts ${DATE} carousels (${N})"
       git push origin HEAD

   On push failure: `git pull --rebase origin HEAD` and retry once.

---

## Required structure

A carousel has, in order:

1. **Front slide** (`title` + `subtitle`).
   - `title`: the central question, ≤ 60 chars.
   - `subtitle`: dataset framing, ≤ 100 chars
     (e.g. "27 outlets across 6 continents. 2026-05-06.").

2. **Frame slides** (5–8, in `slides[]`, `kind: "frame"` or `"quote"`).
   - One bucket per slide.
   - `title`: outlet name (human-readable, e.g. "Foreign Affairs (US)").
   - `body`: a verbatim quote from that bucket, ≤ 200 chars.
   - `source`: `{bucket, url, outlet}` — required.

3. **One silence slide** (if analysis lists silences, `kind: "silence"`).
   - `title`: "What nobody covered" or similar.
   - `body`: name 2–3 buckets and what they ran instead.
   - No `source` field (silence is the absence of a source).

4. **One paradox slide** (if analysis identified a paradox, `kind: "paradox"`).
   - `title`: "Strange agreement: X and Y" or similar.
   - `body`: one short sentence on the joint conclusion + both attributions.
   - `source` array would have two entries — but the schema's `source`
     is a single object, so emit two slides if you want both quotes
     visible (one per side of the paradox), kind="paradox" on both.

5. **Closing slide** (`closing` field, not in `slides[]`).
   - One sentence on the consequence or stakes.
   - No source.

Total slides (front + body + closing): 7–11.

---

## Source attribution

Every `kind: "frame"` or `"quote"` slide MUST have a `source` object
with `{bucket, url}` where the `url` is an article `link` from the
briefing (not a homepage). `outlet` is recommended for display.

`silence`, `callout`, and `closing` slides may omit `source`.

---

## Style rules

- **Verbatim quotes only** in `body` for frame/quote slides. No
  paraphrase, no recombination.
- **Quotes ≤ 200 chars.** If the source quote is longer, end with `…`
  inside the quote marks. Pick a snippet that stands alone.
- **One claim per slide.** Don't pack two findings into one slide.
- **Bucket diversity.** Cover at least 4 distinct geographic/ideological
  blocs in the frame slides. Don't run 6 Western outlets.
- **No emoji.** No hashtag spam.
- **Numbers from metrics.json only** — same rule as the analyze prompt.

---

## Required JSON fields

```json
{
  "story_key": "<from briefing filename>",
  "date": "<YYYY-MM-DD>",
  "title": "<front-slide question>",
  "subtitle": "<front-slide dek>",
  "slides": [
    {
      "title": "<outlet name>",
      "body": "<verbatim quote>",
      "kind": "frame",
      "source": {"bucket": "<key>", "url": "<link>", "outlet": "<name>"}
    }
  ],
  "closing": "<one consequence sentence>",
  "generated_at": "<ISO 8601 UTC>",
  "model": "claude-opus-4-7"
}
```

---

## Skip rules

Skip (write nothing, note in summary) if:
- The analysis file doesn't exist.
- `n_buckets < 5` in the metrics file.
- You can't find at least 4 distinct buckets with usable verbatim quotes.
