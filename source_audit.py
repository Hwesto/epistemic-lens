"""Deep audit of the Epistemic Lens data sources.

Outputs five sections:
  1. Static audit of feeds.json -> regions/languages claimed, coverage gaps
  2. Snapshot-based health: uptime %, avg items, summary-quality signals
  3. Paywall / content-quality heuristics from snapshot summary text
  4. Live HTTP probe of every feed URL (status, bytes, item count, sample)
  5. World-coverage gap analysis (regions / languages / major missing actors)
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import socket
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from urllib.parse import urlparse

import requests
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parent
SNAPS = ROOT / "snapshots"
FEEDS = json.loads((ROOT / "feeds.json").read_text(encoding="utf-8"))

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.8"}

# ---------------------------------------------------------------------------
# 1. Static audit
# ---------------------------------------------------------------------------
print("=" * 78)
print("1. STATIC AUDIT — feeds.json")
print("=" * 78)

countries = FEEDS["countries"]
total_feeds = sum(len(c["feeds"]) for c in countries.values())
langs_claimed = Counter()
status_buckets = Counter()
section_hints = Counter()
for cval in countries.values():
    for f in cval["feeds"]:
        langs_claimed[f["lang"]] += 1
        s = (f.get("status") or "UNKNOWN").upper()
        # bucket
        if "CONFIRMED" in s: status_buckets["CONFIRMED"] += 1
        elif "OK" in s: status_buckets["OK"] += 1
        elif "LIKELY" in s: status_buckets["LIKELY OK"] += 1
        elif "EXPECTED FAIL" in s: status_buckets["EXPECTED FAIL"] += 1
        elif "UNCERTAIN" in s: status_buckets["UNCERTAIN"] += 1
        else: status_buckets["OTHER"] += 1
        # rough section guess from URL path
        path = urlparse(f["url"]).path.lower()
        if "world" in path: section_hints["world"] += 1
        elif "politics" in path: section_hints["politics"] += 1
        elif "international" in path: section_hints["international"] += 1
        elif "news.google.com" in (urlparse(f["url"]).netloc or ""): section_hints["google_news_search"] += 1
        else: section_hints["root/other"] += 1

print(f"Total feeds declared: {total_feeds}")
print(f"Countries declared:  {len(countries)}")
print(f"\nLanguages (per feed-declaration):")
for l, n in langs_claimed.most_common():
    print(f"  {l:<5} {n}")
print(f"\nDeclared status buckets:")
for s, n in status_buckets.most_common():
    print(f"  {s:<16} {n}")
print(f"\nSection hint from URL path:")
for s, n in section_hints.most_common():
    print(f"  {s:<22} {n}")

# ---------------------------------------------------------------------------
# 2. Snapshot-based feed health (39 days)
# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("2. SNAPSHOT HEALTH — uptime & volume across 39 days")
print("=" * 78)

# Match only canonical date-only snapshot files (e.g. 2026-05-09.json).
# Using a positive pattern is more robust than maintaining a denylist of
# every sidecar suffix the pipeline emits.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
dates = sorted(p.stem for p in SNAPS.glob("[0-9]*.json")
               if _DATE_RE.match(p.stem))
raw = {d: json.loads((SNAPS / f"{d}.json").read_text(encoding="utf-8")) for d in dates}

feed_records = defaultdict(list)  # (country_key, feed_name) -> list of dicts per day
for d, snap in raw.items():
    for ckey, cval in snap["countries"].items():
        for f in cval["feeds"]:
            feed_records[(ckey, f["name"])].append({
                "date": d,
                "lang": f.get("lang"),
                "n": f.get("item_count", 0),
                "items": f.get("items", []),
            })

print(f"\n{'feed':<60} {'uptime%':>8} {'avg/day':>8} {'med':>5}")
rows = []
for (ck, fn), recs in feed_records.items():
    n_days = len(recs)
    n_live = sum(1 for r in recs if r["n"] > 0)
    avg = mean(r["n"] for r in recs)
    med = median(r["n"] for r in recs)
    rows.append((n_live / n_days, avg, med, ck, fn))
rows.sort()
for up, avg, med, ck, fn in rows:
    print(f"  {f'{ck} | {fn}':<58} {100*up:>7.1f}% {avg:>8.2f} {med:>5}")

# ---------------------------------------------------------------------------
# 3. Paywall / content-quality heuristics
# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("3. CONTENT-QUALITY SIGNALS (paywall / stub / google-news mediation)")
print("=" * 78)

PAYWALL_PATTERNS = [
    r"subscribe to (read|continue)",
    r"subscribers? only",
    r"sign in to read",
    r"premium content",
    r"this article is for",
    r"register to read",
    r"unlock this article",
    r"to continue reading",
    r"members? only",
]
PW_RE = re.compile("|".join(PAYWALL_PATTERNS), re.I)
GN_HOST = "news.google.com"

print(f"\n{'feed':<60} {'avg_sum_chars':>14} {'pw_hits':>8} {'gn_links%':>10} {'title=summary%':>15}")
qrows = []
for (ck, fn), recs in feed_records.items():
    sum_lens = []
    pw_hits = 0
    gn_links = 0
    n_items = 0
    title_eq_summary = 0
    for r in recs:
        for it in r["items"]:
            n_items += 1
            t = (it.get("title") or "").strip()
            s = (it.get("summary") or "").strip()
            link = it.get("link") or ""
            sum_lens.append(len(s))
            if PW_RE.search(s):
                pw_hits += 1
            if GN_HOST in link:
                gn_links += 1
            # Google News summary often is "Headline&nbsp;&nbsp;Outlet"
            # If the summary, stripped of nbsp/whitespace, equals the title or
            # title + outlet, treat as stub.
            s_clean = re.sub(r"&nbsp;|\s+", " ", s).strip()
            t_clean = re.sub(r"\s+", " ", t).strip()
            if s_clean.startswith(t_clean[:60]) and len(s_clean) - len(t_clean) < 60:
                title_eq_summary += 1
    if n_items == 0:
        continue
    qrows.append((
        mean(sum_lens) if sum_lens else 0,
        100 * pw_hits / n_items,
        100 * gn_links / n_items,
        100 * title_eq_summary / n_items,
        ck, fn, n_items,
    ))

# Sort by content quality: GN-mediated and stub-summary first as red flags
qrows.sort(key=lambda x: (-x[3], -x[2], x[0]))
for avg_sum, pw_pct, gn_pct, eq_pct, ck, fn, n in qrows:
    print(f"  {f'{ck} | {fn}':<58} {avg_sum:>14.1f} {pw_pct:>7.1f}% {gn_pct:>9.1f}% {eq_pct:>14.1f}%")

# ---------------------------------------------------------------------------
# 4. Live HTTP probe
# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("4. LIVE HTTP PROBE (current reachability)")
print("=" * 78)

def probe(name_url):
    name, url = name_url
    out = {"name": name, "url": url, "status": None, "bytes": 0,
           "items": 0, "elapsed": None, "error": None, "ctype": None,
           "sample_title": None}
    t0 = time.time()
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        out["status"] = r.status_code
        out["ctype"] = (r.headers.get("content-type") or "")[:60]
        out["bytes"] = len(r.content)
        # Try to count items (RSS or Atom)
        body = r.content
        if r.status_code == 200 and body:
            try:
                # strip BOM and namespace by lazy approach: count occurrences
                cnt_item = body.lower().count(b"<item")
                cnt_entry = body.lower().count(b"<entry")
                out["items"] = max(cnt_item, cnt_entry)
                # sample title via regex (cheap)
                m = re.search(rb"<title[^>]*>(.*?)</title>", body, re.I | re.S)
                if m:
                    txt = m.group(1).decode("utf-8", "replace")
                    txt = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", txt, flags=re.S)
                    out["sample_title"] = txt.strip()[:80]
            except (UnicodeDecodeError, AttributeError, ValueError) as e:
                out["error"] = f"parse:{e.__class__.__name__}"
    except requests.exceptions.SSLError as e:
        out["error"] = f"SSL:{str(e)[:60]}"
    except requests.exceptions.ConnectionError as e:
        out["error"] = f"CONN:{str(e)[:60]}"
    except requests.exceptions.Timeout:
        out["error"] = "TIMEOUT"
    except (requests.RequestException, ValueError, OSError) as e:
        # Last-resort: covers InvalidURL / MissingSchema / decode errors / etc.
        out["error"] = f"{e.__class__.__name__}:{str(e)[:60]}"
    out["elapsed"] = round(time.time() - t0, 2)
    return out

flat = []
for ckey, cval in countries.items():
    for f in cval["feeds"]:
        flat.append((f"{ckey} | {f['name']}", f["url"]))

print(f"Probing {len(flat)} feeds in parallel (timeout 12s each)...")
results = []
with cf.ThreadPoolExecutor(max_workers=10) as ex:
    for r in ex.map(probe, flat):
        results.append(r)

print(f"\n{'feed':<60} {'st':>4} {'bytes':>7} {'items':>5} {'sec':>5}  notes")
for r in sorted(results, key=lambda x: (x["status"] or 0, -x["items"])):
    note = r["error"] or r["ctype"] or ""
    print(f"  {r['name']:<58} {str(r['status'] or '-'):>4} {r['bytes']:>7} {r['items']:>5} {r['elapsed']:>5}  {note[:50]}")

# Network-disconnected outcomes vs healthy feeds summary
ok = [r for r in results if r["status"] == 200 and r["items"] > 0]
deadhttp = [r for r in results if r["error"] or (r["status"] and r["status"] >= 400)]
empty200 = [r for r in results if r["status"] == 200 and r["items"] == 0]
print(f"\nLive-probe summary: {len(ok)} OK / {len(empty200)} 200-but-empty / {len(deadhttp)} errored")

# ---------------------------------------------------------------------------
# 5. World-coverage gap analysis
# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("5. WORLD-COVERAGE GAPS (regions, languages, major missing actors)")
print("=" * 78)

PRESENT = set(countries.keys())
print("\nPresent country buckets:")
for c in sorted(PRESENT):
    print(f"  + {c}")

# Region taxonomy. PRESENT codes mapped to regions.
REGIONS = {
    "North America": {"present": ["usa"], "missing_major": ["Canada", "Mexico"]},
    "Latin America": {"present": ["brazil"], "missing_major":
        ["Mexico", "Argentina", "Colombia", "Chile", "Venezuela", "Peru"]},
    "Western Europe": {"present": ["uk", "wire_services (FR via AFP)"], "missing_major":
        ["Germany", "France (direct)", "Italy", "Spain", "Netherlands", "Portugal", "Ireland"]},
    "Nordic / Baltic": {"present": [], "missing_major":
        ["Sweden", "Norway", "Finland", "Denmark", "Estonia"]},
    "Eastern Europe": {"present": ["russia (TASS/RT/Meduza/Moscow Times)"], "missing_major":
        ["Ukraine", "Poland", "Hungary", "Romania", "Czechia", "Belarus", "Serbia"]},
    "Caucasus / Central Asia": {"present": [], "missing_major":
        ["Georgia", "Armenia", "Azerbaijan", "Kazakhstan", "Uzbekistan"]},
    "Middle East / N. Africa": {"present":
        ["iran_state", "iran_opposition", "israel", "qatar", "saudi_arabia", "turkey"],
        "missing_major":
        ["Egypt", "UAE (direct)", "Lebanon", "Iraq", "Jordan", "Syria",
         "Morocco", "Tunisia", "Algeria", "Yemen", "Palestine (Wafa, Maan)"]},
    "South Asia": {"present": ["india"], "missing_major":
        ["Pakistan", "Bangladesh", "Sri Lanka", "Nepal", "Afghanistan"]},
    "South-East Asia": {"present": [], "missing_major":
        ["Indonesia", "Malaysia", "Singapore", "Philippines", "Vietnam",
         "Thailand", "Myanmar"]},
    "East Asia": {"present": ["china", "japan", "south_korea"], "missing_major":
        ["Taiwan", "North Korea (KCNA mirrors)", "Hong Kong (independent)", "Mongolia"]},
    "Sub-Saharan Africa": {"present": ["nigeria"], "missing_major":
        ["South Africa", "Kenya", "Ethiopia", "Ghana", "DRC", "Uganda",
         "Senegal", "Tanzania"]},
    "Oceania": {"present": [], "missing_major":
        ["Australia", "New Zealand", "Papua New Guinea", "Fiji"]},
}
print("\nRegion-by-region coverage:")
for region, data in REGIONS.items():
    p = ", ".join(data["present"]) if data["present"] else "(none)"
    print(f"\n  {region}")
    print(f"    PRESENT : {p}")
    print(f"    MISSING : {', '.join(data['missing_major'])}")

# Languages actually emitted in raw items vs claimed
print("\n\nLanguage usage — claimed vs observed-in-titles:")
claimed = Counter()
for cval in countries.values():
    for f in cval["feeds"]:
        claimed[f["lang"]] += 1

observed_titles = Counter()
def detect_script(s):
    """Cheap script bucket detector."""
    if not s:
        return "empty"
    if re.search(r"[一-鿿]", s): return "zh/ja-han"
    if re.search(r"[぀-ヿ]", s): return "ja-kana"
    if re.search(r"[؀-ۿ]", s): return "ar/fa"
    if re.search(r"[֐-׿]", s): return "he"
    if re.search(r"[Ѐ-ӿ]", s): return "ru-cyrillic"
    if re.search(r"[ऀ-ॿ]", s): return "hi-deva"
    if re.search(r"[가-힯]", s): return "ko"
    if re.search(r"[ğşıİçöü]", s.lower()): return "tr-extlatin"
    if re.search(r"[áéíóúãâêç]", s.lower()): return "pt/es-extlatin"
    return "latin"

for d in dates:
    for cval in raw[d]["countries"].values():
        for f in cval["feeds"]:
            for it in f.get("items", []):
                t = it.get("title") or ""
                observed_titles[detect_script(t)] += 1

print(f"\n  CLAIMED langs: {dict(claimed)}")
print(f"\n  OBSERVED title scripts (across ALL items, ALL days):")
for k, n in observed_titles.most_common():
    print(f"    {k:<18} {n}")

print("\nLanguages observed in titles but not declared in feeds.json (per claimed):")
declared_langs = {k.lower() for k in claimed}
observed_langs = {k.lower() for k in observed_titles}
for missing in sorted(observed_langs - declared_langs):
    if missing in {"latin", "other"}:
        continue
    print(f"  - {missing}: {observed_titles.get(missing, 0)} title(s)")

# ---------------------------------------------------------------------------
# 6. Story-relevant gap analysis
# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("6. STORY-RELEVANT GAPS — for the dominant narratives in this dataset")
print("=" * 78)
print("""
Iran-war narrative (the 39-day dominant story) is missing:
  - Pakistan (negotiation venue!)  Dawn / Geo / ARY / Express Tribune
  - Lebanon (active war zone)      L'Orient-Le Jour / Daily Star / Al-Akhbar
  - Iraq (war zone / IRGC routes)  Rudaw / Al-Sumaria / Shafaq
  - UAE (direct)                   The National / Khaleej Times / Gulf News
  - Egypt (largest Arabic market)  Al Ahram / Al Masry Al Youm / Mada Masr
  - Yemen (Houthi axis)            Al Masirah / Saba / Yemen Online
  - Jordan                         Jordan Times / Roya News
  - Syria (regime + opposition)    SANA / Enab Baladi
  - Palestinian voice              Wafa / Ma'an

Russia–Ukraine war (Russia-only stories appear) is missing:
  - Ukrainian voice                Kyiv Independent / Ukrainska Pravda / Pravda EN

China–Taiwan / South China Sea is missing:
  - Taiwanese voice                Taipei Times / Focus Taiwan
  - Filipino voice                 Inquirer / Rappler

Korea peninsula stories: present but narrow — no NK content (KCNA mirrors).
African coverage essentially absent — only Nigeria.
""")

# Persist a machine-readable summary too
out = {
    "scan_date": time.strftime("%Y-%m-%d"),
    "total_feeds": total_feeds,
    "snapshot_health": [
        {"key": f"{ck} | {fn}", "uptime_pct": round(100*up, 1),
         "avg_per_day": round(avg, 2), "median_per_day": med}
        for up, avg, med, ck, fn in rows
    ],
    "live_probe": [
        {"name": r["name"], "status": r["status"], "items": r["items"],
         "bytes": r["bytes"], "error": r["error"], "elapsed_s": r["elapsed"]}
        for r in results
    ],
}
(ROOT / "source_audit.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
print(f"\nWrote machine-readable audit to source_audit.json")
