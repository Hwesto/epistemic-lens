# Draft Thread — Claude Code prompt

You generate **chained-post drafts** (X / Twitter / Bluesky / Threads) from
today's framing analyses. You run on cron once a day, after `analyze` has
written `analyses/<DATE>_<story_key>.md`.

For each story, write **one** JSON file:

  `drafts/<DATE>_<story_key>_thread.json`

conforming to `docs/api/schema/thread.schema.json`.

---

## Inputs

- `analyses/<DATE>_<story_key>.md` — the canonical analysis (synthesis input).
- `briefings/<DATE>_<story_key>.json` — the corpus (for verbatim quote
  retrieval and source URLs).
- `briefings/<DATE>_<story_key>_metrics.json` — precomputed numbers.

---

## Procedure

1. Run `date -u +%Y-%m-%d` to determine today's date.
2. List `analyses/<DATE>_*.md`. For each one:
   a. Read the analysis fully.
   b. Read the briefing — every tweet that quotes or cites must use a
      verbatim string from a `signal_text` and the article's `link`.
   c. Pick the single most striking finding to lead with. Strong picks:
      - A paradox (two opposing buckets with the same conclusion).
      - A silence (a bucket that "should" have covered it and didn't).
      - A bucket-exclusive frame nobody else used.
      - A high-isolation bucket whose framing is genuinely distinct.
      Avoid: generic "here's how the world covered X" leads.
   d. Build the thread (see structure below).
   e. Write the JSON file.
3. After all files are written, print one summary line per file:
   story_key, n_tweets, lead_angle, output_path.
4. **Commit and push your work** (uncommitted writes do not persist):

       git add drafts/
       git diff --cached --quiet && exit 0
       DATE=$(date -u +%Y-%m-%d)
       N=$(ls drafts/${DATE}_*_thread.json 2>/dev/null | wc -l | tr -d ' ')
       git commit -m "drafts ${DATE} threads (${N})"
       git push origin HEAD

   Commit as `claude[bot]` (already configured by the action). If push
   fails with non-fast-forward, `git pull --rebase origin HEAD` and retry.

---

## Required structure

Every thread has **one hook + 5–8 body tweets + optional closing CTA**.

### Hook (one tweet, ≤ 240 chars)

A specific, falsifiable, surprising claim — *not* a topic announcement.

  Bad:  "Here's how the world covered the Hormuz deal."
  Good: "Foreign Affairs and RT — opposite political universes — both
        called the Hormuz deal an Iranian win. Nobody else did."

### Body (5–8 tweets, ≤ 280 chars each)

Each tweet pushes **one** point. Order to consider:

1. State the structural finding (e.g. "13 buckets ran the same wire line.").
2. Name the deviation (e.g. "But three told a different story.").
3. Quote one bucket verbatim. Attribute by outlet name in the tweet.
4. Quote the second bucket verbatim. Attribute.
5. (If paradox) name the paradox explicitly. Both names + the joint
   conclusion.
6. (If silence) name the silence. Which buckets carried *what* instead.
7. The "why it matters" tweet — one consequence, not a sermon.

### Closing CTA (optional, one tweet)

A pointer ("Full breakdown: …") or a question to the reader. Skip if
nothing useful to add.

---

## Source attribution

Every tweet that quotes or cites must include a `sources` array with at
least one `{bucket, url, outlet?}`. The `bucket` value MUST match a
bucket key in the briefing. The `url` MUST be an article `link` from
the briefing — not a homepage URL, not a search result.

Tweets that are pure synthesis (e.g. "13 of 27 buckets ran the same
wire line") may omit `sources` if the underlying numbers come straight
from `metrics.json`.

---

## Hard rules

- **Verbatim quotes only.** Anything in quotes in any tweet must be
  copy-pasted from a `signal_text`. No paraphrase, no recombination.
- **Numbers from metrics.json only.** Never invent a count, isolation
  score, or Jaccard value.
- **No fabricated paradoxes.** If the analysis says "(none in this
  corpus)", do not invent one for the thread.
- **One JSON file per story.** Path: `drafts/<DATE>_<story_key>_thread.json`.
- **Conform to the schema.** `docs/api/schema/thread.schema.json` is
  authoritative.
- **No emoji.** Unless the user has explicitly enabled them in this
  prompt (they have not).
- **No hashtag spam.** At most one hashtag in the closing CTA, only if
  it's a genuine community tag.
- **Don't address the reader as "you" in every tweet.** Vary.

---

## Required JSON fields

```json
{
  "story_key": "<from briefing filename>",
  "date": "<YYYY-MM-DD>",
  "hook": "<string>",
  "tweets": [
    {"text": "<string>", "sources": [{"bucket": "<key>", "url": "<article link>", "outlet": "<name>"}]}
  ],
  "closing_cta": "<string or omit>",
  "generated_at": "<ISO 8601 UTC>",
  "model": "claude-opus-4-7"
}
```

Set `generated_at` from the current UTC time. Set `model` to
`claude-opus-4-7`.

---

## Skip rules

Skip a story (write nothing, note in summary) if:
- The analysis file does not exist for today.
- The briefing has `n_buckets < 5` (not enough comparison signal).
- The analysis explicitly notes "(none in this corpus)" for both
  paradox AND silence AND no bucket-exclusive frames worth pulling.
  In practice this is rare; usually at least one angle is shippable.
