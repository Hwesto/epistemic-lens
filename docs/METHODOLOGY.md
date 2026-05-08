# Methodology pin policy

## Why this exists

Epistemic Lens makes longitudinal claims: "Italy uniquely uses *guerra*
for this story," "Hormuz had 14 buckets day 1, 6 by day 7," "Saudi
outlets cover Egypt's response, not Iran's." These claims are
defensible only if the **way** we computed them is stable across days.
Change the tokenizer mid-week and "Italy uniquely uses *guerra*"
becomes a measurement artifact, not a finding.

The methodology pin makes drift impossible-by-accident: every input
that affects analytical output is hashed in `meta_version.json`, every
artifact is stamped with `meta_version`, and CI fails any PR where the
declared hashes no longer match the live files.

## What is pinned

`meta_version.json` declares hashes for:

| File | Hash key | Why it matters |
|---|---|---|
| `feeds.json` | `feeds.hash` | Adding/removing feeds changes bucket vocabularies and which stories are detected. |
| `stopwords.txt` | `tokenizer.stopwords_hash` | Words that survive filtering are the entire signal in bucket-exclusive vocab metrics. |
| `canonical_stories.json` | `canonical_stories_hash` | Patterns that decide which articles cluster into a "story." |
| `.claude/prompts/*.md` | `claude.prompts_hash` | LLM analyses are downstream of these prompts word-for-word. |

It also declares (without hashing) the structural constants:

- **Embedding model** — `paraphrase-multilingual-MiniLM-L12-v2`
- **Clustering** — DBSCAN over cosine distance, eps=0.35, min_samples=3
- **Tokenizer** — regex `[A-Za-z]{4,}`, plural normalization
  `("ies", "es", "s")`. Operates on the English-pivot field
  `signal_text_en` (see Translation pivot below); falls back to
  `signal_text` for entries that didn't translate.
- **Translation pivot** — `claude-sonnet-4-6` translates every
  non-English `signal_text` to English before metrics are computed.
  Originals are preserved verbatim for citation grounding. Cache:
  `cache/translations/<sha256[:2]>/<sha256>.json`, keyed on
  `(model, source_lang, source_text)`. Bumping the translation model
  invalidates the cache deterministically.
- **Metrics** — Jaccard over bucket token sets; bucket-exclusive vocab
  = doc_freq <= 1 AND count >= 3
- **Signal text fallback** — body if ≥500 chars, summary if ≥60 chars,
  title otherwise; max 2500 chars
- **Extraction** — top 20 clusters + 3 per feed, 4000 char body cap,
  15s timeout, Wayback fallback
- **Claude model** — `claude-sonnet-4-6` (analysis + translation)

## How to change something

Choose the level of bump that matches the impact, run `baseline_pin.py
--bump <level>`, commit, tag.

### Patch (1.0.0 → 1.0.1)

For changes that **don't affect output**: refactors, comments, logging,
renamed variables, doc fixes.

```bash
python baseline_pin.py --bump patch
git add meta_version.json
git commit -m "meta: bump to 1.0.1 — refactor"
```

No tag needed; patch bumps don't affect longitudinal data.

### Minor (1.0.0 → 1.1.0)

For **forward-compatible** changes: a new canonical story, an added
feed, a new metric appended to the metrics output, an added stopword.
Existing artifacts remain valid; new artifacts contain more.

```bash
python baseline_pin.py --bump minor --reason "added 'gaza_ceasefire' canonical story"
git add meta_version.json canonical_stories.json
git commit -m "meta: bump to 1.1.0 — added gaza_ceasefire story"
git tag meta-v1.1.0
git push --follow-tags
```

### Major (1.0.0 → 2.0.0)

For **longitudinal-breaking** changes: switching the embedding model,
changing the Jaccard formula, removing buckets, rewriting prompts,
removing stopwords, lowering `min_body_chars_for_body`. After a major
bump, claims that span pre- and post-bump data must explicitly say so.

```bash
python baseline_pin.py --bump major --reason "switched to BGE multilingual embedding"
git add meta_version.json
git commit -m "meta: bump to 2.0.0 — embedding model change"
git tag meta-v2.0.0
git push --follow-tags
```

The repo tag (`meta-v2.0.0`) lets anyone re-run analyses under the
old config later.

## How CI enforces it

`baseline_pin.py --check` is a required status check on every push to
`main` and every PR. It re-hashes the live files and compares to
`meta_version.json`. If they drift, the check fails with a message
telling you which file changed and which level of bump fits.

The `validate-meta` job runs in ~10 seconds with no Python deps beyond
the standard library. It cannot be silently bypassed: the branch
ruleset for `main` makes it required.

## How artifacts are tagged

Every artifact (snapshot, briefing, metrics, analysis, draft,
api/index, api/latest) carries `"meta_version": "1.0.0"` at its top
level. This is added by `meta.stamp()` at write time. Downstream
consumers (the longitudinal aggregator, the static-card renderer,
external API readers) can branch on it:

```python
art = json.load(open("briefings/2026-05-06_hormuz_iran.json"))
if art["meta_version"].split(".")[0] != "1":
    raise ValueError("incompatible meta version")
```

## Where to read the live values

```python
import meta
print(meta.VERSION)               # "1.0.0"
print(meta.EMBEDDING["model"])    # "paraphrase-multilingual-MiniLM-L12-v2"
print(meta.fingerprint())         # one-line summary for logs
meta.assert_pinned()              # raises if drift
```

`python -m meta` prints the fingerprint and exits 0 if the pin is
consistent — useful as a sanity check after pulling.

## Day-zero state

The repo was first pinned on **2026-05-07** at `meta_version 1.0.0`,
covering 235 feeds across 54 buckets, 5 canonical stories, and the
four `.claude/prompts/*.md` files used by the daily LLM jobs. This is
the baseline against which all longitudinal claims are made.

## Translation pivot (added at 3.0.0)

Versions <= 2.x computed bucket vocabularies directly on
`title + signal_text` in the source language. The tokenizer regex
`[A-Za-z]{4,}` produced zero tokens for non-Latin scripts (Cyrillic,
Han, Kana, Hangul, Arabic, Devanagari, Hebrew, Greek, Thai), so any
cross-bucket Jaccard or "bucket-exclusive vocab" finding involving
those buckets was confounded with language identification rather than
framing.

**3.0.0 fixes this** by routing every non-English `signal_text`
through `analytical/translate.py` before `analytical/build_metrics.py`
runs. The pipeline is now:

```
ingest → extract_full_text → dedup → daily_health
       → build_briefing
       → translate           (NEW: signal_text_en + title_en per article)
       → build_metrics       (reads English-pivot via meta.effective_text)
       → analyze (Claude)    (still cites originals verbatim)
```

The translation step is **idempotent** and **content-hash cached**.
Citation grounding in `analytical/validate_analysis.py` continues to
operate on `corpus[i].signal_text` (originals) — the LLM analysis
quotes source-language text verbatim, so quote integrity is unchanged.
Only the metric layer reads `signal_text_en`. Pre-3.0.0 briefings
without `signal_text_en` fall through to the original via
`meta.effective_text()`; metrics keep computing, just confounded by
language for those entries (which is correctly attributed in the
artifact's `meta_version`).

Longitudinal claims that span the 2.x → 3.0.0 boundary must explicitly
acknowledge it. Most pre-3.0.0 cross-lingual vocabulary findings should
be treated as confounded; replay against 3.0.0 to recover them.

## What's NOT pinned

- **Article body content** — the open web changes; we extract what we
  can and accept that.
- **Cluster IDs** — DBSCAN labels are run-dependent. Don't reference
  them across days.
- **Wire-service representative titles** — the choice of "rep" article
  per cluster is order-dependent. Use the cluster's `articles[]`
  list, not just the rep.
- **Render output** — videos, cards, and rendered HTML are downstream
  artifacts that can be regenerated from the pinned data + code.

## When to bump versus when to leave alone

A useful test: **could a reasonable reader, looking at two artifacts
under the same `meta_version`, expect them to be analytically
comparable?** If yes, no bump needed. If "comparable" requires
caveats, bump.

Adding an English stopword that should have been there from day one
is a minor bump. Removing one is a major bump (terms that used to be
filtered out will now appear in vocab counts). Adding a French
stopword set is a major bump (changes which French articles' tokens
survive). Adding a story to `canonical_stories.json` is a minor bump
(it just makes a new briefing detectable; existing briefings are
unchanged).

When in doubt, bump higher. A spurious major bump is cheap; a missed
one corrupts longitudinal credibility.
