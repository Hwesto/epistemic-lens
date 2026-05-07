"""Side-by-side framing comparison on key clusters and a few extra cuts."""
import json
from collections import Counter, defaultdict
from glob import glob
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent
SNAPS = ROOT / "snapshots"

def load_conv():
    out = {}
    for p in sorted(SNAPS.glob("*_convergence.json")):
        out[p.stem[:-12]] = json.loads(p.read_text(encoding="utf-8"))
    return out

conv = load_conv()
DATES = sorted(conv.keys())

# ---------------------------------------------------------------------------
# A. Side-by-side: pick the largest Iran cluster on most recent date and show
#    one headline per country bloc.
# ---------------------------------------------------------------------------
print("=== FRAMING DIVERGENCE: Iran war cluster, 2026-05-02 ===\n")
top = sorted(conv["2026-05-02"], key=lambda c: -c["country_count"])[0]
print(f"Cluster rep: {top['representative_title']}")
print(f"Countries: {top['country_count']}  Articles: {top['article_count']}  sim: {top['mean_similarity']}\n")

by_country = defaultdict(list)
for a in top["articles"]:
    by_country[a["country"]].append(a["title"])
for c in sorted(by_country):
    print(f"-- {c}")
    for t in by_country[c][:3]:
        print(f"   • {t}")
    print()

# ---------------------------------------------------------------------------
# B. Story coverage extremes — which clusters had the WIDEST country span?
# ---------------------------------------------------------------------------
print("\n=== WIDEST COVERAGE STORIES (top 10) ===")
widest = []
for d in DATES:
    for cl in conv[d]:
        widest.append((cl["country_count"], d, cl["representative_title"]))
widest.sort(reverse=True)
seen = set()
shown = 0
for n, d, t in widest:
    key = t[:40]
    if key in seen:
        continue
    seen.add(key)
    print(f"  n={n:>2}  {d}  {t[:90]}")
    shown += 1
    if shown >= 10:
        break

# ---------------------------------------------------------------------------
# C. "Adversary agreement on facts" — clusters where US AND IranState AND Russia
#    AND China AND Israel were all present.
# ---------------------------------------------------------------------------
print("\n=== ADVERSARIAL CONSENSUS: clusters with USA + IranState + Russia + China + Israel ===")
need = {"usa", "iran_state", "russia", "china", "israel"}
for d in DATES:
    for cl in conv[d]:
        cs = set(cl.get("countries_present", []))
        if need.issubset(cs):
            print(f"  {d}  sim={cl['mean_similarity']:.3f}  n={cl['country_count']}  {cl['representative_title'][:80]}")

# ---------------------------------------------------------------------------
# D. "China silence" check — clusters where everyone but China is covering a story
# ---------------------------------------------------------------------------
print("\n=== STORIES WITH MASS COVERAGE BUT CHINA ABSENT (n>=12) ===")
for d in DATES:
    for cl in conv[d]:
        cs = set(cl.get("countries_present", []))
        if len(cs) >= 12 and "china" not in cs:
            print(f"  {d}  n={cl['country_count']}  {cl['representative_title'][:90]}")

# ---------------------------------------------------------------------------
# E. "Russia silence" check
# ---------------------------------------------------------------------------
print("\n=== STORIES WITH MASS COVERAGE BUT RUSSIA ABSENT (n>=12) ===")
for d in DATES:
    for cl in conv[d]:
        cs = set(cl.get("countries_present", []))
        if len(cs) >= 12 and "russia" not in cs:
            print(f"  {d}  n={cl['country_count']}  {cl['representative_title'][:90]}")

# ---------------------------------------------------------------------------
# F. UK silence (surprising — they missed 17/42)
# ---------------------------------------------------------------------------
print("\n=== STORIES WITH MASS COVERAGE BUT UK ABSENT (n>=12, sample 10) ===")
shown = 0
for d in DATES:
    for cl in conv[d]:
        cs = set(cl.get("countries_present", []))
        if len(cs) >= 12 and "uk" not in cs:
            print(f"  {d}  n={cl['country_count']}  {cl['representative_title'][:90]}")
            shown += 1
            if shown >= 10:
                break
    if shown >= 10:
        break

# ---------------------------------------------------------------------------
# G. China-only / Russia-only stories (unique to each bloc)
# ---------------------------------------------------------------------------
print("\n=== CHINA-EXCLUSIVE STORIES (only China among ALL_COUNTRIES) ===")
ALL = {"wire_services","usa","uk","iran_state","iran_opposition","qatar","china",
       "russia","india","israel","turkey","saudi_arabia","south_korea","japan",
       "brazil","nigeria"}
ch_unique = []
for d in DATES:
    for cl in conv[d]:
        cs = set(cl.get("countries_present", [])) & ALL
        if cs == {"china"} and cl["article_count"] >= 3:
            ch_unique.append((d, cl["article_count"], cl["representative_title"]))
for d, n, t in ch_unique[:15]:
    print(f"  {d}  n_arts={n}  {t[:90]}")

print("\n=== IRAN-STATE-EXCLUSIVE STORIES (only IranState) ===")
for d in DATES:
    for cl in conv[d]:
        cs = set(cl.get("countries_present", [])) & ALL
        if cs == {"iran_state"} and cl["article_count"] >= 2:
            print(f"  {d}  n_arts={cl['article_count']}  {cl['representative_title'][:90]}")

print("\n=== RUSSIA-EXCLUSIVE STORIES ===")
for d in DATES:
    for cl in conv[d]:
        cs = set(cl.get("countries_present", [])) & ALL
        if cs == {"russia"} and cl["article_count"] >= 3:
            print(f"  {d}  n_arts={cl['article_count']}  {cl['representative_title'][:90]}")

# ---------------------------------------------------------------------------
# H. Iran framing comparison: state vs opposition on same day
# ---------------------------------------------------------------------------
print("\n=== IRAN STATE vs IRAN OPP — same cluster, different frames (2026-04-25 sample) ===")
for cl in sorted(conv["2026-04-25"], key=lambda c: -c["article_count"]):
    cs = set(cl.get("countries_present", []))
    if "iran_state" in cs and "iran_opposition" in cs:
        print(f"\n  CLUSTER: {cl['representative_title'][:80]}")
        for a in cl["articles"]:
            if a["country"] in ("Iran (State)", "Iran (Opposition / Diaspora)"):
                print(f"    [{a['country'][:14]:<14}] [{a['lang']}] {a['title'][:100]}")
        if cl["article_count"] >= 5:
            break
