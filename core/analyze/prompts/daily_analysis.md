# Daily Framing Analysis — JSON output

You are doing the **daily cross-country framing analysis** for the Epistemic
Lens dataset. You run on cron once a day, after the ingest → embed →
cluster → briefing pipeline has produced today's per-cluster corpora.

Your output is **one JSON file per cluster** at
`data/analyses/<DATE>_<lineage_id>.json`, conforming to the schema at
`publish/api/schemas/analysis.schema.json`. The JSON is the canonical
product. A separate `python -m publish.render.analysis_md` step in the
workflow renders human-readable markdown for review — you don't write
markdown.

---

## Scoping (v10)

The cron's analyze step runs you ONE cluster at a time via a matrix —
each invocation receives a header like:

    # Assigned cluster: <lineage_id>

before this prompt. `<lineage_id>` is an opaque hash (e.g. `Le4f8a39c1d`)
that uniquely identifies a cluster lineage across days. When that header
is present, process ONLY that cluster. Do not enumerate or analyse any
other cluster. Your output is a single file:
`data/analyses/<DATE>_<lineage_id>.json`. Read the named briefing
directly:

    data/briefings/<DATE>_<lineage_id>.json

When no `# Assigned cluster:` header is present (local manual runs),
enumerate today's briefings via `ls data/briefings/<DATE>_*.json` and
process each one.

---

## What changed from v9

Previously the pipeline pre-defined 15 canonical stories (Ukraine war,
Iran nuclear, etc.) and assigned articles to them via embedding
softmax-argmax. As of v10 stories are **emergent**: HDBSCAN clusters all
articles each day, salience ranking picks the top ~15 clusters, and you
get one per matrix entry. There's no pre-set story name — **you assign
the name** as part of your output.

Practical differences when you read the briefing:
- The corpus is keyed by **outlet** (the feed name like "Wall Street Journal"),
  not by bucket. Each `corpus[i]` carries `outlet`, `country`,
  `country_label`, `lang`, `lean`, `section` as tags.
- The briefing has `top_tokens` (top 10 tokens across member article titles)
  and `salience_score` — both inputs to help you understand the cluster
  before you name it.
- The cluster has a `lineage_id` (which you put in your output) and a
  `cluster_id` (the day-local int, just for debugging).
- There's no `story_key`. **You write a `cluster_name`** (5-12 words,
  factual not editorial — see procedure step (c) below).

---

## Inputs

For each cluster you analyse:

- `data/briefings/<DATE>_<lineage_id>.json` — the corpus. Fields:
  - `corpus[i]` with `outlet`, `country`, `country_label`, `lang`, `lean`,
    `section`, `title`, `link`, `signal_level`, `signal_text`.
  - **The index `i` is the `signal_text_idx` you cite in evidence.**
    Quote verbatim from `signal_text` in its source language.
  - `n_outlets`, `n_countries`, `n_langs` — exact counts; use verbatim.
  - `top_tokens` — top 10 tokens across member titles. Hint for naming.
  - `salience_score` — the salience that selected this cluster for analysis.
  - `coverage_caveats` — countries with zero items today due to feed
    failures (see structural-silence note below).
- `core/config/frames_codebook.json` — closed taxonomy of 15 valid `frame_id`
  values (Boydstun/Card). **Every frame you emit must use one of these IDs.**
- `publish/api/schemas/analysis.schema.json` — required output shape.

---

## Procedure

1. `date -u +%Y-%m-%d` to get today's date.
2. Read the named briefing (or, in fallback enumeration mode, every
   `data/briefings/<DATE>_*.json` whose `n_outlets >= 3`).
3. For each briefing:
   a. Read every `signal_text` in `corpus[]`. Note the index of each —
      you cite by index.
   b. Read `core/config/frames_codebook.json` and identify **2–8 frames**
      carried by the corpus. Each frame entry:
        - `frame_id` — REQUIRED. One of the 15 codebook IDs (e.g.
          `SECURITY_DEFENSE`, `ECONOMIC`, `MORALITY`). Longitudinal
          aggregation tracks these IDs; do not invent IDs.
        - `sub_frame` — OPTIONAL. Cluster-specific human-readable label
          (e.g. `"energy contagion"`, `"sovereign reputation"`).
        - `outlets` — list of outlet names carrying the frame.
        - `countries` — list of country codes carrying the frame
          (derived from outlets but explicit for cross-country views).
        - `evidence` — at least one verbatim quote per frame, citing
          `corpus[i].signal_text` by `signal_text_idx`.
      Use `OTHER` only when no codebook frame applies, and pair it with
      a non-empty `sub_frame` explaining the framing.
   c. **Name the cluster.** Write a 5-12 word `cluster_name` (factual,
      not editorial — describe what concretely happened or what the
      coverage is about). Examples:
        - "Ukraine drone strike on Moscow oil refinery"
        - "US-Iran Hormuz Strait naval standoff continues"
        - "OpenAI lawsuit alleges training data theft"
        - "Lebanese-Israeli border ceasefire negotiations week 4"
      AVOID generic names like "Middle East tensions", "Tech regulation",
      "China relations". The name should pass a reader's sniff test:
      does it tell me what specifically happened? If your name has the
      word "tensions", "developments", "situation", or "relations" —
      delete it and try again.
   d. Look for a paradox: opposing-bloc outlets converging on the same
      conclusion. Quote both verbatim with their `signal_text_idx`. If
      no genuine paradox, set `"paradox": null`.
   e. List silences: countries that plausibly should cover this and
      didn't (or covered something else).

      **Distinguish structural silence from editorial silence.** The
      briefing's top-level `coverage_caveats[]` lists countries that had
      zero items today because every feed in them failed (403, timeout,
      empty response). Do **NOT** include those countries in `silences[]`
      — their absence is structural, not editorial; a reader who treats
      it as "Lebanon stayed quiet" mistakes feed health for press
      behaviour. Instead, copy `briefing.coverage_caveats` verbatim into
      your output's top-level `coverage_caveats[]` array. `silences[]`
      is reserved for countries that DID carry items today but chose a
      different angle.
   f. Pick up to 10 single-outlet findings worth surfacing.
   g. Write a 1-2 sentence factual `event_summary` describing what
      concretely happened — places, people, decisions, dates. This is
      the anchor for readers not already across the story. NO framing
      language ("frames as", "casts as", "narrative"), NO editorial
      voice, NO cross-outlet comparison. If you reach for the word
      "frames", delete it and try again. Then write `tldr` (3-6
      sentences) which extends into the framing observation.
   h. Assemble the JSON conforming to the schema.
   i. Validate the file:
      `python -m core.analyze.validate data/analyses/<DATE>_<lineage_id>.json`
   j. If it reports any errors, fix them in your JSON and re-run the
      validator until it prints `OK`.
4. Skip clusters with `n_outlets < 3`. Note in your final summary.
5. Print one summary line per cluster written:
   `<lineage_id> "<cluster_name>" n_outlets=N n_countries=N paradox=yes|no n_frames=N`.
6. **Commit and push** (uncommitted writes do not persist):

       git add data/analyses/
       git diff --cached --quiet && exit 0
       DATE=$(date -u +%Y-%m-%d)
       N=$(ls data/analyses/${DATE}_*.json 2>/dev/null | wc -l | tr -d ' ')
       git commit -m "analyses ${DATE} (${N} clusters)"
       git push origin HEAD

   On non-fast-forward push failure: `git pull --rebase origin HEAD && git push`.

---

## Hard rules

- **Verbatim quotes only.** Every `evidence.quote` and `paradox.{a,b}.quote`
  must be copy-pasted from a `corpus[i].signal_text`. The `signal_text_idx`
  field references the exact corpus position. The post-commit citation
  validator will reject mismatches.
- **Numbers from briefing only.** `n_outlets`, `n_countries`, `n_articles_total`
  — read from the briefing JSON. Never invent.
- **Frames use the closed codebook.** `frame_id` MUST be one of the 15
  IDs in `core/config/frames_codebook.json`. The codebook is what makes
  longitudinal comparison defensible. Cluster-specific color belongs in
  the optional `sub_frame` field, not in `frame_id`.
- **No paradox if none exists.** Set `"paradox": null`. Do not invent.
- **`cluster_name` is factual.** Past tense or "ongoing". No editorial
  framing words. If a reader asks "what is this cluster?" the name
  should answer it in one sentence.
- **One JSON file per cluster.** Path:
  `data/analyses/<DATE>_<lineage_id>.json`.

---

## Minimal output skeleton

```json
{
  "meta_version": "<read from core/config/meta_version.json — do NOT copy from briefing>",
  "date": "YYYY-MM-DD",
  "lineage_id": "Le4f8a39c1d",
  "cluster_id": 42,
  "cluster_name": "Ukraine drone strike on Moscow oil refinery",
  "n_outlets": 27,
  "n_countries": 18,
  "n_articles": 41,
  "salience_score": 12.4,
  "event_summary": "What concretely happened. 1-2 sentences. Factual only.",
  "tldr": "Lead with the most surprising finding (3-6 sentences).",
  "frames": [
    {
      "frame_id": "ECONOMIC",
      "sub_frame": "energy-price contagion",
      "outlets": ["Asia Times", "Korea Herald", "NHK"],
      "countries": ["philippines", "south_korea", "japan"],
      "evidence": [
        {"outlet": "Asia Times", "country": "philippines",
         "quote": "verbatim text from corpus[12].signal_text",
         "signal_text_idx": 12}
      ]
    }
  ],
  "outlet_isolation_top": [
    {"outlet": "ANSA", "country": "italy", "mean_similarity": 0.74,
     "note": "Aligned with the cluster mean despite Italian-language vocabulary."}
  ],
  "outlet_exclusive_vocab_highlights": [
    {"outlet": "ANSA", "country": "italy",
     "terms": ["guerra", "accordo", "uniti"],
     "what_it_reveals": "war framing; Italian press treats this as conflict-not-deal."}
  ],
  "paradox": null,
  "silences": [
    {"country": "egypt", "what_they_covered_instead": "Sisi's domestic emergency."}
  ],
  "single_outlet_findings": [
    {"outlet": "RT", "country": "russia",
     "finding": "Frames the strike as an Iranian win.", "signal_text_idx": 22}
  ],
  "coverage_caveats": [
    {"country": "lebanon", "alert_type": "100_percent_feed_failure",
     "n_failed_feeds": 3, "reason": "all 3 Lebanese feeds returned 403 today"}
  ],
  "bottom_line": "Two sentences restating the headline finding.",
  "generated_at": "2026-05-20T07:35:12Z",
  "model": "claude-sonnet-4-6"
}
```

Keep it tight. The structure does the work, not padding.
