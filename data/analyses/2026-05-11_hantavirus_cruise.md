# Hantavirus outbreak on cruise ship

**Date:** 2026-05-11  
**Story key:** `hantavirus_cruise`  
**Coverage:** 32 buckets, 58 articles  
**Model:** `claude-haiku-4-5-20251001`  
**Methodology pin:** `meta_version 8.7.1`  

---

## TL;DR

Global coverage of hantavirus outbreak reveals public health framing.

## Frames (3)

### HEALTH_SAFETY

**Buckets:** `argentina_chile`, `asia_pacific_regional`

> Hantavirus en el crucero: en qué consiste la cepa Andes, la única que se contagia entre humanos y qu
>
> — `argentina_chile` (corpus[0])

### CAPACITY_RESOURCES

**Buckets:** `argentina_chile`, `australia_nz`

> Hantavirus en el crucero: en qué consiste la cepa Andes, la única que se contagia entre humanos y qu
>
> — `argentina_chile` (corpus[0])

### POLICY_PRESCRIPTION

**Buckets:** `argentina_chile`, `asia_pacific_regional`

> Hantavirus en el crucero: en qué consiste la cepa Andes, la única que se contagia entre humanos y qu
>
> — `argentina_chile` (corpus[0])

## Population-weighted view

Weighted by bucket population × audience reach (`bucket_weights.json`); bootstrap CI 5–95% over 1000 bucket-resampled iterations. Unweighted share = 1 / (frames carrying any bucket) for comparison.

| Frame | Weighted share | Unweighted | Buckets |
| --- | ---: | ---: | ---: |
| `HEALTH_SAFETY` | 0.781 | 0.667 | 2 |
| `CAPACITY_RESOURCES` | 0.558 | 0.667 | 2 |
| `POLICY_PRESCRIPTION` | 0.781 | 0.667 | 2 |

_Low-confidence weights (treat with caution): `argentina_chile`, `asia_pacific_regional`._

_Bootstrap CIs skipped: numpy unavailable._

## Most divergent buckets

| Bucket | mean_similarity | Note |
| --- | --- | --- |
| `balkans` | 0.481 |  |

## Within-language LLR distinctive vocab

Per-bucket terms over-represented vs the same-language cohort (Dunning log-likelihood ratio; p ≤ 0.001). Effect size is log-rate-ratio.

| Bucket | Lang | Top distinctive terms (LLR) |
| --- | --- | --- |
| `mexico` | es | `sheinbaum` (13.467), `cártel` (13.467), `méxico` (11.775) |
| `state_tv_intl` | es | `hantaviru` (15.957) |
| `india` | en | `noroviru` (31.098), `infection` (14.131) |
| `kenya` | en | `tedro` (37.424) |
| `south_korea` | en | `korea` (52.208) |
| `taiwan_hk` | en | `medical` (17.887) |
| `uk` | en | `french` (14.71) |
| `vietnam_thai_my` | en | `evacuation` (13.294) |

## Associative bigrams (within-language)

Bigrams over-represented in this bucket vs the same-language cohort. Log-odds with Jeffreys prior; |Z| ≥ 1.96.

| Bucket | Lang | Top bigram associations |
| --- | --- | --- |
| `argentina_chile` | en | `tierra fuego` (z=4.37), `fuego health` (z=4.03), `health zero` (z=4.03), `zero chance` (z=4.03) |
| `state_tv_intl` | es | `francesa estadounidense` (z=2.96), `siete número` (z=2.69), `brote hantaviru` (z=2.69), `cinco frances` (z=2.54) |
| `asia_pacific_regional` | en | `hantaviru scare` (z=5.21), `scare expos` (z=4.09), `expos china` (z=4.09), `china mrna` (z=4.09) |
| `australia_nz` | en | `three week` (z=2.96), `flight home` (z=2.96), `ship struck` (z=2.85), `passenger remain` (z=2.85) |
| `balkans` | en | `naučnica objašnjava` (z=3.92), `objašnjava zašto` (z=3.92), `zašto nema` (z=3.92), `nema mesta` (z=3.92) |
| `canada` | en | `four canadian` (z=2.92), `case linked` (z=2.44), `linked cruise` (z=2.44), `reassure public` (z=2.33) |
| `germany` | en | `south america` (z=3.22), `outbreak contained` (z=2.9), `contained passenger` (z=2.9), `hondiu cruise` (z=2.74) |
| `india` | en | `killed three` (z=3.2), `noroviru hantaviru` (z=2.93), `global concern` (z=2.72), `ship outbreak` (z=2.71) |
| `indonesia` | en | `cruise outbreak` (z=5.83), `hantaviru cruise` (z=5.55), `test foreigner` (z=4.41), `foreigner negative` (z=4.41) |
| `iraq` | en | `hantaviru ship` (z=6.33), `ship test` (z=6.28), `test positive` (z=5.7), `citizen hantaviru` (z=4.5) |
| `japan` | en | `national hantaviru` (z=4.91), `does expect` (z=4.75), `hantaviru ship` (z=4.4), `japan does` (z=3.87) |
| `kenya` | en | `health organisation` (z=3.05), `strain hantaviru` (z=3.05), `three death` (z=3.05), `viru cruise` (z=3.05) |
| `netherlands_belgium` | en | `hondiu passenger` (z=3.94), `three died` (z=3.28), `trust hondiu` (z=3.01), `passenger quarantine` (z=3.01) |
| `nigeria` | en | `hantaviru full` (z=4.58), `full list` (z=4.58), `list case` (z=4.58), `case countr` (z=4.58) |
| `nordic` | en | `finland exposed` (z=4.82), `exposed hantaviru` (z=4.82) |
| `opinion_magazines` | en | `hantaviru covid` (z=4.86), `disease outbreak` (z=4.7), `citizen test` (z=4.7), `covid noroviru` (z=3.85) |
| `pakistan` | en | `national hantaviru` (z=4.14), `ship test` (z=4.06), `french national` (z=3.69), `hantaviru ship` (z=3.44) |
| `pan_african` | en | `stricken cruise` (z=5.84), `passenger evacuated` (z=4.94), `cruise ship` (z=3.96), `hantaviru stricken` (z=3.93) |
| `qatar` | en | `passenger test` (z=6.16), `test positive` (z=5.35), `ship passenger` (z=4.83), `positive hantaviru` (z=4.19) |
| `russia` | en | `fear hantaviru` (z=4.45), `response team` (z=4.45), `chief dismiss` (z=3.68), `dismiss covid` (z=3.68) |
| `south_africa` | en | `ande viru` (z=3.45), `aboard hondiu` (z=3.02), `necessarily quarantined` (z=3.01), `authorit track` (z=3.01) |
| `south_korea` | en | `ship outbreak` (z=4.45), `korean frontier` (z=4.18), `frontier discovery` (z=4.18), `discovery prevention` (z=4.18) |
| `taiwan_hk` | en | `britain remote` (z=3.5), `hong kong` (z=3.5), `paratrooper jump` (z=3.19), `jump britain` (z=3.19) |
| `turkey` | en | `canary island` (z=3.81), `spanish health` (z=2.83), `cape verde` (z=2.83), `island oversee` (z=2.77) |
| `uk` | en | `french national` (z=3.14), `hantaviru leaving` (z=3.01), `with case` (z=2.9), `american national` (z=2.9) |
| `usa` | en | `hantaviru stricken` (z=4.44), `stricken cruise` (z=4.33), `different covid` (z=3.87), `covid pandemic` (z=3.8) |
| `vietnam_thai_my` | en | `ship captain` (z=3.02), `passenger crew` (z=2.85), `started feel` (z=2.74), `feel unwell` (z=2.74) |

## Voices

19 direct quote(s) extracted across 7 outlet(s).

**Top speakers:** <unnamed: ,> (3), Health Minister (1), <unnamed: for them to quarantine for three weeks.
Health Minister Mark Butler> (1), Butler (1), Spanish (1)

**Speaker types:** unknown 15, official 4

## Paradox

_No paradox in this corpus._

## Bottom line

Global coverage of hantavirus_cruise varies by regional interest and security posture.

---

_Generated by `render_analysis_md.py` from `analyses/2026-05-11_hantavirus_cruise.json`. The JSON is the canonical artifact; this markdown is a render._
