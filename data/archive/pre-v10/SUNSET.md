# Pre-v10 data archive

This directory contains a frozen snapshot of every data artefact produced
by the v8.x → v9.x architecture before the v10.0.0 rebuild. **None of this
data is comparable with v10 output** — the architecture changed structurally.

Archived: 2026-05-20 against branch `claude/v10-rebuild` off main `d1214a1`.

## What's in here

| File | Source | What it was |
|---|---|---|
| `briefings.tar.gz` | `briefings/` | 1.4 MB — per-story corpora, keyed by canonical story_key (`hormuz_iran`, `iran_nuclear`, etc.) |
| `analyses.tar.gz` | `analyses/` | 296 KB — Claude-written framing analyses, JSON + Markdown |
| `trajectory.tar.gz` | `trajectory/` | 8 KB — frame-share trajectories per canonical story over time |
| `sources.tar.gz` | `sources/` | 24 KB — per-quote speaker attribution, keyed by story_key |
| `calibration.tar.gz` | `calibration/` | 4.4 MB — 343-row Opus silver-labelled eval set, three-way model benchmark, perception_eval_report.md |
| `canonical_stories.json` | repo root | The 15 pre-defined canonical stories with embedding anchors + assignment floors |
| `bucket_weights.json` | repo root | Population × audience-reach weighting per country/region bucket |
| `bucket_quality.json` | repo root | Per-bucket coverage tier (A/B/C grade) + EXCLUDE_QUANT flag for stub-only aggregators |

## Why this is frozen, not deleted

Some of this data could be useful as ground truth for retrospective
comparisons (e.g. "how would the v10 dynamic clusterer have grouped articles
on 2026-05-12?"). The calibration eval set in particular is hand-labelled
work that could anchor v10 evaluations if we ever build a similar test
harness.

## Why none of it is comparable with v10

- **Story keys are gone.** v10 uses `lineage_id` (a stable hash from the
  cluster's seed date + seed cluster ID) instead of human-named keys like
  `hormuz_iran`. No 1:1 mapping exists.
- **Buckets are gone.** v9 aggregated 235 outlets into 55 buckets and
  computed bucket-mean cosine similarity. v10 operates at the outlet level;
  buckets become optional consumer-side tags (country / language / lean).
- **Frame analyses come from different inputs.** v9 analyses were written
  against canonical-story briefings (closed-world matched articles). v10
  analyses are written against dynamic-clustering briefings (open-world
  HDBSCAN over all articles). Same Claude, same codebook, different
  upstream input → different output distribution.
- **The perception layer (regex → softmax-argmax) that the calibration
  eval set measured no longer exists.** Calibration measured "how well does
  softmax-argmax assign articles to one of 15 pre-defined stories?" v10 has
  no such matcher. The eval set could be repurposed as a "given today's
  clusters, are the right articles grouped together?" test but that's a
  different question with different labels.

## Restore (if needed)

```bash
cd /home/user/epistemic-lens
tar -xzf data/archive/pre-v10/briefings.tar.gz
# (etc for the other tarballs)
```

This restores files to their original paths under the repo root, which is
where v9 code expects them. Won't work against v10 code paths.

## Audit trail

Last v9 commit on main before v10 rebuild started: `d1214a1` ("docs: refresh
README + docs/ for meta-v9.x (#42)"). meta_version.json at that commit was
9.2.2. Methodology pin for v10 starts fresh — no longitudinal continuity
across this boundary, per the v10 plan.
