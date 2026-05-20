# Before / After — Epistemic Lens v0.2 -> v0.4

## Coverage

| Metric | v0.2 baseline (2026-05-02) | v0.4 (2026-05-06) | Δ |
|---|---|---|---|
| Feeds | 51 | 138 | +87 |
| Items | 467 | 3807 | +3340 (8.2x) |
| Country buckets | 16 | 47 | +31 |

### New buckets (31)

africa_other, argentina_chile, australia_nz, balkans, belarus_caucasus, canada, colombia_ven_peru, egypt, germany, hungary_central, indonesia, iraq, italy, jordan, kenya, korea_north, lebanon, mexico, netherlands_belgium, nordic, pakistan, palestine, philippines, poland_balt, russia_native, south_africa, spain, syria, taiwan_hk, ukraine, vietnam_thai_my

## Language / script distribution (in titles)

| Script | v0.2 | v0.4 | Δ |
|---|---|---|---|
| latin | 400 | 3379 | +2979 |
| ru-cyrillic | 0 | 170 | +170 |
| ar/fa | 30 | 124 | +94 |
| zh/ja-han | 17 | 58 | +41 |
| hi-deva | 10 | 46 | +36 |
| he | 10 | 30 | +20 |

### Cyrillic content fix
v0.2 had **0** Russian-script titles across all feeds (Russia bloc was English-export only). v0.4: **170**.

## Sample new-bucket headlines (v0.4 only)

### pakistan
  • Breathe Pakistan: Minister Musadik Malik calls for investing in youth-led climate projects
  • Pakistan's response to any future miscalculation will be more intense, warns Asif in Marka

### ukraine
  • Ukrainian intelligence identifies four perpetrators who raped woman in occupied Luhansk Ob
  • Russian drones hit kindergarten in Sumy, rescue operation underway – video

### germany
  • Dozens killed as Ukraine accuses Russia of breaking unilateral ceasefire
  • Hungary's new government pushes for euro by 2030

### egypt
  • Egypt reaffirms full support for Somalia’s sovereignty
  • Egypt, Turkey discuss cooperation in water management, irrigation modernization

### russia_native
  • Перечислены цели ударов российских войск по Украине за сутки
  • ВСУ выпустили в сторону России сотни беспилотников и управляемые авиабомбы

### spain
  • Primer juicio contra Ábalos, Koldo y Aldama por la trama de las mascarillas, en directo | 
  • Díaz Ayuso lleva su discurso libertario a la universidad de Salinas Pliego

### philippines
  • Thank You, Mom: Celebrate Mom the best way at Robinsons Malls
  • Small businesses in Cebu to benefit Asean’s Digital Economy Framework

### south_africa
  • News24 | Accused Bondi Beach mass killer faces 19 additional charges, but has not pleaded 
  • News24 | Iran foreign minister’s visit to China underlines close ties, ahead of Trump meet

### taiwan_hk
  • State visits are a basic right: president
  • Paraguay’s Pena visit underlines solid ties: MOFA

## Items per declared lang

| Lang | v0.2 items | v0.4 items | Δ |
|---|---|---|---|
| en | 360 | 2822 | +2462 |
| ru | 0 | 170 | +170 |
| es | 0 | 163 | +163 |
| pt | 20 | 100 | +80 |
| de | 0 | 90 | +90 |
| it | 0 | 80 | +80 |
| ar | 10 | 75 | +65 |
| tr | 10 | 50 | +40 |
| hu | 0 | 50 | +50 |
| zh | 10 | 50 | +40 |
| fa | 20 | 50 | +30 |
| hi | 10 | 46 | +36 |
| he | 10 | 30 | +20 |
| fr | 10 | 24 | +14 |
| ja | 7 | 7 | +0 |
| ? | 0 | 0 | +0 |

## Stub-only feeds in v0.4 (9)

- wire_services|Reuters (via Google News) (41/50 stubs)
- china|Global Times (50/50 stubs)
- saudi_arabia|Arab News (via Google News) (40/50 stubs)
- saudi_arabia|Al Arabiya English (via Google News) (40/50 stubs)
- brazil|O Globo (via Google News) (46/50 stubs)
- pakistan|ARY News English (50/50 stubs)
- russia_native|Lenta.ru (50/50 stubs)
- russia_native|RIA Novosti RU (20/20 stubs)
- taiwan_hk|Taipei Times (50/50 stubs)

## Errored feeds in v0.4 (21)
Most are 403 from container IP; expected to work on prod IP.

- wire_services|Le Monde (http=403 err=None)
- wire_services|Le Figaro (http=403 err=None)
- wire_services|Liberation (http=403 err=None)
- uk|The Guardian World (http=403 err=None)
- uk|The Telegraph (http=403 err=None)
- iran_state|Tehran Times (http=503 err=None)
- iran_state|IRNA English (http=503 err=None)
- iran_state|IRNA Farsi (http=503 err=None)
- iran_state|Mehr News English (rsshub) (http=403 err=None)
- iran_state|Kayhan (rsshub) (http=403 err=None)
- india|Times of India (http=403 err=None)
- israel|Times of Israel (http=403 err=None)
- pakistan|Express Tribune (http=403 err=None)
- lebanon|Al-Akhbar Lebanon (http=403 err=None)
- lebanon|LBCI English (http=403 err=None)
- jordan|Jordan Times (http=403 err=None)
- palestine|Maan News English (http=403 err=None)
- palestine|Palestine Chronicle (http=429 err=None)
- russia_native|Novaya Gazeta Europe (http=403 err=None)
- australia_nz|Guardian Australia (http=403 err=None)
- africa_other|Addis Standard Ethiopia (http=403 err=None)