# Hormuz / US-Iran Deal — Cross-Country Framing Correlation

> **Spec, not auto-output.** This is the hand-curated exemplar that the
> automated daily analysis pipeline targets. Real cron-generated analyses
> live in `analyses/<DATE>_<story_key>.md`. Keep this file in sync with
> `.claude/prompts/daily_analysis.md` — together they define what good
> output looks like.

**Story**: Strait of Hormuz / US-Iran one-page memorandum, "Project Freedom" paused
**Date**: 2026-05-06
**Source**: `briefings/2026-05-06_hormuz_iran.json`
**Coverage**: 27 country/region buckets, 41 articles in dedup'd corpus
(66 raw articles before dedup), 35/41 with full body text extraction

---

## TL;DR

The wire framing converged — half the world's buckets ran the same Reuters/Axios
"one-page memo" line. But the **second-order story** each country told was
wildly different. The corpus splits cleanly into three competing narrative arcs
that almost never appear together:

1. **Diplomatic mechanics** — "memo near, deal close" (13 buckets, wire-driven)
2. **Threat / warning** — "Trump threatens much-higher bombing" (9 buckets)
3. **Economic shock** — fuel costs, oil stranded, rate hikes, inflation
   (13 buckets, but each one tells a *local* economic story)

Almost nobody reports on the question the video poses ("who won?"). Only
**2 buckets** carry the explicit "Iran prevailed" frame and only **2 buckets**
carry the "US victory" frame. The rest stay strategically neutral on outcome.

---

## Frame matrix (27 buckets × 9 frames)

```
bucket                 | USvic Iran  Deal  Threat China Oil   IRGC  Nucl  Civ
------------------------------------------------------------------------------
asia_pacific_regional  |   .     .     .     .     .     X     X     .     .
australia_nz           |   .     .     X     X     .     X     X     .     X
belarus_caucasus       |   .     .     .     .     .     X     .     .     .
canada                 |   .     .     X     .     .     X     .     .     X
china                  |   .     .     .     .     X     .     .     .     .
egypt                  |   .     .     X     X     .     .     X     .     .
india                  |   .     .     .     X     .     .     X     .     X
indonesia              |   .     .     X     .     .     .     .     .     .
iran_opposition        |   .     .     X     X     .     .     .     X     X
iraq                   |   .     .     .     .     .     X     .     .     X
israel                 |   .     .     X     .     .     .     .     X     .
italy                  |   .     .     X     .     .     .     .     .     .
japan                  |   .     .     X     .     .     X     .     .     .
kenya                  |   .     .     .     .     .     X     .     .     .
korea_north            |   X     .     .     .     .     X     .     .     .
nordic                 |   .     .     .     .     .     X     .     .     X
opinion_magazines      |   .     .     .     X     .     X     X     .     .
russia                 |   .     .     .     .     .     .     X     .     .
saudi_arabia           |   .     .     X     X     .     X     .     .     .
south_africa           |   .     .     X     X     .     .     X     .     X
south_korea            |   .     .     X     X     .     .     X     .     .
state_tv_intl          |   .     .     .     .     .     .     .     X     .
taiwan_hk              |   .     .     X     .     X     X     .     .     .
turkey                 |   .     .     X     X     .     X     X     .     .
usa                    |   X     .     .     .     .     .     .     .     .
```

**Frame totals across buckets**:

| Frame | # buckets | Note |
|---|---|---|
| OIL_ECON | 13 | Tied for top — the *real* story is the oil shock |
| NEUTRAL_DEAL | 13 | Reuters/Axios wire syndication signature |
| IRAN_STRENGTH | 9 | "IRGC stays / Tehran holds the strait" |
| THREAT | 9 | "Trump warns much higher level" |
| CIVILIAN_COST | 7 | Stranded oil, Lufthansa fuel, ships stuck |
| NUCLEAR | 3 | Israel + iran_opposition + Sputnik (only) |
| CHINA_BROKER | 2 | China + Taiwan/HK (Wang Yi mediator angle) |
| US_VICTORY | 2 | USA (NPR) + North Korea (NK News, ironic) |
| IRAN_VICTORY | 0 | **Nobody at headline level** — only in body text |

The "who won" question that the video drops on the audience is *not present at
the headline level anywhere in the corpus*. It only emerges when you read the
body text of opinion magazines (Foreign Affairs) and Russian state TV (RT).

---

## The three story arcs

### Arc 1 — Diplomatic mechanics (wire-syndicated)
> "The US and Iran are closing in on a one-page memorandum to end the war in
> the Gulf, a source from mediator Pakistan…"

**Carriers**: Japan Times, SMH, CBC, Globe and Mail, Egypt Independent,
Iran International EN, Daily Sabah, Italy (La Rep + Sole 24), Indonesia,
Israel (J-Post), Saudi Arabia, Taipei Times, Middle East Monitor.

This is the Reuters/Axios baseline. Pakistan-as-mediator is the universal
hook. Every wire-dependent outlet leads with this — including Israel and
Iran-opposition, which is editorially surprising.

### Arc 2 — Threat narrative (Trump-as-protagonist)
> "Trump warns of 'much higher level' strikes if Iran refuses deal."

**Carriers**: 9News (AU), Republic World (IN), RFE/RL, Yonhap (KR), Daily
Sabah (TR), Pan-Arab (MEM), South Africa, Saudi.

This frames Trump as the actor with leverage; deal exists only as an
ultimatum precondition. Notice South Korea's Yonhap exclusively chose this
angle — peninsula readers are being told the story of US escalation, not US
diplomacy.

### Arc 3 — Economic shock (downstream effects)
> "Germany's Lufthansa warns of hefty fuel costs… €1.7B higher 2026 bill."
> "Pyongyang gasoline prices surpass Seoul's amid Middle East supply shock."
> "Georgian National Bank raises rate to 8.25% citing Middle East situation."
> "Philippines first to lose grip on Iran-war-stoked inflation."
> "Japan to buy another 20m barrels of UAE oil to bypass Hormuz blockade."
> "Over 40 million barrels of Iraqi oil stuck west of Strait of Hormuz."

**Carriers**: Nordic (Lufthansa), Korea-North (Pyongyang gas), Belarus-Caucasus
(Georgia rates), Asia-Pacific-regional (Philippines inflation, India sea-route
risk), Iraq, Japan, Kenya (US trade gap), Saudi (El-Sisi: Egypt emergency).

Each tells a *different* economic story — local impact dominates over
geopolitics. There is no shared "global oil shock" narrative; instead 13
separate national-impact stories that happen to share a root cause.

---

## Pairwise framing similarity (Jaccard, vocabulary overlap)

```
0.423  australia_nz <> turkey            ← both heavy AP/Reuters consumers
0.297  australia_nz <> south_africa
0.239  australia_nz <> iran_opposition
0.235  iran_opposition <> turkey
0.229  iran_opposition <> south_korea
0.219  japan <> turkey
0.209  south_africa <> turkey
0.209  egypt <> south_africa
0.206  iran_opposition <> south_africa
0.198  iran_opposition <> israel        ← noteworthy alignment
0.191  australia_nz <> japan
0.182  south_korea <> turkey
0.174  south_africa <> south_korea
0.165  australia_nz <> south_korea
0.161  pan_arab <> south_africa
```

**Most isolated buckets** (lowest mean similarity to everyone else):

```
0.007  indonesia              (Bahasa — vocabulary lock-out)
0.010  italy                  (Italian)
0.027  iraq                   (single short article)
0.030  state_tv_intl          (URL-heavy stub extraction)
0.039  china                  (CGTN body extraction degraded to nav menu)
0.039  korea_north            (uniquely local angle)
0.041  philippines            (chose to cover other story altogether)
0.044  asia_pacific_regional  (deep analytical pieces, distinct vocab)
```

Note: **isolation is mostly linguistic, not editorial.** Italian and Bahasa
buckets register as "isolated" because their vocabulary doesn't overlap, not
because their framing is exotic. The genuinely editorially distinct buckets
are **asia_pacific_regional** (Asia Times — strategic analysis, India's
Malacca-vs-Hormuz chokepoint) and **korea_north** (NK News — Pyongyang gas
prices: a 3rd-order effect nobody else picked up).

---

## Bucket-exclusive vocabulary (terms appearing in ONE bucket only)

These are framing fingerprints — words that mark the country's unique angle:

| Bucket | Distinctive terms | What it reveals |
|---|---|---|
| **asia_pacific_regional** | malacca, dependence, southeast | Strategic-analyst frame: dual chokepoints |
| **belarus_caucasus** | refinancing, monetary, geopolitical | Pure economic-impact frame from Georgia |
| **india** | rules, permit, advertisement | "Iran imposes new rules" — Iran-as-aggressor |
| **indonesia** | yang, kesepakatan, selat, damai (peace) | Bahasa — but framing is **deal-as-peace** |
| **iraq** | iraqi, stuck | Self-centered: 40M barrels of *Iraqi* oil trapped |
| **italy** | guerra, accordo, nemico (enemy), uniti | Frames Iran as nemico (enemy) explicitly |
| **korea_north** | pyongyang | Singular: gasoline-price impact in DPRK |
| **nordic** | lufthansa, euros | German airline-as-victim |
| **opinion_magazines** | persia, civilisation, history, emperor | Civilizational frame — totally absent elsewhere |
| **russia** | rick, sanchez | RT pundit-led, not wire-led |
| **saudi_arabia** | sisi, egypt, emergency | **Saudi redirects to Egypt's emergency, not Iran** |
| **state_tv_intl** | sputnik, sputnikglobe, rossiya | Sputnik metadata, plus exclusive HEU angle |
| **usa** | democrats, voters, midterm, competition | Hormuz framed through US domestic politics |

The **saudi_arabia** finding is the most editorially significant: Arab News'
top "Hormuz" article isn't about Iran or the deal at all — it's El-Sisi
declaring an Egyptian "state of near-emergency". Saudi's frame is
"war-is-hurting-Egypt" (a US ally), not "war-is-ending" or "Iran-is-strong".
That is framing-by-redirection.

---

## The Foreign Affairs ↔ RT paradox (still the headline finding)

Two outlets — opposite ideological poles — make **the same analytical claim**
in their body text:

**Foreign Affairs** (`opinion_magazines` bucket), "Iran's New Oil Weapon":
> "Despite a fragile cease-fire between the United States and Iran, the
> global economic crisis sparked by the closure of the Strait of Hormuz
> continues unabated. Dueling blockades have kept 20 percent of the global
> oil supply, 20 percent of the global supply of liquefied natural gas, and
> critical commodities such as helium, aluminum, and urea trapped inside the
> Persian Gulf, unable to reach markets."

**RT** (`russia` bucket), "Mapping Hormuz: RT's Rick Sanchez on strategic edge":
> "Donald Trump has touted 'tremendous military success,' but the reality
> in the Strait contradicts US claims. Tehran still holds the strategic
> edge."

The US foreign-policy establishment magazine and Russian state TV
**independently arrive at the same strategic read**. This is the paradox the
Hormuz video exploits: when FA and RT agree, that's not propaganda
convergence, it's the actual fact pattern showing through both filters.

---

## What's *missing* (silence as data)

Buckets that should have covered this story but their top items pointed
elsewhere:

- **Philippines** — Rappler's lead was about a domestic extortion arrest. The
  Hormuz/Iran story barely registered in Philippine national press despite
  Asia Times naming the Philippines as "first inflation domino". Asia Times
  saw the Philippine economic impact before Philippine outlets did.
- **Kenya** — Standard Kenya's "Hormuz" hit was actually about US trade gap
  widening (no direct Iran framing). African press has the Iran war as
  background not foreground.
- **China** — CGTN's body text extraction yielded only the language picker,
  not analysis. The CGTN headline ("Wang Yi: Blockade not in common
  interests") is the entire signal we got. China's Hormuz commentary lives
  in CGTN content we can't extract via RSS.
- **North Korea (state press)** — KCNA / Rodong Sinmun yielded zero direct
  coverage. NK News (US-based North-Korea-watcher outlet) carried the only
  DPRK-angle story (gas prices).

---

## Most striking single-outlet findings

1. **Foreign Affairs**: civilizational framing ("Iran's New Oil Weapon",
   "Persia") — the only bucket using imperial/civilizational vocabulary.
2. **The Conversation**: "'No fear of roaring lions': Iran has a long history
   of standing firm" — explicitly anti-Trump civilizational pushback,
   academic register.
3. **Sputnik International**: only outlet leading with the "Trump says Iran
   will transfer highly enriched uranium to US" angle. Body text is sparse
   (URL/metadata-heavy extraction) but the headline framing is unique. This
   is the angle most likely to be used inside Iran to undermine the deal as
   capitulation.
4. **Asia Times**: two analytical pieces — India's Malacca-Hormuz dual
   chokepoint risk, and Philippines as the "first Asian inflation domino".
   Most analytically deep coverage in the entire corpus.
5. **NK News**: Pyongyang gasoline prices now exceed Seoul's. Singular
   3rd-order finding nobody else has.
6. **Civil Georgia + OC Media**: Georgian central bank rate hike to 8.25%,
   citing the Middle East situation directly. Smallest country, most direct
   monetary-policy response.
7. **Lufthansa via The Local Germany**: €1.7B higher 2026 fuel bill, prepping
   for shortages. Concrete corporate impact figure unique to this bucket.
8. **Republic World (India)**: "Transit Permit Mandatory To Cross Strait Of
   Hormuz" — frames Iran as imposing maritime regulation, not as victim of
   US aggression. Aligned with India's energy-security perspective.
9. **Yonhap (Korea)**: chose the threat-narrative over the deal-narrative.
   In a peninsula media market under nuclear-DMZ stress, Trump's bombing
   threat is the relevant signal.
10. **Arab News (Saudi)**: redirected entirely to Egypt's economic
    emergency. Coverage-by-deflection.

---

## What this tells us about how to frame the video

The current Hormuz video centers the Foreign Affairs ↔ RT paradox. The
correlation analysis suggests **three complementary angles** that the data
supports just as strongly:

### Angle A — "The same memo, three planets"
Show the wire convergence (13 buckets, identical Pakistan-mediator lead),
then drop into the three arcs (deal / threat / shock). Punchline: every
country wrote the same sentence and meant a different thing.

### Angle B — "The story Saudi Arabia told"
Saudi redirected to Egypt's emergency, not Iran. Iran International (Saudi-
funded opposition) carried the deal news. The asymmetry between official
Saudi state press and Saudi-funded foreign-language press is *itself* the
story.

### Angle C — "Pyongyang vs. Seoul gas prices"
The most surprising data point in the entire corpus is downstream and
mundane: NK News reporting that gas in Pyongyang now costs more than gas in
Seoul because of the Hormuz closure. A 60-second video on "the unexpected
losers of the Iran war" — Lufthansa, Pyongyang drivers, Georgian borrowers,
Iraqi oil traders — would land harder than another "framing of the deal"
piece.

### Angle D — "What Asia Times saw before national press did"
Asia Times' Philippines-as-canary piece pre-empted Philippine domestic
coverage (which was about a domestic extortion arrest). Show how regional
analyst outlets (Asia Times, Foreign Affairs, The Conversation) consistently
see 2nd/3rd-order effects before national press does. The data supports a
recurring "Analysis vs. News" series.

---

## Recap of method

- Source: `briefings/2026-05-06_hormuz_iran.json` (27 buckets, 41 articles
  after dedup, 85% with body text).
- Frame regexes applied to (signal_text + title) per article, OR-aggregated
  to bucket level.
- Pairwise Jaccard on lemmatized terms, stopword-filtered, len>3.
- Bucket-exclusive vocabulary = terms with `df==1` (one bucket only) and
  count >= 3.
- Lead-paragraph analysis = first 200 chars of `signal_text`.
- Frame definitions in this analysis are conservative (regex-based, not LLM
  classification); a Claude-pass on the 41 article bodies surfaces
  finer-grained frames (e.g. "ceasefire-as-victory" vs "ceasefire-as-pause").
  That Claude-pass is now wired into the daily cron via the `analyze` job
  in `.github/workflows/daily.yml` and `.claude/prompts/daily_analysis.md`.

---

**Bottom line**: The wire framing is convergent (13/27 buckets), but the
*editorial* framing fans out into three near-disjoint narrative arcs. The
"who won?" question that the video poses is genuinely unresolved at the
headline level — only Foreign Affairs and RT make explicit "Iran has the
strategic edge" claims, from opposite directions, and both bury that claim
in body text. That paradox is the highest-signal finding the dataset
produces, and it's not visible without body-text extraction.
