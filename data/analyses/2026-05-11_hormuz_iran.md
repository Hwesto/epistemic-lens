# Strait of Hormuz / US-Iran deal

**Date:** 2026-05-11  
**Story key:** `hormuz_iran`  
**Coverage:** 34 buckets, 61 articles  
**Model:** `claude-haiku-4-5-20251001`  
**Methodology pin:** `meta_version 8.7.1`  

---

## TL;DR

The most striking finding is the simultaneous mutual rejection of proposals by both blocs despite both claiming to offer reasonable terms: Trump rejected Iran's ceasefire counter-proposal as 'totally unacceptable' while Iran's opposition outlets characterized Iran's proposal as 'reasonable and generous.' Across the corpus, framing splits into security concerns (military experts emphasizing Iranian blockade threats), economic impacts (ASEAN and emerging economies warning of energy price shocks), and diplomatic stalemate (negotiation language vs. power posturing). Notably, Asian outlets center the economic spillover while Western security analysts focus on maritime military risk, revealing how geographic position shapes issue framing.

## Frames (5)

### SECURITY_DEFENSE — military blockade threat

**Buckets:** `germany`, `canada`, `uk`, `israel`, `india`

> Iran Must Only Succeed Once to Trigger a Catastrophe
>
> — `germany` / German military expert (corpus[9])

> Iran-Linked LPG Tanker Transits Hormuz Identifying Itself As Indian-Owned
>
> — `india` / Bloomberg/India coverage (corpus[10])

### EXTERNAL_REGULATION — ceasefire negotiation deadlock

**Buckets:** `canada`, `iran_opposition`, `iran_state`, `turkey`, `usa`

> Trump calls ceasefire counter-proposal from Iran 'totally unacceptable'
>
> — `canada` / CBC World (corpus[4])

> Iran calls proposal to US ‘reasonable and generous’
>
> — `iran_opposition` / Iran opposition outlet (corpus[13])

### ECONOMIC — energy supply crisis

**Buckets:** `asia_pacific_regional`, `philippines`, `egypt`, `south_korea`

> The closure of the Strait has led to a sudden spike in the price of oil and gas from the Middle East. This has had particularly serious impacts in Asia, which sources around 60 percent of its crude oil imports from the Gulf.
>
> — `asia_pacific_regional` / The Diplomat (corpus[0])

> Saudi Aramco has reported a 26 percent jump in first-quarter profit thanks to higher oil prices
>
> — `egypt` / Saudi/Arabia coverage (corpus[8])

### POLICY_PRESCRIPTION — regional coordination

**Buckets:** `asia_pacific_regional`, `canada`, `germany`

> called for the restoration of the safe, unimpeded, and continuous transit passage of vessels and aircraft in the Strait of Hormuz
>
> — `asia_pacific_regional` / The Diplomat / ASEAN Summit (corpus[0])

### CAPACITY_RESOURCES — energy security reserves

**Buckets:** `asia_pacific_regional`, `philippines`, `south_korea`

> the need to preserve the unimpeded flow of energy and essential goods, including food, agricultural inputs, pharmaceutical products, and transport fuels
>
> — `asia_pacific_regional` / The Diplomat (corpus[0])

## Population-weighted view

Weighted by bucket population × audience reach (`bucket_weights.json`); bootstrap CI 5–95% over 1000 bucket-resampled iterations. Unweighted share = 1 / (frames carrying any bucket) for comparison.

| Frame | Weighted share | Unweighted | Buckets |
| --- | ---: | ---: | ---: |
| `SECURITY_DEFENSE` | 0.589 | 0.385 | 5 |
| `EXTERNAL_REGULATION` | 0.311 | 0.385 | 5 |
| `ECONOMIC` | 0.124 | 0.308 | 4 |
| `POLICY_PRESCRIPTION` | 0.114 | 0.231 | 3 |
| `CAPACITY_RESOURCES` | 0.088 | 0.231 | 3 |

_Low-confidence weights (treat with caution): `asia_pacific_regional`, `egypt`, `iran_opposition`, `iran_state`, `philippines`._

_Default-weight buckets (no entry in `bucket_weights.json`): `south_korea`._

_Bootstrap CIs skipped: numpy unavailable._

## Most divergent buckets

| Bucket | mean_similarity | Note |
| --- | --- | --- |
| `nordic` | 0.426 | Outlier with lowest isolation; minimal regional coverage or distinctive framing. |
| `kenya` | 0.713 | High integration; Kenya's coverage aligns closely with wire services and African regional consensus. |

## Bucket-exclusive vocabulary

| Bucket | Distinctive terms | What it reveals |
| --- | --- | --- |
| `asia_pacific_regional` | *asean*, *southeast*, *joint*, *apsa* | Framing centers on regional cooperation institutions and collective energy security — not bilateral diplomacy. |
| `south_korea` | *korea*, *opcon*, *seoul*, *wartime* | Links Hormuz crisis to Korean peninsula military readiness; frames as security cascade affecting multiple theaters. |
| `italy` | *cessate*, *fuoco*, *armi*, *deluso* | Italian press emphasizes ceasefire and arms framing; frames as conflict requiring unified opposition, not negotiation. |
| `usa` | *slick*, *funding*, *spill*, *immigration* | US outlets connect maritime security to domestic environmental and border concerns; broadens spillover narrative beyond energy. |

## Within-language LLR distinctive vocab

Per-bucket terms over-represented vs the same-language cohort (Dunning log-likelihood ratio; p ≤ 0.001). Effect size is log-rate-ratio.

| Bucket | Lang | Top distinctive terms (LLR) |
| --- | --- | --- |
| `asia_pacific_regional` | en | `asean` (50.53), `middle` (10.833), `east` (10.833) |
| `china` | en | `china` (36.754), `wang` (36.341) |
| `egypt` | en | `saudi` (32.378) |
| `india` | en | `tracking` (27.185), `weakest` (21.914) |
| `iran_opposition` | en | `gray` (26.344), `baghaei` (20.916), `tehran` (18.531), `side` (17.702), `washington` (17.592) |
| `iraq` | en | `iraqi` (49.299) |
| `israel` | en | `trump` (16.117) |
| `japan` | en | `profit` (46.103), `delay` (32.623), `billion` (27.948), `compan` (24.402) |
| `opinion_magazines` | en | `diesel` (46.938), `energy` (31.458), `fuel` (30.392), `economy` (18.13), `world` (12.768) |
| `philippines` | en | `energy` (12.153) |
| `south_korea` | en | `korea` (66.095), `opcon` (47.987), `transfer` (41.808), `south` (41.808), `defense` (27.949) |
| `state_tv_intl` | en | `houthi` (36.72), `nigeria` (31.461), `somali` (26.206), `somalia` (25.869) |
| `turkey` | en | `kalla` (26.505), `minister` (21.637) |
| `uk` | en | `european` (40.025), `nato` (31.422) |
| `usa` | en | `slick` (47.032), `funding` (31.314), `congres` (20.829), `infrastructure` (18.012) |

## Associative bigrams (within-language)

Bigrams over-represented in this bucket vs the same-language cohort. Log-odds with Jeffreys prior; |Z| ≥ 1.96.

| Bucket | Lang | Top bigram associations |
| --- | --- | --- |
| `asia_pacific_regional` | en | `middle east` (z=4.28), `reopening strait` (z=3.34), `response iran` (z=3.34), `asean leader` (z=3.04) |
| `canada` | en | `trump call` (z=4.74), `counter proposal` (z=4.69), `reopen strait` (z=4.69), `totally unacceptable` (z=4.11) |
| `china` | en | `iranian port` (z=3.92), `foreign affair` (z=3.37), `united arab` (z=3.37), `arab emirat` (z=3.37) |
| `egypt` | en | `crude pric` (z=6.11), `saudi arabia` (z=4.59), `arabia giant` (z=4.34), `giant gets` (z=4.34) |
| `germany` | en | `hormuz iran` (z=5.39), `military expert` (z=4.3), `expert tanker` (z=4.3), `tanker convoy` (z=4.3) |
| `india` | en | `iran ceasefire` (z=3.06), `data show` (z=3.05), `commercial vessel` (z=3.05), `ship tracking` (z=3.04) |
| `iran_opposition` | en | `reasonable generou` (z=3.0), `gordon gray` (z=3.0), `washington demand` (z=2.99), `demand tehran` (z=2.99) |
| `iran_state` | en | `persian gulf` (z=5.59), `gulf national` (z=4.09), `with iran` (z=4.06), `cannot with` (z=3.77) |
| `iraq` | en | `iraqi tanker` (z=4.56), `tanker brave` (z=4.56), `brave strait` (z=4.56), `hormuz risk` (z=4.56) |
| `israel` | en | `trump iran` (z=4.3), `hormuz trump` (z=4.28), `escort ship` (z=4.28), `vessel strait` (z=3.71) |
| `japan` | en | `supply chain` (z=4.17), `fuel pric` (z=3.61), `major japanese` (z=3.42), `shipping compan` (z=3.42) |
| `kenya` | en | `conflict iran` (z=3.48), `plan escort` (z=3.48), `hormuz ship` (z=3.45), `percent barrel` (z=3.03) |
| `nigeria` | en | `energy shock` (z=7.54), `saudi aramco` (z=6.5), `world largest` (z=4.85), `largest energy` (z=4.85) |
| `nordic` | en | `fuel shortag` (z=6.1), `cancel flight` (z=4.77), `flight fuel` (z=4.77) |
| `opinion_magazines` | en | `diesel fuel` (z=3.48), `major driver` (z=2.97), `even harder` (z=2.97), `energy market` (z=2.95) |
| `pakistan` | en | `iran response` (z=4.59), `qatari tanker` (z=4.46), `trump reject` (z=4.1), `reject iran` (z=4.1) |
| `pan_african` | en | `iran deal` (z=6.06), `hormuz remain` (z=5.99), `ship strait` (z=5.68), `remain stranded` (z=4.5) |
| `pan_arab` | en | `iran deal` (z=4.13), `deal possible` (z=4.13), `current energy` (z=4.0), `energy supply` (z=4.0) |
| `philippines` | en | `energy shock` (z=5.48), `diesel pric` (z=4.68), `second wave` (z=4.06), `shock iran` (z=4.06) |
| `qatar` | en | `unreasonable demand` (z=5.35), `middle east` (z=4.19), `iran making` (z=4.13), `making unreasonable` (z=4.13) |
| `religious_press` | en | `president trump` (z=4.04), `call iran` (z=4.04), `iran reply` (z=4.04), `peace plan` (z=4.04) |
| `russia` | en | `iran ceasefire` (z=4.87), `expect pric` (z=4.05), `pric fall` (z=4.05), `fall midterm` (z=4.05) |
| `south_africa` | en | `response peace` (z=5.26), `peace proposal` (z=4.98), `iran response` (z=4.9), `proposal unacceptable` (z=4.67) |
| `south_korea` | en | `south korea` (z=3.76), `defense chief` (z=3.45), `opcon transfer` (z=3.45), `hormuz ship` (z=3.28) |
| `state_tv_intl` | en | `domino effect` (z=2.68), `effect iran` (z=2.68), `iran israel` (z=2.68), `israel tension` (z=2.68) |
| `turkey` | en | `defense minister` (z=3.5), `lift sanction` (z=3.2), `minister discussed` (z=3.2), `sanction syria` (z=2.99) |
| `uk` | en | `foreign minister` (z=4.36), `response peace` (z=4.13), `iran response` (z=3.68), `trump ceasefire` (z=3.43) |
| `ukraine` | en | `prime minister` (z=4.99), `iran peace` (z=4.2), `blind spot` (z=3.78), `russia iran` (z=3.78) |
| `usa` | en | `suspected slick` (z=2.96), `iran last` (z=2.94), `second suspected` (z=2.67), `slick near` (z=2.67) |
| `vietnam_thai_my` | en | `visit qatar` (z=4.03), `talk iran` (z=4.03), `massive life` (z=3.98), `foreign minister` (z=3.59) |
| `wire_services` | en | `million barrel` (z=5.69), `hormuz remain` (z=5.68), `market lose` (z=5.28), `peace proposal` (z=5.01) |

## Voices

26 direct quote(s) extracted across 9 outlet(s).

**Top speakers:** <unnamed: Trump> (4), Trump (3), Trump Washington (2), Netanyahu (2), <unnamed: he> (2)

**Speaker types:** unknown 20, official 6

## Paradox

**Both sides simultaneously claim their own proposals are reasonable while categorically rejecting the other's, revealing a framing deadlock where convergence appears impossible.**

> Trump calls ceasefire counter-proposal from Iran 'totally unacceptable'
>
> — `canada` / CBC World (reporting Trump) (corpus[4])

> Iran calls proposal to US ‘reasonable and generous’
>
> — `iran_opposition` / Iran opposition media (corpus[13])


## Silence as data

- **`brazil`** — Saudi Arabia's military response and regional pressure (Rubio's diplomacy, MbS's airspace denial) — tactical statecraft rather than proposal content.
- **`russia`** — Covered primarily China's economic interests in Iranian oil and maritime access; largely absent from negotiation analysis.

## Single-outlet findings

1. **The Diplomat** (`asia_pacific_regional`): ASEAN frames Strait reopening as prerequisite for collective energy security and food price stability; mobilizes regional institutions as unified actor. (corpus[0])
2. **CBC World** (`canada`): Trump's rejection uses absolutist language ('totally unacceptable'); Iran's scope includes Lebanon/Hezbollah, suggesting divergent definitions of what 'ending war' means. (corpus[4])
3. **German security analyst** (`germany`): Emphasizes asymmetric vulnerability: 'Iran must only succeed once' framing suggests regional military balance is tilted against Iran. (corpus[9])

## Bottom line

The Strait of Hormuz crisis fragments into negotiation deadlock narrative (Western and Iranian media) versus energy security cascade narrative (Asia and emerging economies), with each bloc's geographic interests determining whether diplomatic stalemate or economic spillover dominates the framing.

---

_Generated by `render_analysis_md.py` from `analyses/2026-05-11_hormuz_iran.json`. The JSON is the canonical artifact; this markdown is a render._
