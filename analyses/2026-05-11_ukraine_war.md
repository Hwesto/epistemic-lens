# Ukraine military and territorial developments

**Date:** 2026-05-11  
**Story key:** `ukraine_war`  
**Coverage:** 23 buckets, 38 articles  
**Model:** `claude-haiku-4-5-20251001`  
**Methodology pin:** `meta_version 8.7.1`  

---

## TL;DR

War coverage fragments between military strategy, political consequences, and alliance politics.

## Frames (3)

### SECURITY_DEFENSE

**Buckets:** `brazil`, `canada`

> Como a Ucrânia conseguiu usar a seu favor o tremendo impacto da guerra no Irã

O presidente da Ucrân
>
> — `brazil` (corpus[0])

### POLITICAL

**Buckets:** `brazil`, `germany`

> Como a Ucrânia conseguiu usar a seu favor o tremendo impacto da guerra no Irã

O presidente da Ucrân
>
> — `brazil` (corpus[0])

### EXTERNAL_REGULATION

**Buckets:** `brazil`, `canada`

> Como a Ucrânia conseguiu usar a seu favor o tremendo impacto da guerra no Irã

O presidente da Ucrân
>
> — `brazil` (corpus[0])

## Population-weighted view

Weighted by bucket population × audience reach (`bucket_weights.json`); bootstrap CI 5–95% over 1000 bucket-resampled iterations. Unweighted share = 1 / (frames carrying any bucket) for comparison.

| Frame | Weighted share | Unweighted | Buckets |
| --- | ---: | ---: | ---: |
| `SECURITY_DEFENSE` | 0.723 | 0.667 | 2 |
| `POLITICAL` | 0.860 | 0.667 | 2 |
| `EXTERNAL_REGULATION` | 0.723 | 0.667 | 2 |

_Bootstrap CIs skipped: numpy unavailable._

## Most divergent buckets

| Bucket | mean_similarity | Note |
| --- | --- | --- |
| `japan` | 0.403 |  |

## Within-language LLR distinctive vocab

Per-bucket terms over-represented vs the same-language cohort (Dunning log-likelihood ratio; p ≤ 0.001). Effect size is log-rate-ratio.

| Bucket | Lang | Top distinctive terms (LLR) |
| --- | --- | --- |
| `india` | en | `putin` (14.664) |
| `religious_press` | en | `mother` (42.498) |
| `russia` | en | `french` (25.51), `france` (23.24), `korea` (19.861), `national` (19.832), `philippot` (18.201) |
| `south_africa` | en | `accusation` (39.13), `ceasefire` (16.1) |
| `taiwan_hk` | en | `narrativ` (33.356), `sanction` (13.005) |
| `turkey` | en | `christian` (32.571), `tajani` (23.843) |
| `uk` | en | `putin` (15.095) |
| `ukraine` | en | `brigade` (36.597), `vampire` (32.919) |
| `usa` | en | `partner` (26.255) |
| `vietnam_thai_my` | en | `zelenskiy` (31.96) |

## Associative bigrams (within-language)

Bigrams over-represented in this bucket vs the same-language cohort. Log-odds with Jeffreys prior; |Z| ≥ 1.96.

| Bucket | Lang | Top bigram associations |
| --- | --- | --- |
| `canada` | en | `victory parade` (z=2.82), `parade ukraine` (z=2.59), `ceasefire deadline` (z=2.54), `deadline loom` (z=2.54) |
| `germany` | en | `ukraine russian` (z=4.22), `ukraine sanction` (z=3.48), `sanction russian` (z=3.48), `russian systematic` (z=3.48) |
| `india` | en | `russia agreed` (z=3.93), `coming putin` (z=3.9), `india china` (z=3.62), `western elit` (z=3.62) |
| `iran_opposition` | en | `missile attack` (z=4.85), `ukraine russian` (z=3.85), `parade ukraine` (z=3.85), `ukraine deadly` (z=3.85) |
| `italy` | en | `peace talk` (z=5.65), `talk russia` (z=5.61), `decide negotiator` (z=4.28), `negotiator ukraine` (z=4.28) |
| `japan` | en | `north korea` (z=6.05), `korea reap` (z=4.56), `reap huge` (z=4.56), `huge economic` (z=4.56) |
| `kenya` | en | `ukraine deadly` (z=4.41), `ukraine trade` (z=4.41), `deadly drone` (z=4.32), `kenyan recruit` (z=3.59) |
| `korea_north` | en | `north korean` (z=4.21), `russia award` (z=3.09), `award north` (z=3.09), `korean hero` (z=3.09) |
| `nordic` | en | `german chancellor` (z=6.26), `berlin sceptical` (z=4.06), `sceptical putin` (z=4.06), `putin float` (z=4.06) |
| `opinion_magazines` | en | `victory ukraine` (z=4.98), `russia doesn` (z=4.03), `doesn celebrate` (z=4.03), `celebrate victory` (z=4.03) |
| `pan_arab` | en | `three killed` (z=5.95), `strik ukraine` (z=5.49), `ukraine ceasefire` (z=5.25), `russian strik` (z=4.57) |
| `poland_balt` | en | `military intelligence` (z=4.16), `deep strik` (z=4.16), `intelligence ukraine` (z=3.83), `ukraine capable` (z=3.83) |
| `religious_press` | en | `ukrainian mother` (z=3.77), `mother taken` (z=3.77), `taken away` (z=3.77), `away everyone` (z=3.77) |
| `russia` | en | `north korea` (z=3.49), `sanction russia` (z=2.54), `french presidential` (z=2.37), `presidential hopeful` (z=2.37) |
| `south_africa` | en | `russia ukraine` (z=5.59), `russia trade` (z=4.37), `ukraine trade` (z=4.37), `ceasefire violation` (z=4.37) |
| `taiwan_hk` | en | `ukrainian children` (z=4.68), `kremlin narrativ` (z=3.7), `individual organisation` (z=3.47), `sanction entit` (z=3.16) |
| `turkey` | en | `middle east` (z=3.05), `cease fire` (z=3.04), `fire ukraine` (z=3.04), `foreign minister` (z=2.95) |
| `uk` | en | `former german` (z=3.97), `russia europe` (z=3.94), `chancellor gerhard` (z=3.89), `peace talk` (z=3.89) |
| `ukraine` | en | `ukrainian soldier` (z=2.91), `russian captivity` (z=2.55), `soldier russian` (z=2.37), `vampire heavy` (z=2.37) |
| `usa` | en | `front line` (z=2.46), `united stat` (z=2.41), `ukraine monday` (z=2.14), `ukrainian president` (z=2.14) |
| `vietnam_thai_my` | en | `russia trade` (z=3.53), `ukraine russia` (z=3.23), `zelenskiy hold` (z=3.08), `hold call` (z=3.08) |
| `wire_services` | en | `mediated ceasefire` (z=5.46), `ukraine russia` (z=4.81), `russia fight` (z=4.47), `fight mediated` (z=4.47) |

## Voices

7 direct quote(s) extracted across 6 outlet(s).

**Top speakers:** <unnamed: s Defence Ministry> (1), Trump (1), On Victory (1), Russia (1), After Putin (1)

**Speaker types:** unknown 7

## Paradox

_No paradox in this corpus._

## Bottom line

Global coverage of ukraine_war varies by regional interest and security posture.

---

_Generated by `render_analysis_md.py` from `analyses/2026-05-11_ukraine_war.json`. The JSON is the canonical artifact; this markdown is a render._
