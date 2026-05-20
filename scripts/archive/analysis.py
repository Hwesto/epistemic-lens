"""Hyper-analysis of 39 days of cross-national news snapshots.

Aggregates convergence + similarity files across the snapshots/ directory
and produces a findings report covering: country co-presence, silence
audits, bloc cohesion, convergence-vs-spin topics, topic persistence,
feed volume timelines, framing-keyword fingerprints, and bloc defections.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from glob import glob
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).parent
SNAPS = ROOT / "snapshots"

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load_all():
    raw, conv, sim = {}, {}, {}
    for p in sorted(SNAPS.glob("*.json")):
        name = p.stem
        if name.endswith("_convergence"):
            conv[name[:-12]] = json.loads(p.read_text(encoding="utf-8"))
        elif name.endswith("_similarity"):
            sim[name[:-11]] = json.loads(p.read_text(encoding="utf-8"))
        else:
            raw[name] = json.loads(p.read_text(encoding="utf-8"))
    return raw, conv, sim

raw, conv, sim = load_all()
DATES = sorted(conv.keys())
print(f"Loaded {len(DATES)} days: {DATES[0]} -> {DATES[-1]}")
print(f"  raw: {len(raw)}  conv: {len(conv)}  sim: {len(sim)}")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
COUNTRY_LABEL = {
    "wire_services": "Wire",
    "usa": "USA", "uk": "UK", "iran_state": "IranState",
    "iran_opposition": "IranOpp", "qatar": "Qatar", "china": "China",
    "russia": "Russia", "india": "India", "israel": "Israel",
    "turkey": "Turkey", "saudi_arabia": "Saudi", "south_korea": "SKorea",
    "japan": "Japan", "brazil": "Brazil", "nigeria": "Nigeria",
}
ALL_COUNTRIES = list(COUNTRY_LABEL.keys())

BLOCS = {
    "Western": ["usa", "uk", "wire_services"],
    "ChinaRussia": ["china", "russia"],
    "IranAxis": ["iran_state"],
    "IranDiaspora": ["iran_opposition"],
    "SunniArab": ["saudi_arabia", "qatar"],  # both Sunni Arab but rivals
    "Israel": ["israel"],
    "GlobalSouth": ["india", "brazil", "nigeria"],
    "EastAsia": ["japan", "south_korea"],
    "Turkey": ["turkey"],
}

def cluster_countries(c):
    return set(c.get("countries_present", []))

def cluster_feeds(c):
    return set(c.get("feeds_present", []))

# ---------------------------------------------------------------------------
# 1. Country co-presence matrix
# ---------------------------------------------------------------------------
co_pair = Counter()      # (a,b) sorted -> count of clusters where both present
country_appearances = Counter()
total_clusters = 0
for d in DATES:
    for cl in conv[d]:
        cs = cluster_countries(cl)
        cs &= set(ALL_COUNTRIES)
        total_clusters += 1
        for c in cs:
            country_appearances[c] += 1
        cs_l = sorted(cs)
        for i, a in enumerate(cs_l):
            for b in cs_l[i+1:]:
                co_pair[(a, b)] += 1

# Jaccard-style affinity per pair
def jaccard(a, b):
    inter = co_pair[tuple(sorted((a, b)))]
    union = country_appearances[a] + country_appearances[b] - inter
    return inter / union if union else 0.0

print("\n=== COUNTRY CO-COVERAGE (Jaccard, top 20) ===")
pairs = []
for i, a in enumerate(ALL_COUNTRIES):
    for b in ALL_COUNTRIES[i+1:]:
        pairs.append((jaccard(a, b), a, b))
pairs.sort(reverse=True)
for j, a, b in pairs[:20]:
    print(f"  {COUNTRY_LABEL[a]:<10} <-> {COUNTRY_LABEL[b]:<10}  J={j:.3f}  co={co_pair[tuple(sorted((a,b)))]}")

print("\n=== LEAST-LINKED PAIRS (bottom 10, ignoring rare countries) ===")
for j, a, b in pairs[-10:]:
    print(f"  {COUNTRY_LABEL[a]:<10} <-> {COUNTRY_LABEL[b]:<10}  J={j:.3f}  co={co_pair[tuple(sorted((a,b)))]}")

# ---------------------------------------------------------------------------
# 2. Silence audit — large stories (>=10 countries) each country missed
# ---------------------------------------------------------------------------
big_stories = []
for d in DATES:
    for cl in conv[d]:
        cs = cluster_countries(cl) & set(ALL_COUNTRIES)
        if len(cs) >= 10:
            big_stories.append((d, cl["representative_title"], cs))

print(f"\n=== SILENCE AUDIT: {len(big_stories)} stories with >=10 countries ===")
silence = Counter()
for _, _, cs in big_stories:
    for c in ALL_COUNTRIES:
        if c not in cs:
            silence[c] += 1
print("Big-story absences (lower = more universally engaged):")
for c, n in silence.most_common():
    pct = 100 * n / max(1, len(big_stories))
    print(f"  {COUNTRY_LABEL[c]:<10} missed {n:>3}/{len(big_stories)}  ({pct:5.1f}%)")

# ---------------------------------------------------------------------------
# 3. Bloc cohesion via averaged similarity matrix
# ---------------------------------------------------------------------------
def country_of_feed(label):
    return label.split(" | ", 1)[0]

avg_sim = defaultdict(list)
for d, S in sim.items():
    feeds = S["feeds"]
    M = S["matrix"]
    for i, fa in enumerate(feeds):
        for j, fb in enumerate(feeds):
            if i >= j:
                continue
            avg_sim[(fa, fb)].append(M[i][j])

mean_sim = {k: mean(v) for k, v in avg_sim.items()}

# Country-level mean similarity (averaging all feed pairs across the country pair)
def country_pair_avg(ca_label, cb_label):
    vals = []
    for (fa, fb), m in mean_sim.items():
        a_c = country_of_feed(fa)
        b_c = country_of_feed(fb)
        if {a_c, b_c} == {ca_label, cb_label} and a_c != b_c:
            vals.append(m)
    return mean(vals) if vals else None

LABEL_TO_DISPLAY = {
    "Wire Services (Factual Baseline)": "Wire",
    "United States": "USA", "United Kingdom": "UK",
    "Iran (State)": "IranState", "Iran (Opposition / Diaspora)": "IranOpp",
    "Qatar": "Qatar", "China": "China", "Russia": "Russia", "India": "India",
    "Israel": "Israel", "Turkey": "Turkey", "Saudi Arabia": "Saudi",
    "South Korea": "SKorea", "Japan": "Japan", "Brazil": "Brazil",
    "Nigeria": "Nigeria",
}
display_countries = list(LABEL_TO_DISPLAY.keys())

print("\n=== AVG EMBEDDING SIMILARITY between country pairs (top 15) ===")
ssim_rows = []
for i, a in enumerate(display_countries):
    for b in display_countries[i+1:]:
        v = country_pair_avg(a, b)
        if v is not None:
            ssim_rows.append((v, a, b))
ssim_rows.sort(reverse=True)
for v, a, b in ssim_rows[:15]:
    print(f"  {LABEL_TO_DISPLAY[a]:<10} <-> {LABEL_TO_DISPLAY[b]:<10}  sim={v:.3f}")

print("\n=== LOWEST AVG SIMILARITY (bottom 15) ===")
for v, a, b in ssim_rows[-15:]:
    print(f"  {LABEL_TO_DISPLAY[a]:<10} <-> {LABEL_TO_DISPLAY[b]:<10}  sim={v:.3f}")

# Within-country (intra) cohesion
intra = defaultdict(list)
for (fa, fb), m in mean_sim.items():
    a_c = country_of_feed(fa)
    b_c = country_of_feed(fb)
    if a_c == b_c:
        intra[a_c].append(m)

print("\n=== INTRA-COUNTRY COHESION (do their own outlets agree?) ===")
for c, vs in sorted(intra.items(), key=lambda x: -mean(x[1])):
    print(f"  {LABEL_TO_DISPLAY.get(c, c):<10} avg={mean(vs):.3f}  n_pairs={len(vs)}")

# ---------------------------------------------------------------------------
# 4. Convergence (likely fact) vs divergence (spin) topics
# ---------------------------------------------------------------------------
print("\n=== HIGH-CONVERGENCE STORIES (>=10 countries, top mean_similarity) ===")
high_conv = []
for d in DATES:
    for cl in conv[d]:
        if len(cluster_countries(cl) & set(ALL_COUNTRIES)) >= 10:
            high_conv.append((cl["mean_similarity"], d, cl["representative_title"], len(cluster_countries(cl))))
high_conv.sort(reverse=True)
for s, d, t, n in high_conv[:15]:
    print(f"  {d}  sim={s:.3f}  n={n:>2}  {t[:90]}")

print("\n=== LOW-CONVERGENCE (spin) STORIES (>=10 countries, lowest mean_similarity) ===")
for s, d, t, n in sorted(high_conv)[:15]:
    print(f"  {d}  sim={s:.3f}  n={n:>2}  {t[:90]}")

# ---------------------------------------------------------------------------
# 5. Topic persistence — track keyword runs over time
# ---------------------------------------------------------------------------
def normalize_title(t):
    t = re.sub(r"\s+", " ", t.lower())
    return re.sub(r"[^a-z0-9 ]", "", t)

# extract long-running themes by representative-title token frequency over days
day_themes = defaultdict(set)
for d in DATES:
    for cl in conv[d]:
        if len(cluster_countries(cl) & set(ALL_COUNTRIES)) >= 8:
            for tok in normalize_title(cl["representative_title"]).split():
                if len(tok) > 3:
                    day_themes[tok].add(d)

print("\n=== LONGEST-RUNNING THEMES (token in >=8-country stories, by # of days) ===")
runs = sorted(day_themes.items(), key=lambda x: -len(x[1]))
stop = {"says", "with", "that", "from", "this", "their", "have", "after", "over",
        "into", "about", "amid", "what", "when", "where", "warns", "could", "would",
        "will", "more", "than", "they", "while", "amid", "your", "been", "year"}
shown = 0
for tok, ds in runs:
    if tok in stop:
        continue
    print(f"  {tok:<18} {len(ds):>3} days")
    shown += 1
    if shown >= 25:
        break

# ---------------------------------------------------------------------------
# 6. Feed volume timeline — outages, surges
# ---------------------------------------------------------------------------
feed_counts = defaultdict(dict)  # feed -> date -> count
for d in DATES:
    for ckey, cval in raw[d]["countries"].items():
        for f in cval["feeds"]:
            feed_counts[f"{ckey} | {f['name']}"][d] = f.get("item_count", 0)

print("\n=== FEED HEALTH: feeds with most zero-count days ===")
zeros = []
for f, by_day in feed_counts.items():
    z = sum(1 for d in DATES if by_day.get(d, 0) == 0)
    zeros.append((z, len(by_day), f))
zeros.sort(reverse=True)
for z, n, f in zeros[:20]:
    print(f"  {f:<55} dead {z:>3}/{n} days")

print("\n=== TOP-VOLUME FEEDS (avg articles/day) ===")
vol = []
for f, by_day in feed_counts.items():
    if by_day:
        vol.append((mean(by_day.values()), f))
vol.sort(reverse=True)
for v, f in vol[:15]:
    print(f"  {f:<55} {v:.1f} avg/day")

# ---------------------------------------------------------------------------
# 7. Framing keywords by country — propaganda lexicon fingerprints
# ---------------------------------------------------------------------------
LEX = {
    "regime":      r"\bregime\b",
    "occupation":  r"\b(occupier|occupation|occupied)\b",
    "aggression":  r"\baggress(ion|ive|or)\b",
    "terrorist":   r"\bterrorist[s]?\b",
    "martyr":      r"\bmartyr",
    "Zionist":     r"\bzionist",
    "imperialist": r"\bimperial",
    "ceasefire":   r"\bcease[- ]?fire\b|\btruce\b",
    "genocide":    r"\bgenocid",
    "resistance":  r"\bresistance\b",
    "sanction":    r"\bsanction",
    "negotiation": r"\bnegotiat",
    "war_crime":   r"\bwar crim",
    "proxy":       r"\bproxy\b|\bproxies\b",
    "operation":   r"\b(operation|special operation)\b",
    "liberation":  r"\bliberat",
}

# Iterate raw articles and tally by country
lex_counts = defaultdict(Counter)
total_titles_per_country = Counter()
for d in DATES:
    for ckey, cval in raw[d]["countries"].items():
        for f in cval["feeds"]:
            for it in f.get("items", []):
                title = (it.get("title") or "").lower()
                total_titles_per_country[ckey] += 1
                for label, pat in LEX.items():
                    if re.search(pat, title):
                        lex_counts[ckey][label] += 1

print("\n=== FRAMING KEYWORDS — uses per 1000 headlines by country ===")
header = ["country"] + list(LEX.keys())
print("  " + " ".join(f"{h[:10]:>10}" for h in header))
for c in ALL_COUNTRIES:
    n = max(1, total_titles_per_country[c])
    row = [COUNTRY_LABEL[c]] + [
        f"{1000 * lex_counts[c][k] / n:.1f}" for k in LEX
    ]
    print("  " + " ".join(f"{v[:10]:>10}" for v in row))

# ---------------------------------------------------------------------------
# 8. Iran blackout effect — feed health for Iran state vs opposition over time
# ---------------------------------------------------------------------------
print("\n=== IRAN STATE vs OPPOSITION volume over time (totals/day) ===")
print(f"  {'date':<12} {'IranState':>10} {'IranOpp':>10}")
for d in DATES[::3]:  # every 3rd day to fit
    s = sum(f.get("item_count", 0) for f in raw[d]["countries"]["iran_state"]["feeds"])
    o = sum(f.get("item_count", 0) for f in raw[d]["countries"]["iran_opposition"]["feeds"])
    print(f"  {d}   {s:>10} {o:>10}")

# ---------------------------------------------------------------------------
# 9. Defector days — country breaks from its bloc
# ---------------------------------------------------------------------------
# For each day, compute each feed's avg sim within own country vs cross-country.
# Flag feeds where cross-country sim > intra-country sim by a margin (defector).
print("\n=== POSSIBLE DEFECTOR DAYS (feed week mean closer to OUTSIDE bloc than own) ===")
defectors = []
for d, S in sim.items():
    feeds = S["feeds"]
    M = S["matrix"]
    for i, fa in enumerate(feeds):
        ca = country_of_feed(fa)
        intra_v, cross_best = [], (-1.0, None)
        for j, fb in enumerate(feeds):
            if i == j:
                continue
            cb = country_of_feed(fb)
            v = M[i][j]
            if ca == cb:
                intra_v.append(v)
            else:
                if v > cross_best[0]:
                    cross_best = (v, fb)
        if intra_v and cross_best[1]:
            iv = mean(intra_v)
            if cross_best[0] - iv > 0.15:
                defectors.append((cross_best[0] - iv, d, fa, cross_best[1], iv, cross_best[0]))
defectors.sort(reverse=True)
for diff, d, fa, fb, iv, cv in defectors[:15]:
    print(f"  {d} {fa[:40]:<40} -> {fb[:40]:<40}  intra={iv:.2f} cross={cv:.2f}  Δ={diff:.2f}")

# ---------------------------------------------------------------------------
# 10. Iran-war cluster evolution
# ---------------------------------------------------------------------------
print("\n=== IRAN-WAR THEME PRESENCE PER DAY (countries covering 'Iran' top cluster) ===")
print(f"  {'date':<12} {'top_cl_n':>8} {'iran_in_top3':>14}")
for d in DATES:
    top = sorted(conv[d], key=lambda c: -c["article_count"])[:3]
    iran_in_top3 = any("iran" in c["representative_title"].lower() for c in top)
    largest_n = max((c["country_count"] for c in conv[d]), default=0)
    print(f"  {d}   {largest_n:>8} {('YES' if iran_in_top3 else '-'):>14}")
