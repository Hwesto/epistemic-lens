# Daily Framing Analysis — JSON output

You are doing the **daily cross-country framing analysis** for the Epistemic
Lens dataset. You run on cron once a day, after the ingest + briefing pipeline
has produced today's corpora.

Your output is **one JSON file per story** at
`analyses/<DATE>_<story_key>.json`, conforming to the schema at
`docs/api/schema/analysis.schema.json`. The JSON is the canonical product.
A separate `python -m publication.render_analysis_md` step in the workflow
renders human-readable markdown for PR review — you don't write markdown.

---

## Inputs

For each story you analyse:

- `briefings/<DATE>_<story_key>.json` — corpus. Each `corpus[i]` entry has
  `bucket`, `feed`, `lang`, `title`, `link`, `signal_level`, `signal_text`.
  **The index `i` is the `signal_text_idx` you cite in evidence.**
- `briefings/<DATE>_<story_key>_metrics.json` — precomputed numbers:
  `pairwise_jaccard`, `isolation`, `bucket_exclusive_vocab`, `n_buckets`,
  `n_articles`. **Use these numbers verbatim. Never invent counts or scores.**
- `docs/api/schema/analysis.schema.json` — required output shape.

---

## Procedure

1. `date -u +%Y-%m-%d` to get today's date.
2. `ls briefings/<DATE>_*.json` (excluding `_metrics.json` files) to find today's stories.
3. For each briefing where `n_buckets >= 5`:
   a. Read the briefing and matching `_metrics.json`.
   b. Read every `signal_text` in `corpus[]`. Note the index of each — you cite by index.
   c. Derive **2–8 frames** specific to this story by what the corpus actually contains.
      Each frame = a label + which buckets carry it + at least one verbatim quote.
   d. Look for a paradox: opposing-bloc buckets converging on the same conclusion.
      Quote both verbatim with their `signal_text_idx`. If no genuine paradox, set `"paradox": null`.
   e. List silences: buckets that plausibly should cover this and didn't (or covered
      something else). Cross-reference today's snapshot if needed.
   f. Pick up to 10 single-outlet findings worth surfacing.
   g. Assemble the JSON conforming to the schema.
   h. Validate the file with the project's full validator (schema +
      citation grounding + number reconciliation):
      `python -m analytical.validate_analysis analyses/<DATE>_<story>.json`
   i. If it reports any errors, fix them in your JSON and re-run the
      validator until it prints `OK`. The same validator runs in the
      workflow post-commit; if you skip this step and any error is
      caught downstream, the workflow fails and your work has to be
      manually reverted.
4. Skip stories with `n_buckets < 5`. Note in your final summary.
5. Print one summary line per story written: `<story_key> n_buckets=N paradox=yes|no n_frames=N`.
6. **Commit and push** (uncommitted writes do not persist):

       git add analyses/
       git diff --cached --quiet && exit 0
       DATE=$(date -u +%Y-%m-%d)
       N=$(ls analyses/${DATE}_*.json 2>/dev/null | wc -l | tr -d ' ')
       git commit -m "analyses ${DATE} (${N} stories)"
       git push origin HEAD

   On non-fast-forward push failure: `git pull --rebase origin HEAD && git push`.

---

## Hard rules

- **Verbatim quotes only.** Every `evidence.quote` and `paradox.{a,b}.quote`
  must be copy-pasted from a `corpus[i].signal_text`. The `signal_text_idx`
  field references the exact corpus position. The pre-commit citation linter
  (Phase 4) will reject mismatches.
- **Numbers from metrics only.** `n_buckets`, `n_articles`, isolation scores,
  exclusive-vocab terms — all from `metrics.json`. Never invent.
- **Frames are story-specific.** Re-derive every time. Do NOT reuse labels
  across stories or across days. (Once we accumulate a few weeks of data we
  may pin a taxonomy; for now, free-form per story.)
- **No paradox if none exists.** Set `"paradox": null`. Do not invent.
- **Schema-conformant or it doesn't ship.** Validate before commit; the
  workflow's render step depends on conforming JSON.
- **One JSON file per story.** Path: `analyses/<DATE>_<story_key>.json`.

---

## Minimal output skeleton

```json
{
  "meta_version": "<read from meta_version.json — do NOT copy from briefing>",
  "date": "YYYY-MM-DD",
  "story_key": "...",
  "story_title": "...",
  "n_buckets": 27,
  "n_articles": 41,
  "tldr": "Lead with the most surprising finding (3-6 sentences).",
  "frames": [
    {
      "label": "ECONOMIC_CONTAGION",
      "description": "Coverage focuses on price spillovers to the bucket's home economy.",
      "buckets": ["philippines", "south_korea", "japan"],
      "evidence": [
        {"bucket": "philippines", "outlet": "Asia Times",
         "quote": "verbatim text from corpus[12].signal_text",
         "signal_text_idx": 12}
      ]
    }
  ],
  "isolation_top": [
    {"bucket": "italy", "mean_jaccard": 0.009,
     "note": "Italian-language; isolation is linguistic, not editorial."}
  ],
  "exclusive_vocab_highlights": [
    {"bucket": "italy", "terms": ["guerra", "accordo", "uniti"],
     "what_it_reveals": "war framing; Italian press treats this as conflict-not-deal."}
  ],
  "paradox": null,
  "silences": [
    {"bucket": "egypt", "what_they_covered_instead": "Sisi's domestic emergency."}
  ],
  "single_outlet_findings": [
    {"outlet": "RT", "bucket": "russia",
     "finding": "Frames the deal as an Iranian win.", "signal_text_idx": 22}
  ],
  "bottom_line": "Two sentences restating the headline finding.",
  "generated_at": "2026-05-08T12:34:56Z",
  "model": "claude-haiku-4-5-20251001"
}
```

Keep it tight. The structure does the work, not padding.
