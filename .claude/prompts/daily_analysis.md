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
  Quote verbatim from `signal_text` in its source language.
- `briefings/<DATE>_<story_key>_metrics.json` — precomputed numbers.
  Primary similarity (meta-v7.0.0): `pairwise_similarity` and `isolation`
  with `mean_similarity` per bucket — both are LaBSE bucket-mean cosine
  on original signal_text (multilingual; no translation pivot). Plus
  `bucket_exclusive_vocab` (operates on raw originals — flag in the
  bucket's `note` if the distinctive terms look like language artefacts
  rather than story-specific vocabulary), `n_buckets`, `n_articles`,
  `buckets_excluded_quant`. **Use these numbers verbatim. Never invent
  counts or scores.**
- `frames_codebook.json` — closed taxonomy of 15 valid `frame_id` values
  (Boydstun/Card). **Every frame you emit must use one of these IDs.**
- `docs/api/schema/analysis.schema.json` — required output shape.

---

## Procedure

1. `date -u +%Y-%m-%d` to get today's date.
2. `ls briefings/<DATE>_*.json` (excluding `_metrics.json` files) to find today's stories.
3. For each briefing where `n_buckets >= 3`:
   a. Read the briefing and matching `_metrics.json`.
   b. Read every `signal_text` in `corpus[]`. Note the index of each — you cite by index.
   c. Read `frames_codebook.json` and identify **2–8 frames** carried by the corpus.
      Each frame entry is:
        - `frame_id` — REQUIRED. One of the 15 codebook IDs (e.g.
          `SECURITY_DEFENSE`, `ECONOMIC`, `MORALITY`). This is what
          longitudinal aggregation tracks; do not invent IDs.
        - `sub_frame` — OPTIONAL. Story-specific human-readable label
          (e.g. `"energy contagion"`, `"sovereign reputation"`). This is
          where story-specific color goes — NOT in `frame_id`.
        - `buckets` — list of bucket keys carrying the frame.
        - `evidence` — at least one verbatim quote per frame, citing
          `corpus[i].signal_text` by `signal_text_idx`.
      Use `OTHER` only when no codebook frame applies, and pair it with
      a non-empty `sub_frame` explaining the framing.
   d. Look for a paradox: opposing-bloc buckets converging on the same conclusion.
      Quote both verbatim with their `signal_text_idx`. If no genuine paradox, set `"paradox": null`.
   e. List silences: buckets that plausibly should cover this and didn't (or covered
      something else). Cross-reference today's snapshot if needed.

      **Distinguish structural silence from editorial silence.** The
      briefing's top-level `coverage_caveats[]` lists buckets that had
      zero items today because every feed in them failed (403,
      timeout, empty response). Do **NOT** include those buckets in
      `silences[]` — their absence is structural, not editorial; a
      reader who treats it as "Lebanon stayed quiet" mistakes feed
      health for press behaviour. Instead, copy `briefing.coverage_caveats`
      verbatim into your output's top-level `coverage_caveats[]` array
      (same shape: one object per bucket with `bucket`, `alert_type`,
      `avg7`, `reason`). `silences[]` is reserved for buckets that DID
      carry items today but chose a different angle.
   f. Pick up to 10 single-outlet findings worth surfacing.
   g. Write a 1-2 sentence factual `event_summary` describing what
      concretely happened — places, people, decisions, dates. This
      is the anchor for readers not already across the story. NO
      framing language ("frames as", "casts as", "narrative"), NO
      editorial voice, NO cross-outlet comparison. If you reach
      for the word "frames", delete it and try again. Then write
      `tldr` (3–6 sentences) which extends into the framing
      observation.
   h. Assemble the JSON conforming to the schema.
   i. Validate the file with the project's full validator (schema +
      citation grounding + number reconciliation):
      `python -m analytical.validate_analysis analyses/<DATE>_<story>.json`
   j. If it reports any errors, fix them in your JSON and re-run the
      validator until it prints `OK`. The same validator runs in the
      workflow post-commit; if you skip this step and any error is
      caught downstream, the workflow fails and your work has to be
      manually reverted.
4. Skip stories with `n_buckets < 3`. Note in your final summary.
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
- **Frames use the closed codebook.** `frame_id` MUST be one of the 15
  IDs in `frames_codebook.json`. The codebook is what makes longitudinal
  comparison ("Italy's framing of Iran shifted from SECURITY_DEFENSE to
  ECONOMIC over 30 days") defensible. Story-specific color belongs in
  the optional `sub_frame` field, not in `frame_id`.
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
  "event_summary": "What concretely happened. 1-2 sentences. Factual only — no framing language, no editorial voice, no cross-outlet comparison.",
  "tldr": "Lead with the most surprising finding (3-6 sentences).",
  "frames": [
    {
      "frame_id": "ECONOMIC",
      "sub_frame": "energy-price contagion",
      "buckets": ["philippines", "south_korea", "japan"],
      "evidence": [
        {"bucket": "philippines", "outlet": "Asia Times",
         "quote": "verbatim text from corpus[12].signal_text",
         "signal_text_idx": 12}
      ]
    }
  ],
  "isolation_top": [
    {"bucket": "italy", "mean_similarity": 0.74,
     "note": "Aligned semantically with the corpus mean."}
  ],
  "exclusive_vocab_highlights": [
    {"bucket": "italy", "terms": ["guerra", "accordo", "uniti"],
     "what_it_reveals": "war framing; Italian press treats this as conflict-not-deal."}
  ],
  "paradox": null,
  "silences": [
    {"bucket": "egypt", "what_they_covered_instead": "Sisi's domestic emergency."}
  ],
  "coverage_caveats": [
    {"bucket": "lebanon", "alert_type": "structural_silence", "avg7": 3.4,
     "reason": "bucket carried 0 items today (7-day avg 3.4); feeds 403'd."}
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
