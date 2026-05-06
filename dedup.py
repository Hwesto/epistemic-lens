"""Phase 6: deduplication layer.

Two-stage dedup applied to a snapshot AFTER fetch but BEFORE embedding:

  1. URL canonicalisation — strip utm_*/ref/share params, www., m./mobile.
     prefixes, trailing slashes, fragment IDs. Identical canonical URL
     across feeds collapses into one canonical item with multi-source
     attribution.
  2. Title near-dup — normalise title (lowercase, strip punctuation,
     collapse whitespace, drop common boilerplate suffixes like " - Reuters")
     and collapse identical normalised titles into one record with multi-
     source attribution.

Dedup is intra-day (same snapshot only) and preserves which feeds carried
each item. The dedup'd snapshot is what feeds embedding/clustering. The
raw items remain in the original snapshot file for audit.

Usage:
  python3 dedup.py                       # run on latest snapshot
  python3 dedup.py snapshots/YYYY-MM-DD.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ROOT = Path(__file__).parent
SNAPS = ROOT / "snapshots"

# -- URL canonicalisation ----------------------------------------------------
TRACKING_PREFIXES = ("utm_", "ref", "fbclid", "gclid", "mc_cid", "mc_eid",
                     "share", "ito", "icid", "cid", "ncid", "smid", "src")

def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
    except Exception:
        return url
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc.startswith("m.") or netloc.startswith("mobile."):
        netloc = netloc.split(".", 1)[1]
    # Google News redirect URLs are unique per consumer — strip query
    if netloc.startswith("news.google.com"):
        # the path encodes article id; keep that, drop query
        p = p._replace(query="", fragment="")
        return urlunparse(p)
    # Drop tracking query params
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not any(k.lower().startswith(pref) for pref in TRACKING_PREFIXES)]
    new_query = urlencode(q)
    path = p.path
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    return urlunparse(p._replace(netloc=netloc, path=path, query=new_query, fragment=""))

# -- Title normalisation -----------------------------------------------------
# Common boilerplate suffix patterns: " - Reuters", " | CNN", " — BBC News"
SUFFIX_RE = re.compile(r"\s*[-|—–]\s*[A-Z][\w &.'/]{1,30}\s*$")

def normalise_title(title: str) -> str:
    t = (title or "").strip()
    # Strip trailing outlet attribution (one or two iterations)
    for _ in range(2):
        new = SUFFIX_RE.sub("", t)
        if new == t:
            break
        t = new
    t = t.lower()
    t = re.sub(r"['‘’“”]", "", t)
    t = re.sub(r"[^a-z0-9À-ɏЀ-ӿ֐-׿؀-ۿ一-鿿぀-ヿ ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

# -- Dedup pass --------------------------------------------------------------
def dedup_snapshot(snapshot: dict) -> dict:
    """Add dedup metadata to a snapshot in place AND return a deduped view."""
    # 1. Build canonical buckets across all items in the snapshot
    by_url: dict[str, list[tuple]] = defaultdict(list)
    by_title: dict[str, list[tuple]] = defaultdict(list)

    for ckey, cval in snapshot["countries"].items():
        for f in cval["feeds"]:
            for it in f.get("items", []):
                cu = canonical_url(it.get("link", ""))
                nt = normalise_title(it.get("title", ""))
                if cu:
                    by_url[cu].append((ckey, f["name"], it["id"]))
                if nt:
                    by_title[nt].append((ckey, f["name"], it["id"]))

    # 2. Annotate items with dedup info
    n_url_dupes = 0
    n_title_dupes = 0
    for ckey, cval in snapshot["countries"].items():
        for f in cval["feeds"]:
            for it in f.get("items", []):
                cu = canonical_url(it.get("link", ""))
                nt = normalise_title(it.get("title", ""))
                url_group = by_url.get(cu, [])
                title_group = by_title.get(nt, [])
                it["canonical_url"] = cu
                it["normalised_title"] = nt
                it["url_dup_count"] = len(url_group)
                it["title_dup_count"] = len(title_group)
                if len(url_group) > 1:
                    it["url_dup_feeds"] = sorted({f"{c}|{n}" for c, n, _ in url_group})
                    n_url_dupes += 1
                if len(title_group) > 1:
                    it["title_dup_feeds"] = sorted({f"{c}|{n}" for c, n, _ in title_group})
                    n_title_dupes += 1

    # 3. Build a deduped article list for embedding: keep one item per
    #    (canonical_url OR normalised_title) group, attaching the multi-source
    #    attribution. Picks the item with the longest summary as "primary".
    seen_keys = set()
    deduped = []
    for ckey, cval in snapshot["countries"].items():
        for f in cval["feeds"]:
            for it in f.get("items", []):
                cu = it.get("canonical_url", "")
                nt = it.get("normalised_title", "")
                # Prefer canonical_url group key when available
                key = ("u", cu) if cu else ("t", nt) if nt else ("i", it["id"])
                if key in seen_keys:
                    continue
                # Find all items in the same group
                same_url = by_url.get(cu, []) if cu else []
                same_title = by_title.get(nt, []) if nt else []
                group = {(c, n) for c, n, _ in same_url + same_title}
                # Pick longest-summary representative across the group
                rep = it
                best_len = len(it.get("summary", ""))
                for ckey2, cval2 in snapshot["countries"].items():
                    for f2 in cval2["feeds"]:
                        for it2 in f2.get("items", []):
                            if (ckey2, f2["name"]) not in group:
                                continue
                            sl = len(it2.get("summary", ""))
                            if sl > best_len:
                                best_len = sl
                                rep = it2
                deduped.append({
                    **rep,
                    "primary_feed": f["name"],
                    "primary_country": ckey,
                    "source_feeds": sorted(f"{c}|{n}" for c, n in group) or [f"{ckey}|{f['name']}"],
                    "source_count": max(1, len(group)),
                })
                seen_keys.add(key)

    return {
        "n_url_dupes": n_url_dupes,
        "n_title_dupes": n_title_dupes,
        "n_total_items": sum(len(f["items"]) for c in snapshot["countries"].values() for f in c["feeds"]),
        "n_deduped": len(deduped),
        "deduped_items": deduped,
    }


def main():
    if len(sys.argv) > 1:
        snap_path = Path(sys.argv[1])
    else:
        # latest non-suffix snapshot
        cands = sorted(p for p in SNAPS.glob("[0-9]*.json")
                       if not p.stem.endswith(("_convergence", "_similarity", "_prompt")))
        snap_path = cands[-1]
    print(f"Dedup'ing {snap_path}")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    result = dedup_snapshot(snap)
    print(f"  total items   : {result['n_total_items']}")
    print(f"  deduped items : {result['n_deduped']}  "
          f"(reduction: {100*(1 - result['n_deduped']/max(1,result['n_total_items'])):.1f}%)")
    print(f"  url dupes     : {result['n_url_dupes']}")
    print(f"  title dupes   : {result['n_title_dupes']}")
    # Write annotated snapshot back
    snap_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False))
    # Write dedup result alongside
    out = snap_path.with_name(snap_path.stem + "_dedup.json")
    out.write_text(json.dumps({
        "n_total_items": result["n_total_items"],
        "n_deduped": result["n_deduped"],
        "n_url_dupes": result["n_url_dupes"],
        "n_title_dupes": result["n_title_dupes"],
        "deduped_items": result["deduped_items"],
    }, indent=2, ensure_ascii=False))
    print(f"  wrote {out.name}")
    # Spot-check: top 10 dup groups
    groups = defaultdict(list)
    for ckey, cval in snap["countries"].items():
        for f in cval["feeds"]:
            for it in f.get("items", []):
                if it.get("title_dup_count", 0) > 1:
                    groups[it["normalised_title"]].append((ckey, f["name"], it["title"]))
    print("\nTop title-dup groups (multi-feed near-duplicates):")
    for k, vs in sorted(groups.items(), key=lambda x: -len(x[1]))[:8]:
        print(f"  ({len(vs)}x) {k[:80]}")
        for c, fn, t in vs[:3]:
            print(f"    - {c}|{fn}: {t[:80]}")


if __name__ == "__main__":
    main()
