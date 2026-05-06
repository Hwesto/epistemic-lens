"""Analyze the fresh v0.4 138-feed pull (no embeddings — token + heuristic).

Without sentence-transformers we can't do cross-language clustering, but we
can still do:
  1. Per-bucket volume + language distribution
  2. Top stories per region (sampled)
  3. Cross-bucket story discovery via shared 4-gram token sets in headlines
  4. Framing-keyword fingerprints by country (the propaganda lexicon)
  5. Silence audit on the most-covered stories
  6. New-bucket-specific samples (what Pakistan/Ukraine/Russia-native cover)
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
SNAP = ROOT / "fresh_pull" / "2026-05-06.json"
data = json.loads(SNAP.read_text(encoding="utf-8"))
print(f"Analyzing fresh pull: {data['date']} (config v{data.get('config_version')})")
print(f"  {sum(len(c['feeds']) for c in data['countries'].values())} feeds across "
      f"{len(data['countries'])} buckets, "
      f"{sum(sum(f.get('item_count',0) for f in c['feeds']) for c in data['countries'].values())} items")
print()

# ---------------------------------------------------------------------------
# 1. Per-bucket volume + language distribution
# ---------------------------------------------------------------------------
def detect_script(t):
    if not t: return "empty"
    if re.search(r"[一-鿿]", t): return "zh-han"
    if re.search(r"[぀-ヿ]", t): return "ja-kana"
    if re.search(r"[؀-ۿ]", t): return "ar/fa"
    if re.search(r"[֐-׿]", t): return "he"
    if re.search(r"[Ѐ-ӿ]", t): return "ru"
    if re.search(r"[ऀ-ॿ]", t): return "hi"
    if re.search(r"[가-힯]", t): return "ko"
    if re.search(r"[ğşıİçöü]", t.lower()): return "tr"
    if re.search(r"[áéíóúãâêç]", t.lower()): return "es/pt"
    return "latin"

bucket_volume = []
bucket_scripts = defaultdict(Counter)
for ck, cv in data["countries"].items():
    n_items = sum(f.get("item_count", 0) for f in cv["feeds"])
    bucket_volume.append((n_items, ck))
    for f in cv["feeds"]:
        for it in f.get("items", []):
            bucket_scripts[ck][detect_script(it.get("title", ""))] += 1
bucket_volume.sort(reverse=True)

print("=== BUCKET VOLUME (fresh pull) ===")
for n, ck in bucket_volume[:20]:
    scripts = bucket_scripts[ck].most_common(3)
    sc = " ".join(f"{s}={c}" for s, c in scripts)
    print(f"  {ck:<22} {n:>4}  scripts: {sc}")

# ---------------------------------------------------------------------------
# 2. Cross-bucket story discovery via shared 4-gram tokens
#    For each English headline, take its non-stopword 4+-letter tokens, build
#    a signature, find signatures that appear across multiple buckets.
# ---------------------------------------------------------------------------
STOP = {
    "the","says","that","with","from","this","their","have","after","over","into",
    "about","amid","what","when","where","warns","could","would","will","more","than",
    "they","while","your","been","year","just","also","like","does","other","than",
    "should","could","first","last","under","since","because","still","being","into",
    "made","many","most","says","told","tell","said","gets","comes","came","took",
    "here","much","make","makes","time","times","week","year","years","plan","plans",
    "report","reports","new","old","says",
}
def headline_tokens(title):
    title = title.lower()
    title = re.sub(r"[^a-z0-9 ]", " ", title)
    toks = [t for t in title.split() if len(t) >= 4 and t not in STOP]
    return toks

# Build (frozenset of tokens) -> [(bucket, feed, title)]
sig_groups = defaultdict(list)
all_items = []
for ck, cv in data["countries"].items():
    for f in cv["feeds"]:
        for it in f.get("items", []):
            t = it.get("title", "")
            toks = headline_tokens(t)
            if len(toks) >= 3:
                # Use top-3 most distinctive tokens (alphabetical for stability)
                sig = frozenset(sorted(toks)[:6])  # first 6 by lex order
                sig_groups[sig].append((ck, f["name"], t))
                all_items.append((ck, t, toks))

# Approximate cross-coverage: any cluster where ≥3 buckets share ≥3 token overlap
print("\n=== CROSS-BUCKET STORY MATCHES (>=4 buckets, >=4 articles) ===")
# Better approach: pairwise grep — for each long token (5+ chars, distinctive),
# count buckets that have ≥1 article using it.
token_to_buckets = defaultdict(set)
token_to_titles = defaultdict(list)
for ck, t, toks in all_items:
    for tok in toks:
        if len(tok) >= 5:
            token_to_buckets[tok].add(ck)
            token_to_titles[tok].append((ck, t[:100]))

# Find "story tokens" — distinctive proper-noun-like tokens covered by many buckets
story_tokens = sorted(token_to_buckets.items(), key=lambda x: -len(x[1]))
shown = 0
for tok, bs in story_tokens:
    if len(bs) >= 12:
        sample = token_to_titles[tok]
        # Pick distinct buckets to show
        seen_b = set()
        picks = []
        for ck, t in sample:
            if ck not in seen_b:
                seen_b.add(ck)
                picks.append((ck, t))
            if len(picks) >= 3:
                break
        print(f"\n  '{tok}' — {len(bs)} buckets, {len(token_to_titles[tok])} headlines")
        for ck, t in picks:
            print(f"    [{ck:<14}] {t}")
        shown += 1
        if shown >= 12:
            break

# ---------------------------------------------------------------------------
# 3. Framing keyword fingerprints (extended from previous analysis)
# ---------------------------------------------------------------------------
LEX = {
    "regime":      r"\bregime\b",
    "occupation":  r"\b(occupier|occupation|occupied)\b",
    "aggression":  r"\baggress(ion|ive|or)\b",
    "terrorist":   r"\bterrorist[s]?\b",
    "martyr":      r"\bmartyr",
    "Zionist":     r"\bzionist",
    "ceasefire":   r"\bcease[- ]?fire\b|\btruce\b",
    "genocide":    r"\bgenocid",
    "resistance":  r"\bresistance\b",
    "sanction":    r"\bsanction",
    "negotiation": r"\bnegotiat",
    "war_crime":   r"\bwar crim",
    "proxy":       r"\bproxy\b|\bproxies\b",
    "operation":   r"\b(operation|special operation)\b",
    "liberation":  r"\bliberat",
    "blockade":    r"\bblockade",
    "strike":      r"\bstrik(e|es|ing)\b",
}

lex_counts = defaultdict(Counter)
total_per = Counter()
for ck, cv in data["countries"].items():
    for f in cv["feeds"]:
        for it in f.get("items", []):
            title = (it.get("title") or "").lower()
            total_per[ck] += 1
            for label, pat in LEX.items():
                if re.search(pat, title):
                    lex_counts[ck][label] += 1

print("\n\n=== FRAMING KEYWORDS — per 1000 headlines (top 8 keywords across new buckets) ===")
KEYS = ["regime","ceasefire","strike","sanction","blockade","aggression","terrorist","martyr"]
header = "  " + f"{'bucket':<22}" + "  ".join(f"{k:>10}" for k in KEYS)
print(header)
focus = ["pakistan","ukraine","egypt","russia_native","russia","iran_state","iran_opposition",
         "israel","saudi_arabia","qatar","usa","uk","wire_services","germany","china","india",
         "lebanon","syria","palestine"]
for ck in focus:
    if ck not in total_per: continue
    n = max(1, total_per[ck])
    cells = [f"{1000*lex_counts[ck][k]/n:.1f}" for k in KEYS]
    print(f"  {ck:<22}" + "  ".join(f"{c:>10}" for c in cells))

# ---------------------------------------------------------------------------
# 4. New-bucket spotlights — what's actually being covered
# ---------------------------------------------------------------------------
print("\n\n=== NEW BUCKET SPOTLIGHTS ===")
spot = ["pakistan","ukraine","egypt","russia_native","germany","spain","philippines","south_africa","taiwan_hk"]
for ck in spot:
    if ck not in data["countries"]: continue
    print(f"\n--- {ck}")
    for f in data["countries"][ck]["feeds"][:2]:
        if not f.get("items"): continue
        print(f"  {f['name']} ({f['lang']}, {f['item_count']} items):")
        for it in f["items"][:3]:
            t = it["title"][:100]
            print(f"    • {t}")

# ---------------------------------------------------------------------------
# 5. Silence audit — for the top story tokens, who's NOT covering them?
# ---------------------------------------------------------------------------
print("\n\n=== SILENCE AUDIT — top 5 story tokens, missing buckets ===")
ALL_BUCKETS = set(data["countries"].keys())
for tok, bs in story_tokens[:5]:
    missing = sorted(ALL_BUCKETS - bs)
    print(f"\n  '{tok}' covered by {len(bs)} buckets; MISSING from: {', '.join(missing[:15])}{'...' if len(missing)>15 else ''}")

# ---------------------------------------------------------------------------
# 6. Russia-native vs Russia-export — same outlets covering same story?
# ---------------------------------------------------------------------------
print("\n\n=== RUSSIA — native (RU) vs export (EN) headline contrast ===")
ru_native_titles = []
ru_export_titles = []
for f in data["countries"].get("russia_native", {}).get("feeds", []):
    for it in f.get("items", []):
        ru_native_titles.append((f["name"], it["title"]))
for f in data["countries"].get("russia", {}).get("feeds", []):
    for it in f.get("items", []):
        ru_export_titles.append((f["name"], it["title"]))

print(f"  russia_native (RU/exiled-RU): {len(ru_native_titles)} items")
print(f"  russia (English-export+exiled-EN): {len(ru_export_titles)} items")
print()
print("  Sample russia_native (Cyrillic):")
for fn, t in ru_native_titles[:5]:
    print(f"    [{fn:<22}] {t[:90]}")
print()
print("  Sample russia (English):")
for fn, t in ru_export_titles[:5]:
    print(f"    [{fn:<22}] {t[:90]}")
