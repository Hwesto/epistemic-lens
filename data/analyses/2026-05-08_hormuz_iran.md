# Strait of Hormuz / US-Iran deal

**Date:** 2026-05-08  
**Story key:** `hormuz_iran`  
**Coverage:** 33 buckets, 59 articles  
**Model:** `claude-haiku-4-5-20251001`  
**Methodology pin:** `meta_version 1.4.1`  

---

## TL;DR

The US-Iran confrontation over the Strait of Hormuz frames as either strategic blockade (weakening Iran economically) or illegal maritime control (empowering Iran regionally). ASEAN's primary narrative emphasizes energy supply shock—a rare outsider perspective. Both US blockade strategy and ASEAN vulnerability converge on strait closure as power instrument, demonstrating how unilateral coercion redistributes costs globally.

## Frames (5)

### ECONOMIC_BLOCKADE_EFFICACY

**Buckets:** `canada`

> How the U.S. blockade is starting to hurt Iran's economy
>
> — `canada` / CBC World (corpus[4])

### CEASEFIRE_FRAGILITY

**Buckets:** `canada`

> U.S. says it intercepted Iranian attacks on 3 navy ships in Strait of Hormuz
>
> — `canada` / CBC World (corpus[5])

### REGIONAL_ECONOMIC_CRISIS

**Buckets:** `asia_pacific_regional`

> The economic fallout from the war in the Middle East has dominated talks between senior Southeast Asian officials at the 48th ASEAN Summit and related meetings, which got underway in the Philippines yesterday.
>
> — `asia_pacific_regional` / The Diplomat (corpus[0])

### DEAL_NEGOTIATION_WINDOW

**Buckets:** `brazil`

> Trump recua e diz que operação para reabrir Hormuz será suspensa em tentativa de finalizar acordo
>
> — `brazil` / Folha de São Paulo (corpus[2])

### MARITIME_CONTROL_FORMALIZATION

**Buckets:** `canada`

> Earlier in the day, a shipping data company reported Iran had created a government agency to vet and tax vessels seeking passage through the crucial Strait of Hormuz.
>
> — `canada` / CBC World (corpus[5])

## Population-weighted view

Weighted by bucket population × audience reach (`bucket_weights.json`); bootstrap CI 5–95% over 1000 bucket-resampled iterations. Unweighted share = 1 / (frames carrying any bucket) for comparison.

| Frame | Weighted share | 90% CI | Unweighted | Buckets |
| --- | ---: | --- | ---: | ---: |
| `ECONOMIC_BLOCKADE_EFFICACY` | 0.148 | [0.00, 0.55] | 0.333 | 1 |
| `CEASEFIRE_FRAGILITY` | 0.148 | [0.00, 0.55] | 0.333 | 1 |
| `REGIONAL_ECONOMIC_CRISIS` | 0.239 | [0.00, 0.76] | 0.333 | 1 |
| `DEAL_NEGOTIATION_WINDOW` | 0.613 | [0.00, 0.89] | 0.333 | 1 |
| `MARITIME_CONTROL_FORMALIZATION` | 0.148 | [0.00, 0.55] | 0.333 | 1 |

_Low-confidence weights (treat with caution): `asia_pacific_regional`._

## Most divergent buckets

| Bucket | mean_similarity | Note |
| --- | --- | --- |
| `italy` |  | Linguistically isolated; minimal coverage. |

## Within-language LLR distinctive vocab

Per-bucket terms over-represented vs the same-language cohort (Dunning log-likelihood ratio; p ≤ 0.001). Effect size is log-rate-ratio.

| Bucket | Lang | Top distinctive terms (LLR) |
| --- | --- | --- |
| `asia_pacific_regional` | en | `asean` (31.905), `foreign` (18.505) |
| `canada` | en | `economy` (18.881), `blockade` (17.956), `iranian` (16.131) |
| `china` | en | `wang` (37.241), `china` (23.17) |
| `india` | en | `project` (13.556), `naval` (11.965), `israeli` (11.807), `forc` (10.866) |
| `iran_opposition` | en | `fertilizer` (37.121), `farmer` (27.005), `guns` (27.005), `weapon` (21.736), `million` (14.402) |
| `iran_state` | en | `maritime` (23.116) |
| `israel` | en | `trump` (14.701) |
| `opinion_magazines` | en | `tariff` (26.523), `petrodollar` (26.523), `gulf` (20.798), `united` (13.116) |
| `pan_arab` | en | `tanker` (20.523), `china` (16.007), `attack` (12.107) |
| `philippines` | en | `asean` (36.719), `marco` (23.518), `middle` (19.376), `east` (19.376) |
| `russia` | en | `escalation` (21.115) |
| `south_africa` | en | `destroyer` (15.952), `damage` (13.165) |
| `south_korea` | en | `korea` (61.055), `cooperation` (22.261) |
| `spain` | en | `crude` (34.094), `world` (13.868) |
| `turkey` | en | `hormuz` (11.101) |
| `uk` | en | `exchange` (12.124) |
| `usa` | en | `enrichment` (26.3), `israel` (19.273), `israeli` (12.172) |
| `vietnam_thai_my` | en | `fuel` (28.523), `member` (18.264), `asean` (17.871), `regional` (10.993) |
| `wire_services` | en | `sanction` (41.682), `china` (20.708) |

## Associative bigrams (within-language)

Bigrams over-represented in this bucket vs the same-language cohort. Log-odds with Jeffreys prior; |Z| ≥ 1.96.

| Bucket | Lang | Top bigram associations |
| --- | --- | --- |
| `asia_pacific_regional` | en | `supply shock` (z=3.51), `iran long` (z=3.35), `long history` (z=3.35), `history standing` (z=3.35) |
| `canada` | en | `iranian media` (z=3.58), `intercepted iranian` (z=3.56), `navy ship` (z=3.56), `iran economy` (z=3.4) |
| `china` | en | `iranian port` (z=4.1), `maritime acces` (z=3.31), `acces restriction` (z=3.31), `restriction enforced` (z=3.31) |
| `egypt` | en | `tension escalate` (z=4.35), `escalate strait` (z=4.35), `hormuz diplomacy` (z=4.35), `diplomacy race` (z=4.35) |
| `germany` | en | `hormuz iran` (z=4.71), `military expert` (z=3.97), `expert tanker` (z=3.97), `tanker convoy` (z=3.97) |
| `india` | en | `project freedom` (z=4.59), `base airspace` (z=3.47), `gulf stat` (z=3.18), `restore acces` (z=2.97) |
| `iran_opposition` | en | `iran international` (z=3.24), `work equipment` (z=3.03), `fertilizer pric` (z=3.03), `million rial` (z=3.03) |
| `iran_state` | en | `hormuz iran` (z=5.51), `commercial ship` (z=4.77), `ship strait` (z=4.22), `permanent lifting` (z=4.12) |
| `iraq` | en | `iran clash` (z=7.61), `jump stock` (z=4.61), `stock fall` (z=4.61), `fall iran` (z=4.61) |
| `israel` | en | `strik iran` (z=5.71), `hormuz trump` (z=5.71), `ceasefire effect` (z=5.65), `clash strait` (z=5.62) |
| `japan` | en | `fire threatening` (z=6.41), `threatening fragile` (z=6.41), `iran trade` (z=6.37), `trade fire` (z=6.37) |
| `kenya` | en | `trump idiot` (z=3.09), `idiot californian` (z=3.09), `californian fume` (z=3.09), `fume soaring` (z=3.09) |
| `nigeria` | en | `iran trade` (z=6.77), `trade fire` (z=6.77), `fragile truce` (z=6.77), `fire threatening` (z=6.72) |
| `nordic` | en | `germany lufthansa` (z=4.39), `lufthansa warn` (z=4.39), `warn hefty` (z=4.39), `hefty fuel` (z=4.39) |
| `opinion_magazines` | en | `united stat` (z=4.21), `saudi arabia` (z=2.95), `gulf countr` (z=2.88), `regional global` (z=2.7) |
| `pakistan` | en | `saudi pressure` (z=3.54), `small boat` (z=3.12), `pressure pause` (z=3.08), `pause hormuz` (z=3.08) |
| `pan_arab` | en | `tanker strait` (z=5.36), `foreign ministry` (z=4.87), `hormuz china` (z=4.42), `china attack` (z=4.18) |
| `philippines` | en | `middle east` (z=5.87), `closure strait` (z=4.35), `asean leader` (z=3.74), `east crisi` (z=3.51) |
| `qatar` | en | `trump ceasefire` (z=5.89), `ceasefire effect` (z=5.37), `effect iran` (z=5.29), `iran clash` (z=5.09) |
| `religious_press` | en | `tense situation` (z=4.27), `situation strait` (z=4.27), `iran talk` (z=4.27), `talk closer` (z=4.27) |
| `russia` | en | `president trump` (z=3.84), `iran launched` (z=3.84), `media iran` (z=3.82), `military escalation` (z=3.26) |
| `south_africa` | en | `damage done` (z=4.54), `good talk` (z=4.12), `threat iran` (z=3.56), `great damage` (z=3.56) |
| `south_korea` | en | `energy suppl` (z=4.55), `freedom navigation` (z=4.35), `fire strait` (z=3.85), `ceasefire with` (z=3.85) |
| `spain` | en | `first time` (z=3.64), `fossil fuel` (z=3.64), `million barrel` (z=3.64), `closure strait` (z=3.23) |
| `turkey` | en | `tension with` (z=4.43), `iran impos` (z=4.1), `impos transit` (z=4.1), `transit rule` (z=4.1) |
| `uk` | en | `exchange fire` (z=4.59), `small boat` (z=4.08), `ceasefire place` (z=3.98), `trump iran` (z=3.59) |
| `ukraine` | en | `strik iranian` (z=5.72), `attack navy` (z=4.87), `navy destroyer` (z=4.87), `ship strait` (z=4.35) |
| `usa` | en | `enriched material` (z=2.99), `attack ship` (z=2.88), `israel want` (z=2.7), `want iran` (z=2.7) |
| `vietnam_thai_my` | en | `member stat` (z=4.07), `china russia` (z=4.07), `regional fuel` (z=3.57), `fuel stockpile` (z=3.57) |
| `wire_services` | en | `with iran` (z=3.53), `china based` (z=3.39), `based refinery` (z=3.39), `busines with` (z=3.39) |

## Paradox

**US blockade intent and ASEAN consequence diverge but converge on strait closure as power instrument.**

> How the U.S. blockade is starting to hurt Iran's economy
>
> — `canada` / CBC World (corpus[4])

> ASEAN imports about 66 percent of its crude oil and is now facing a significant rise in fuel and energy costs that would, in turn, force up the prices of food and other essential goods.
>
> — `asia_pacific_regional` / The Diplomat (corpus[0])


## Single-outlet findings

1. **Brazil - Folha de São Paulo** (`brazil`): Trump pauses operations pending 30-day negotiations. (corpus[2])

## Bottom line

The Hormuz crisis bifurcates: military escalation dominates Western coverage; ASEAN frames it as energy emergency. US coercion and ASEAN vulnerability are linked outcomes.

---

_Generated by `render_analysis_md.py` from `analyses/2026-05-08_hormuz_iran.json`. The JSON is the canonical artifact; this markdown is a render._
