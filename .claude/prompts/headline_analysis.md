# Headline Framing Analysis — JSON output

You are doing the **headline-only** framing analysis for the Epistemic Lens
dataset. You run on cron once a day, after the regular daily framing pass,
on the same set of stories.

Your output is **one JSON file per story** at
`analyses/<DATE>_<story_key>_headline.json`, conforming to the same schema
at `docs/api/schema/analysis.schema.json` as the regular pass. The output
is the headline-only counterpart to the body-text analysis; downstream the
two are compared by `analytical/headline_body_divergence.py` to compute a
per-outlet sensationalism index.

---

## Inputs

For each story:

- `briefings/<DATE>_<story_key>.json` — same corpus as the regular pass.
  **You read only `corpus[i].title` (and `corpus[i].bucket` /
  `corpus[i].feed` / `corpus[i].lang` for attribution). Ignore
  `signal_text`.** This is the whole point: produce a frame analysis from
  what a reader sees on the homepage / RSS feed before they click.
- `briefings/<DATE>_<story_key>_metrics.json` — same metrics. Reuse the
  same `n_buckets`, `n_articles`, similarity scores, vocab.
- `frames_codebook.json` — the closed 15-frame Boydstun/Card codebook.
  Same constraint: `frame_id` MUST be one of those 15.

---

## What's different vs. the body pass

The body pass reads ~2500 chars per article. The headline pass reads ~70
chars (one title). This means:

1. **Frames per story will be fewer** (1–4 typical, vs 2–8 for body). Don't
   force a frame if the headlines don't support it.
2. **Many headlines support no frame at all.** Those buckets simply don't
   appear in any frame's `buckets` list. Don't invent a frame to capture
   them; they go to `silences`.
3. **Sub-frame text must come from the headline.** No body quotes
   available. The `evidence[].quote` is a verbatim title fragment ≤ 60
   chars.
4. **Tone often diverges from body.** A body covering "ASEAN summit
   discusses energy crisis" may have a headline "Iran chokes Asia: ASEAN
   panic." The headline pass captures the *advertised* framing — exactly
   the divergence the divergence-index measures.

---

## Output schema

Same schema as regular pass:

```json
{
  "story_key": "...",
  "date": "YYYY-MM-DD",
  "n_buckets": <from metrics.json>,
  "n_articles": <from metrics.json>,
  "tldr": "1–2 sentences describing what the HEADLINES (not the bodies) collectively assert about this story.",
  "frames": [
    {
      "frame_id": "<one of the 15 codebook ids>",
      "sub_frame": "≤ 40 chars — what the headline framing emphasises",
      "buckets": ["bucket_a", "bucket_b"],
      "evidence": [
        {
          "bucket": "bucket_a",
          "outlet": "Outlet Name",
          "quote": "≤60 chars verbatim title",
          "signal_text_idx": <i>
        }
      ]
    }
  ],
  "isolation_top": [...],     // copy verbatim from metrics.json (same numbers)
  "exclusive_vocab_highlights": [],  // headlines have no vocab — leave empty
  "paradox": null,            // typically not detectable from titles alone
  "silences": [...],          // buckets whose titles fit no frame go here
  "single_outlet_findings": [],
  "bottom_line": "1 sentence: what does the *headline* layer of coverage say?",
  "model": "claude-sonnet-4-6",
  "meta_version": "..."       // restamp_analyses.py will fix this
}
```

Constraints (same as body pass):

- `frame_id` must be in `frames_codebook.json`. Closed set.
- `sub_frame` is a short tag (≤ 40 chars), not free-form prose.
- `evidence[].quote` is verbatim from `corpus[i].title`.
- `signal_text_idx` indexes the corpus exactly like the body pass.
- Numbers from `metrics.json` ONLY. Never invent.

---

## When you're done

Same flow:
1. Write `analyses/<DATE>_<story_key>_headline.json` for each story.
2. Validate locally with `python -c "import json; json.load(open(p))"` per file.
3. Stage + commit + push (the agent handles its own commit, same as the body pass).

The `restamp_analyses.py` step in the workflow will re-stamp `meta_version`
to the live pin. The validator (`validate_analysis.py`) will verify
`signal_text_idx` resolution and quote-grounding the same way as the body
pass — the headline JSON uses the same schema.
