"""Phase 8: validate that the v0.4 pipeline materially improved coverage.

Side-by-side: 2026-05-02 (baseline, v0.2 sequential pipeline, 51 feeds)
              vs
              2026-05-06 (v0.4 pipeline, 138 feeds, 8.5x items)

Computes the analytical metrics from earlier work for both snapshots
where applicable, and writes a markdown report of the deltas.

Note: 2026-05-06 doesn't have convergence/similarity (SKIP_EMBED was
set since sentence-transformers isn't installed in this container).
This script focuses on coverage / language / bucket metrics that work
on raw items alone.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent
SNAPS = ROOT / "snapshots"
BASE = ROOT / "baseline"

OLD = json.loads((BASE / "2026-05-02_baseline.json").read_text(encoding="utf-8"))
NEW = json.loads((SNAPS / "2026-05-06.json").read_text(encoding="utf-8"))

def feed_count(s):
    return sum(len(c["feeds"]) for c in s["countries"].values())

def item_count(s):
    return sum(sum(f.get("item_count", 0) for f in c["feeds"]) for c in s["countries"].values())

def buckets(s):
    return list(s["countries"].keys())

def langs(s):
    c = Counter()
    for cv in s["countries"].values():
        for f in cv["feeds"]:
            c[f.get("lang", "?")] += f.get("item_count", 0)
    return c

# Script detection from earlier work
def detect_script(t):
    if not t:
        return "empty"
    if re.search(r"[一-鿿]", t): return "zh/ja-han"
    if re.search(r"[぀-ヿ]", t): return "ja-kana"
    if re.search(r"[؀-ۿ]", t): return "ar/fa"
    if re.search(r"[֐-׿]", t): return "he"
    if re.search(r"[Ѐ-ӿ]", t): return "ru-cyrillic"
    if re.search(r"[ऀ-ॿ]", t): return "hi-deva"
    if re.search(r"[가-힯]", t): return "ko"
    return "latin"

def scripts(s):
    c = Counter()
    for cv in s["countries"].values():
        for f in cv["feeds"]:
            for it in f.get("items", []):
                c[detect_script(it.get("title", ""))] += 1
    return c

def first_items_for(s, bucket_keys):
    out = {}
    for ck in bucket_keys:
        if ck not in s["countries"]:
            continue
        sample = []
        for f in s["countries"][ck]["feeds"][:1]:
            for it in f.get("items", [])[:2]:
                sample.append(f"  • {it['title'][:90]}")
        out[ck] = sample
    return out

# -----------------
md = ["# Before / After — Epistemic Lens v0.2 -> v0.4", ""]
md.append("## Coverage")
md.append("")
md.append(f"| Metric | v0.2 baseline (2026-05-02) | v0.4 (2026-05-06) | Δ |")
md.append(f"|---|---|---|---|")
md.append(f"| Feeds | {feed_count(OLD)} | {feed_count(NEW)} | {feed_count(NEW)-feed_count(OLD):+d} |")
md.append(f"| Items | {item_count(OLD)} | {item_count(NEW)} | {item_count(NEW)-item_count(OLD):+d} ({item_count(NEW)/max(1,item_count(OLD)):.1f}x) |")
md.append(f"| Country buckets | {len(buckets(OLD))} | {len(buckets(NEW))} | +{len(buckets(NEW))-len(buckets(OLD))} |")

old_b = set(buckets(OLD)); new_b = set(buckets(NEW))
added = sorted(new_b - old_b)
removed = sorted(old_b - new_b)
md.append("")
md.append(f"### New buckets ({len(added)})")
md.append("")
md.append(", ".join(added))
if removed:
    md.append(f"\n### Removed buckets")
    md.append(", ".join(removed))

md.append("")
md.append("## Language / script distribution (in titles)")
md.append("")
old_s = scripts(OLD); new_s = scripts(NEW)
md.append(f"| Script | v0.2 | v0.4 | Δ |")
md.append(f"|---|---|---|---|")
all_keys = sorted(set(list(old_s) + list(new_s)), key=lambda k: -new_s.get(k,0))
for k in all_keys:
    o = old_s.get(k, 0); n = new_s.get(k, 0)
    md.append(f"| {k} | {o} | {n} | {n-o:+d} |")

md.append("")
md.append("### Cyrillic content fix")
old_cyr = old_s.get("ru-cyrillic", 0); new_cyr = new_s.get("ru-cyrillic", 0)
md.append(f"v0.2 had **{old_cyr}** Russian-script titles across all feeds (Russia bloc was English-export only). v0.4: **{new_cyr}**.")

md.append("")
md.append("## Sample new-bucket headlines (v0.4 only)")
md.append("")
priority = ["pakistan","ukraine","germany","egypt","russia_native","spain","philippines","south_africa","taiwan_hk"]
samples = first_items_for(NEW, priority)
for b, lines in samples.items():
    md.append(f"### {b}")
    md.extend(lines)
    md.append("")

# Items per language
md.append("## Items per declared lang")
md.append("")
ol = langs(OLD); nl = langs(NEW)
md.append(f"| Lang | v0.2 items | v0.4 items | Δ |")
md.append(f"|---|---|---|---|")
all_l = sorted(set(list(ol) + list(nl)), key=lambda l: -nl.get(l, 0))
for l in all_l:
    o = ol.get(l, 0); n = nl.get(l, 0)
    md.append(f"| {l} | {o} | {n} | {n-o:+d} |")

# Feeds with stub flag (v0.4 only — v0.2 didn't track)
stub_feeds = []
for ck, cv in NEW["countries"].items():
    for f in cv["feeds"]:
        items = f.get("items", [])
        if not items:
            continue
        stubs = sum(1 for i in items if i.get("is_stub"))
        if stubs / len(items) >= 0.8:
            stub_feeds.append(f"{ck}|{f['name']} ({stubs}/{len(items)} stubs)")
md.append("")
md.append(f"## Stub-only feeds in v0.4 ({len(stub_feeds)})")
md.append("")
for s in stub_feeds:
    md.append(f"- {s}")

# Feeds with errors in v0.4
err_feeds = []
for ck, cv in NEW["countries"].items():
    for f in cv["feeds"]:
        if f.get("error") or f.get("http_status") not in (200, None):
            err_feeds.append(f"{ck}|{f['name']} (http={f.get('http_status')} err={f.get('error')})")
md.append("")
md.append(f"## Errored feeds in v0.4 ({len(err_feeds)})")
md.append("Most are 403 from container IP; expected to work on prod IP.")
md.append("")
for e in err_feeds:
    md.append(f"- {e}")

(ROOT / "before_after.md").write_text("\n".join(md))
print(f"Wrote before_after.md ({len(md)} lines)")
print(f"\nKey deltas:")
print(f"  feeds:   {feed_count(OLD):>4} -> {feed_count(NEW):>4}  ({feed_count(NEW)-feed_count(OLD):+d})")
print(f"  items:   {item_count(OLD):>4} -> {item_count(NEW):>4}  ({item_count(NEW)/max(1,item_count(OLD)):.1f}x)")
print(f"  buckets: {len(buckets(OLD)):>4} -> {len(buckets(NEW)):>4}  ({len(buckets(NEW))-len(buckets(OLD)):+d})")
print(f"  cyrillic titles: {old_cyr} -> {new_cyr}")
