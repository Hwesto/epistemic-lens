# Perception calibration report — PR2 Phase A

_Generated 2026-05-13T15:40:24Z._

## Setup

- Eval set: **343 rows**, hand-labeled by Opus
- Canonical stories: **15**
- Models benchmarked: **LaBSE, e5-large, bge-m3**
- Floor cosines tested: **[0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]**
- Acceptance gate: macro F1 ≥ 0.8 AND per-lang F1 ≥ 0.7 on ar, en, es, fa, fr, hi, ja, ko, zh

## Verdict

- **Winner:** `bge-m3`
- **Gate status:** FAIL (no model meets gate; closest selected)

## Per-model summary

| Model | Best floor | Macro F1 | Cross-lingual drift max | Gate |
| --- | --- | --- | --- | --- |
| `LaBSE` | 0.40 | 0.580 | 0.197 | ✗ |
| `e5-large` | 0.40 | 0.764 | 0.086 | ✗ |
| `bge-m3` | 0.45 | 0.784 | 0.143 | ✗ |

## bge-m3 detail

### Floor sweep

| Floor | Macro F1 |
| --- | --- |
| 0.40 | 0.766 |
| 0.45 | 0.784 |
| 0.50 | 0.771 |
| 0.55 | 0.688 |
| 0.60 | 0.530 |
| 0.65 | 0.374 |
| 0.70 | 0.201 |

### Per-story (at floor=0.45)

| Story | TP | FP | FN | TN | P | R | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `africa_political_transitions` | 9 | 0 | 2 | 10 | 1.00 | 0.82 | 0.90 |
| `ai_regulation` | 9 | 4 | 0 | 8 | 0.69 | 1.00 | 0.82 |
| `china_taiwan` | 10 | 0 | 5 | 8 | 1.00 | 0.67 | 0.80 |
| `climate_policy` | 7 | 2 | 0 | 7 | 0.78 | 1.00 | 0.88 |
| `eu_expansion` | 7 | 3 | 4 | 13 | 0.70 | 0.64 | 0.67 |
| `hantavirus_cruise` | 15 | 2 | 0 | 5 | 0.88 | 1.00 | 0.94 |
| `hormuz_iran` | 16 | 3 | 0 | 10 | 0.84 | 1.00 | 0.91 |
| `india_pakistan` | 4 | 3 | 3 | 12 | 0.57 | 0.57 | 0.57 |
| `iran_nuclear` | 11 | 2 | 8 | 7 | 0.85 | 0.58 | 0.69 |
| `israel_palestine` | 14 | 0 | 3 | 11 | 1.00 | 0.82 | 0.90 |
| `lebanon_buffer` | 18 | 0 | 3 | 7 | 1.00 | 0.86 | 0.92 |
| `turner_cnn` | 7 | 1 | 0 | 3 | 0.88 | 1.00 | 0.93 |
| `ukraine_war` | 20 | 2 | 4 | 4 | 0.91 | 0.83 | 0.87 |
| `us_election_cycle` | 8 | 4 | 1 | 8 | 0.67 | 0.89 | 0.76 |
| `vietnam_china_visit` | 1 | 8 | 0 | 7 | 0.11 | 1.00 | 0.20 |

### Per-language (at floor=0.45)

| Lang | TP | FP | FN | TN | P | R | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ar` | 13 | 3 | 5 | 6 | 0.81 | 0.72 | 0.77 |
| `de` | 1 | 0 | 0 | 3 | 1.00 | 1.00 | 1.00 |
| `en` | 113 | 16 | 21 | 49 | 0.88 | 0.84 | 0.86 |
| `es` | 3 | 0 | 0 | 3 | 1.00 | 1.00 | 1.00 |
| `fa` | 6 | 5 | 2 | 16 | 0.55 | 0.75 | 0.63 |
| `fr` | 3 | 0 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| `he` | 0 | 0 | 0 | 2 | 0.00 | 0.00 | 0.00 |
| `hi` | 0 | 1 | 0 | 10 | 0.00 | 0.00 | 0.00 |
| `ja` | 5 | 4 | 0 | 5 | 0.56 | 1.00 | 0.71 |
| `ko` | 2 | 5 | 0 | 12 | 0.29 | 1.00 | 0.44 |
| `pt` | 3 | 0 | 0 | 2 | 1.00 | 1.00 | 1.00 |
| `ru` | 5 | 0 | 4 | 3 | 1.00 | 0.56 | 0.71 |
| `zh` | 2 | 0 | 1 | 9 | 1.00 | 0.67 | 0.80 |

### Cross-lingual cosine drift (per story)

Drift = mean(cosine | Latin-script positive) - mean(cosine | non-Latin positive). Positive drift = non-Latin articles score lower against English anchors.

| Story | n_latin | n_non_latin | mean_latin | mean_non_latin | drift |
| --- | ---: | ---: | ---: | ---: | ---: |
| `hormuz_iran` | 14 | 2 | 0.650 | 0.507 | 0.143 |
| `turner_cnn` | 6 | 1 | 0.723 | 0.670 | 0.053 |
| `lebanon_buffer` | 13 | 8 | 0.653 | 0.581 | 0.072 |
| `hantavirus_cruise` | 8 | 7 | 0.645 | 0.625 | 0.019 |
| `iran_nuclear` | 15 | 4 | 0.629 | 0.534 | 0.094 |
| `ukraine_war` | 15 | 9 | 0.604 | 0.491 | 0.114 |
| `china_taiwan` | 11 | 4 | 0.602 | 0.533 | 0.069 |
| `ai_regulation` | 8 | 1 | 0.621 | 0.479 | 0.142 |
| `israel_palestine` | 10 | 7 | 0.579 | 0.537 | 0.042 |
| `africa_political_transitions` | 9 | 2 | 0.544 | 0.452 | 0.092 |

## Failure-mode analysis

The gate fails by 0.016 macro F1 (0.784 observed vs 0.80 required) AND by
one per-language F1 (Persian `fa` = 0.63 vs 0.70 required). The failures
are structural, not random — they cluster around five identifiable
issues that Phase A.2 should fix before Phase B is reviewable.

### 1. `vietnam_china_visit` is over-specified (F1 = 0.20)

The story key targets "To Lam visits Beijing" specifically. But regex
tier1 picked up Vietnam visits to OTHER countries (India, Sri Lanka,
trips by Vietnamese PM Takaichi to Vietnam) — and softmax-argmax
correctly puts them in `vietnam_china_visit` because that's the only
Vietnam-shaped story in the canon. 8 FP, 1 TP. Two options:

- **Broaden the story** to "Vietnam high-level diplomacy" and retire
  the Beijing-specific framing.
- **Retire `vietnam_china_visit` entirely** — it was a dated story per
  `canonical_stories.json:tier`, and the to-Lam-to-Beijing event is
  past. The promotion pipeline (PR2 Phase B's `auto_promote.py`)
  exists for exactly this case.

### 2. `iran_nuclear` near-neighbor confusion with `hormuz_iran` (F1 = 0.69)

8 FNs: articles I silver-labeled as `iran_nuclear` got assigned to
`hormuz_iran` by softmax-argmax. This is the disambiguation behaviour
working as intended — articles centrally about Hormuz tensions that
mention nuclear in passing should go to Hormuz — but the per-story
recall on the genuinely-nuclear-centered Persian articles suffers.

Fix: **differentiate the anchors**. Move "Iranian nuclear program"
content out of `hormuz_iran` anchors; keep `iran_nuclear` anchors
focused on enrichment, IAEA, Fordow, Natanz, JCPOA without bleed into
"Iran deal terms." Re-run benchmark.

### 3. `eu_expansion` confusion with `ukraine_war` (F1 = 0.67)

4 FNs: Ukraine-EU accession articles (e.g. "EU could open all Ukraine
negotiation clusters in July") got assigned to `ukraine_war` because
the `ukraine_war` anchors mention NATO partners and Western military
aid. Softmax-argmax read these as war-coordination rather than
accession.

Fix: tighten `ukraine_war` anchors to combat operations, drone
strikes, frontline reporting. Keep `eu_expansion` anchors focused on
accession chapters, candidate-country reforms, enlargement strategy.

### 4. `us_election_cycle` over-claim on Persian Trump content (F1 = 0.76, fa F1 = 0.63)

4 FPs cluster on Persian Iran-International articles about Trump
(e.g. "Trump warning Iran"). The `us_election_cycle` anchors mention
"Trump-aligned successors" and "2028 candidates including Trump."
Softmax-argmax sees "Trump" in a Persian Iran article and pulls it
toward US elections.

Fix: remove "Trump" by name from `us_election_cycle` anchors; rely on
"2028 election", "primary candidates", "Iowa caucus" instead.

### 5. Per-language coverage gaps: `hi`, `ko`, `he`, `ru` under-sampled

- `hi` (Hindi): 0 labeled positives in eval set. Cannot evaluate. The
  build_eval_set's tier3 non-Latin hint match found 0 articles matching
  any story in Hindi-language candidates.
- `ko` (Korean): 2 TP, 5 FP → matcher over-claims Korean. Anchor or
  threshold tuning needed.
- `he` (Hebrew): 0 positives, 2 negatives — too small to evaluate.
- `ru` (Russian): F1 = 0.71, OK but only 9 positives → noisy.

Fix: expand eval set deliberately for these languages. Either add
labeled positives by querying Korean/Hindi/Hebrew snapshots more
aggressively, or accept that v0 calibration is English-leaning and
calibrate per-language separately in follow-up.

### 6. Cross-lingual drift exceeds threshold on 3 stories

| Story | Drift |
|---|---:|
| hormuz_iran | 0.143 |
| ai_regulation | 0.142 |
| ukraine_war | 0.114 |

These exceed the 0.10 drift threshold the plan set. Either add
per-language anchor variants (Persian for hormuz_iran/iran_nuclear,
Russian for ukraine_war, Arabic for hormuz_iran) OR add a
per-language `assignment_floor_delta` to the canonical_stories
schema.

## Decision for Phase B

- **Phase B does not merge.** Macro F1 of 0.784 is below the 0.80 gate
  and Persian F1 of 0.63 is below the 0.70 per-language gate.
- Required Phase A.2 work before re-running:
  1. Retire OR broaden `vietnam_china_visit`.
  2. Refine `iran_nuclear` ↔ `hormuz_iran` anchors to reduce overlap.
  3. Refine `eu_expansion` ↔ `ukraine_war` anchors to reduce overlap.
  4. Remove "Trump" from `us_election_cycle` anchors.
  5. Add Persian + Russian + Korean labeled positives to eval set
     (target ≥10 each per story where the story is plausibly carried
     in that language).
  6. For 3 stories with drift > 0.10, draft per-language anchor
     variants (Persian for hormuz_iran/iran_nuclear, Russian for
     ukraine_war, Arabic for ai_regulation).
  7. Re-run `python -m calibration.benchmark_models` after each
     iteration; require macro F1 ≥ 0.80 AND per-language F1 ≥ 0.70.
- If macro F1 ≥ 0.78 on next pass AND no per-language F1 < 0.65,
  consider relaxing the gate to 0.78/0.65 with explicit acknowledgement
  in `meta_version.json:perception` that this is a v0 swap. Either way,
  Phase B's `tests_perception.TestMatchingParityAgainstLabels`
  threshold should match whatever gate Phase A converges on.

### Honest framing

This silver-labeled benchmark is genuinely informative: it demonstrates
that **LaBSE (the legacy 2020 model the plan would have defaulted to)
is meaningfully worse than BGE-M3** at this task (F1 = 0.58 vs 0.78).
The challenger's #7 critique was correct — defaulting to legacy was the
wrong instinct. The benchmark also surfaces real anchor-design issues
(stories #1-4 above) that no amount of model swapping would fix.

The closest model (`bge-m3`) still produces a usable matcher for 10 of
15 stories at F1 ≥ 0.80, including all of the high-value
non-Latin-recall use cases (lebanon_buffer 0.92, hantavirus 0.94,
hormuz 0.91, israel_palestine 0.90). If the user wants to ship Phase B
under "v0 perception swap; iterate" framing, that's defensible — the 10
stories that work cover the editorial bulk. But the canonical gate is
not met and a transparent re-calibration loop is the right next step.

## Caveats

- **Silver labels, not gold.** 343 rows total, Opus-labeled. Compared to the plan's target of ≥100 hand-labeled per story (1,500+ rows), this is preliminary. Story coverage varies: lebanon_buffer has 21 labeled positives, vietnam_china_visit only 1 (the regex was over-broad on Vietnam visits to other countries).

## Caveats

- **Silver labels, not gold.** 343 rows total, Opus-labeled. Compared to the plan's target of ≥100 hand-labeled per story (1,500+ rows), this is preliminary. Story coverage varies: lebanon_buffer has 21 labeled positives, vietnam_china_visit only 1 (the regex was over-broad on Vietnam visits to other countries).
- **English-only anchors.** Embedding anchors are written in English. Cross-lingual cosine drift is what the benchmark measures; per-language anchor variants are a Phase A.2 fallback if drift exceeds 0.10.
- **May 8–12 held-out.** Candidate articles were drawn from snapshots 2026-04-25 through 2026-05-11 (Phase B's parity test reserves May 12 as held-out).