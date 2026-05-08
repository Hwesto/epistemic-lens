# Draft Long-Form Post — Claude Code prompt

You generate **long-form post drafts** (LinkedIn, Substack, newsletter)
from today's framing analyses. You run on cron once a day, after
`analyze` has written `analyses/<DATE>_<story_key>.json`.

This is the only LLM-generated draft format — thread and carousel are
deterministic Python templates over the same analysis JSON. Your job
is the prose-grade synthesis that templates can't do.

For each story, write **one** JSON file:

  `drafts/<DATE>_<story_key>_long.json`

conforming to `docs/api/schema/long.schema.json`. The post body is
markdown inside a JSON envelope so the frontend can parse metadata
uniformly across formats.

---

## Inputs

- `analyses/<DATE>_<story_key>.json` — canonical structured analysis.
  Read its `tldr`, `frames`, `paradox`, `silences`, `single_outlet_findings`,
  `isolation_top` directly as fields. Each `frames[].evidence[].signal_text_idx`
  references the corpus by index.
- `briefings/<DATE>_<story_key>.json` — corpus. `corpus[i]` provides
  the full body, link, outlet, and bucket for citation lookup.
- `briefings/<DATE>_<story_key>_metrics.json` — numbers (use verbatim).

---

## Procedure

1. Determine today's date (`date -u +%Y-%m-%d`).
2. List `analyses/<DATE>_*.json`. For each:
   a. Read the analysis JSON fully. Its `tldr` is your spine;
      `frames[]` give you the structural points; `paradox`/`silences`
      give you the lede options.
   b. Pick the lede angle: the single most arresting finding the
      analysis surfaced. Selection priority: paradox (non-null) >
      strongest silence > bucket-exclusive vocab from
      `exclusive_vocab_highlights` > top-1 isolation outlier.
   c. Write 600–900 words of clean prose. Inline-cite sources as
      `[outlet name](article link)` using only links from the briefing.
   d. Build the `sources[]` array: every link cited in `body_md` must
      appear once in `sources[]` with its `bucket` and `url`.
   e. Write the JSON file.
3. Print one summary line per file: story_key, word_count, lede_angle,
   output_path.
4. **Commit and push your work** (uncommitted writes do not persist):

       git add drafts/
       git diff --cached --quiet && exit 0
       DATE=$(date -u +%Y-%m-%d)
       N=$(ls drafts/${DATE}_*_long.json 2>/dev/null | wc -l | tr -d ' ')
       git commit -m "drafts ${DATE} long-form (${N})"
       git push origin HEAD

   On push failure: `git pull --rebase origin HEAD` and retry once.

---

## Required structure (in body_md)

The post is markdown. Recommended structure (don't use literal section
headers; use them as a discipline):

1. **Lede** (1–2 paragraphs). Open with the single most arresting fact.
   Specific. Falsifiable. The reader should know in 60 words why this
   piece is worth their next four minutes.

2. **The shared frame** (1–2 paragraphs). What did most of the corpus
   agree on? Cite 1–2 wire-line outlets. Use Jaccard / convergence
   numbers from metrics.json verbatim if relevant.

3. **The deviations** (2–4 paragraphs). The arcs from the analysis —
   one paragraph per arc, each with at least one verbatim quote
   attributed to a bucket via `[outlet](link)`.

4. **The paradox or the silence** (1–2 paragraphs). Whichever is
   sharper in this corpus. If a paradox: name the two opposing buckets,
   quote both, interpret the joint conclusion. If a silence: name what
   the absent buckets ran instead, and what it implies.

5. **Stakes** (1 short paragraph). One consequence or open question.
   No sermon. No grand "this is what democracy means" closer.

---

## Voice

- Sober, observational, opinion-magazine register.
- First person plural ("we") only if defensible — usually drop it.
- No second person ("you") — addresses the reader without consent.
- No rhetorical questions in the body. One in the lede is OK.
- No "in a world where…" / "in an era of…" openers. Start with the fact.
- No bulleted lists in the body except where genuinely list-like
  (e.g. naming the 3 buckets carrying a frame).

---

## Source citation

- Every factual claim or quote cites inline as `[outlet name](link)`.
- The `link` must be an article URL from the briefing's `link` field —
  not a homepage, not a search result.
- The `sources[]` array must contain every cited link, deduplicated,
  with `{bucket, url, outlet?}`. This is what the frontend uses to
  render an appendix or hover-citations.

---

## Hard rules

- **Verbatim quotes only.** Markdown blockquotes (`> "…"`) and inline
  quoted strings must come straight from `signal_text`.
- **Numbers from metrics.json only.** Never invent counts or scores.
- **No fabrication.** If the analysis says "(none in this corpus)" for
  the paradox, don't invent one. Switch the lede to the silence or a
  bucket-exclusive frame instead.
- **One JSON file per story.** Path: `drafts/<DATE>_<story_key>_long.json`.
- **Schema compliance.** `docs/api/schema/long.schema.json` is authoritative.
- **600–900 words** in `body_md`. Shorter is OK if the corpus is thin;
  do not pad. Longer drifts into newsletter territory we don't want.

---

## Required JSON fields

```json
{
  "story_key": "<from briefing filename>",
  "date": "<YYYY-MM-DD>",
  "title": "<post title, <= 90 chars>",
  "subtitle": "<optional dek>",
  "body_md": "<markdown, 600-900 words, inline citations as [outlet](link)>",
  "sources": [
    {"bucket": "<key>", "url": "<article link>", "outlet": "<name>"}
  ],
  "tags": ["<optional free-text tags>"],
  "generated_at": "<ISO 8601 UTC>",
  "model": "claude-sonnet-4-6"
}
```

---

## Skip rules

Skip (write nothing, note in summary) if:
- The analysis JSON doesn't exist for today.
- `n_buckets < 5` in the analysis.
- The analysis has no paradox AND no silences AND no isolation_top
  entry below 0.05 (very wire-convergent corpus). Note
  "wire-converged, no long-form angle" in summary.
