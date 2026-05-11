# Source / Quote Attribution — JSON output

You are running the **source-attribution pass** for the Epistemic Lens
dataset. You run on cron once a day, after the body framing analysis.

Your job: for each article in today's briefings, identify every direct
quote and the **person speaking it**, with their role, the attributive
verb the article uses, and the speaker's stance toward the story's
target. The output makes "who gets to speak" measurable per outlet, per
region, over time.

Your output is **one JSON file per story** at
`sources/<DATE>_<story_key>.json`. The schema is described below.

---

## Inputs

For each story:

- `briefings/<DATE>_<story_key>.json` — corpus. Each `corpus[i]` entry
  has `bucket`, `feed`, `lang`, `title`, `link`, `signal_text`. **The
  index `i` is the `signal_text_idx` you cite in evidence.**
- `analyses/<DATE>_<story_key>.json` — the body analysis. Read for the
  story_title and the canonical bucket list; you don't need to alter it.

---

## What to extract

For each article (`corpus[i]`), find every direct quote attributed to a
named or roled speaker. **Direct quotes only** — sentences set off with
quotation marks (or the language equivalent) and attributed to a speaker.
Skip:

- Reported speech without quotation marks ("X said the deal would
  collapse" — too soft).
- Editorial paraphrase without a named source ("analysts believe…").
- Generic crowd quotes ("a Tehran resident", "a Kremlin spokesperson")
  — record these but flag `speaker_name` as `null` and use the descriptor
  in `role_or_affiliation`.

For each quote, emit:

```json
{
  "speaker_name": "Donald Trump"  // or null for unnamed
  "role_or_affiliation": "US President" // or "Tehran resident" if unnamed
  "speaker_type": "official" | "civilian" | "expert" | "journalist" | "spokesperson" | "unknown",
  "exact_quote": "verbatim text from signal_text, including punctuation",
  "attributive_verb": "said" | "claimed" | "warned" | "told" | "argued" | "denied" | etc.,
  "stance_toward_target": "for" | "against" | "neutral" | "unclear",
  "signal_text_idx": <i>,
  "bucket": "<bucket_key>",
  "outlet": "<outlet name>"
}
```

Notes on each field:

- `speaker_name`: the proper name only; no titles. "Trump" not "President
  Trump". Use the form most consistent with how the article writes it on
  later mentions. Null when unnamed.
- `role_or_affiliation`: the institutional role at time of quotation.
  "US President" not "Republican". For civilians, the descriptor the
  article uses ("Khuzestan port worker", "Ushuaia tour operator").
- `speaker_type`: closed enum. **official** = government, military,
  or party officials; **civilian** = ordinary people; **expert** =
  named academics, think-tank fellows, journalists quoted as analysts;
  **journalist** = the reporter or another journalist quoted in their
  professional capacity; **spokesperson** = institutional press
  representatives; **unknown** when ambiguous.
- `exact_quote`: must appear **verbatim** in
  `corpus[signal_text_idx].signal_text`. The validator will reject
  hallucinated quotes.
- `attributive_verb`: the lemma form. The choice of "said" vs "claimed"
  vs "argued" vs "warned" is itself coverage data; record it precisely.
- `stance_toward_target`: the speaker's position relative to the story's
  central actor or proposition. For the Strait-of-Hormuz story, "target"
  = the US blockade. Trump speaking *for* the blockade. Iranian official
  speaking *against*. ASEAN official speaking *neutral* (third-party
  affected). Often `unclear` is the honest call.

---

## Output schema

```json
{
  "story_key": "...",
  "date": "YYYY-MM-DD",
  "story_title": "...",
  "n_articles_processed": <int>,
  "sources": [
    { ... per-quote object as above ... },
    ...
  ],
  "model": "claude-haiku-4-5",
  "meta_version": "..."
}
```

---

## Constraints

- Quote-grounding: every `exact_quote` MUST be a substring of the article
  it's attributed to. Run the same self-check the body analyzer does:
  `corpus[signal_text_idx].signal_text` should contain `exact_quote`.
- Cross-language: extract quotes in the article's source language. Don't
  translate. The validator works on the original language.
- Empty stories: if an article carries no direct quotes (rare in news but
  common in stub-style aggregators), skip it. Don't invent quotes.
- Rate-limit: each story has typically 5–20 articles. Process them one
  story at a time; if you start hitting rate limits, stop and commit
  what you have. The cron will re-run tomorrow.

---

## When you're done

1. Write `sources/<DATE>_<story_key>.json` for each story.
2. Validate locally: every `exact_quote` is verbatim in its corpus entry.
3. Stage + commit + push:
   ```
   git add sources/
   git commit -m "source attribution <DATE> (<n> sources extracted)"
   git push
   ```

The post-pass `analytical.validate_analysis` step will re-verify quote
grounding (defence in depth). The post-pass
`analytical.source_aggregation` step builds the per-outlet aggregate and
publishes it to `sources/aggregate/<DATE>.json`.
