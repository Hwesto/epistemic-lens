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

Phase 1 addition: cross-day dedup. A rolling 30-day state in
`cross_day_dedup_state.json` tracks first-seen date for each canonical URL +
normalised title. Items matching a state entry get `cross_day_duplicate=True`
and `cross_day_first_seen=<date>`; the original is *not* dropped (downstream
consumers decide), but the count-inflation hole the audit identified is
closed: longitudinal aggregators can now filter cross-day duplicates from
weekly/monthly counts.

Dedup output preserves which feeds carried each item. The dedup'd snapshot
is what feeds embedding/clustering. The raw items remain in the original
snapshot file for audit.

Usage:
  python3 dedup.py                       # run on latest snapshot
  python3 dedup.py snapshots/YYYY-MM-DD.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import meta

ROOT = meta.REPO_ROOT
SNAPS = ROOT / "snapshots"
CROSS_DAY_STATE_FILE = ROOT / "cross_day_dedup_state.json"
CROSS_DAY_WINDOW_DAYS = 30

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

# -- Cross-day dedup state ---------------------------------------------------
def load_cross_day_state(path: Path = CROSS_DAY_STATE_FILE) -> dict:
    """Load (or initialise) the rolling cross-day state file.

    Schema:
      {
        "_doc": "...",
        "window_days": 30,
        "url_first_seen": {canonical_url: "YYYY-MM-DD", ...},
        "title_first_seen": {normalised_title: "YYYY-MM-DD", ...},
      }
    """
    if not path.exists():
        return {
            "_doc": (
                "Rolling cross-day dedup state. Each entry stores the first "
                "date a canonical URL or normalised title was seen. Entries "
                "older than `window_days` are pruned at each dedup run. Phase 1."
            ),
            "window_days": CROSS_DAY_WINDOW_DAYS,
            "url_first_seen": {},
            "title_first_seen": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def save_cross_day_state(state: dict, path: Path = CROSS_DAY_STATE_FILE) -> None:
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def prune_cross_day_state(state: dict, today: str | None = None) -> int:
    """Drop entries whose first_seen is older than window_days. Returns count pruned."""
    today_d = date.fromisoformat(today) if today else date.today()
    window = int(state.get("window_days", CROSS_DAY_WINDOW_DAYS))
    cutoff = (today_d - timedelta(days=window)).isoformat()
    pruned = 0
    for field in ("url_first_seen", "title_first_seen"):
        bucket = state.get(field) or {}
        for k in list(bucket):
            if bucket[k] < cutoff:
                del bucket[k]
                pruned += 1
        state[field] = bucket
    return pruned


def seen_url_recently(canonical: str, state: dict) -> str | None:
    """Return first-seen date if canonical URL is in state, else None."""
    if not canonical:
        return None
    return (state.get("url_first_seen") or {}).get(canonical)


def seen_title_recently(normalised: str, state: dict) -> str | None:
    """Return first-seen date if normalised title is in state, else None."""
    if not normalised:
        return None
    return (state.get("title_first_seen") or {}).get(normalised)


def update_cross_day_state(state: dict, canonical_urls: set[str],
                            normalised_titles: set[str],
                            today: str | None = None) -> None:
    """Record first-seen dates for any URLs/titles not already in state.

    Idempotent: existing entries are NOT overwritten (the date stays at the
    actual first-seen, not today)."""
    today_iso = today or date.today().isoformat()
    state.setdefault("url_first_seen", {})
    state.setdefault("title_first_seen", {})
    for cu in canonical_urls:
        if cu and cu not in state["url_first_seen"]:
            state["url_first_seen"][cu] = today_iso
    for nt in normalised_titles:
        if nt and nt not in state["title_first_seen"]:
            state["title_first_seen"][nt] = today_iso


# -- Dedup pass --------------------------------------------------------------
def dedup_snapshot(snapshot: dict, cross_day_state: dict | None = None) -> dict:
    """Add dedup metadata to a snapshot in place AND return a deduped view.

    If `cross_day_state` is provided, items whose canonical URL or normalised
    title appears in the state get `cross_day_duplicate=True` and
    `cross_day_first_seen=<date>`. The state dict is updated with this
    snapshot's items in place; persisting is the caller's responsibility.
    """
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

    # 2. Annotate items with dedup info (intra-day + cross-day if state given)
    n_url_dupes = 0
    n_title_dupes = 0
    n_cross_day = 0
    today_canonical_urls: set[str] = set()
    today_normalised_titles: set[str] = set()
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
                # Cross-day check (Phase 1)
                if cross_day_state is not None:
                    if cu:
                        today_canonical_urls.add(cu)
                    if nt:
                        today_normalised_titles.add(nt)
                    seen_url_date = seen_url_recently(cu, cross_day_state)
                    seen_title_date = seen_title_recently(nt, cross_day_state)
                    first_seen = seen_url_date or seen_title_date
                    if first_seen:
                        it["cross_day_duplicate"] = True
                        it["cross_day_first_seen"] = first_seen
                        n_cross_day += 1
    if cross_day_state is not None:
        update_cross_day_state(
            cross_day_state, today_canonical_urls, today_normalised_titles
        )

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
        "n_cross_day_duplicates": n_cross_day,
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
                       if not p.stem.endswith(("_convergence", "_similarity",
                                               "_prompt", "_dedup", "_health",
                                               "_pull_report")))
        snap_path = cands[-1]
    print(f"Dedup'ing {snap_path}")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    cross_day_state = load_cross_day_state()
    pruned = prune_cross_day_state(cross_day_state)
    if pruned:
        print(f"  pruned cross-day state: {pruned} entries past {CROSS_DAY_WINDOW_DAYS}-day window")
    result = dedup_snapshot(snap, cross_day_state=cross_day_state)
    save_cross_day_state(cross_day_state)
    print(f"  total items   : {result['n_total_items']}")
    print(f"  deduped items : {result['n_deduped']}  "
          f"(reduction: {100*(1 - result['n_deduped']/max(1,result['n_total_items'])):.1f}%)")
    print(f"  url dupes     : {result['n_url_dupes']}")
    print(f"  title dupes   : {result['n_title_dupes']}")
    print(f"  cross-day dups: {result['n_cross_day_duplicates']}")
    # Write annotated snapshot back (re-stamp so live meta_version sticks)
    meta.stamp(snap)
    snap_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False))
    # Write dedup result alongside
    out = snap_path.with_name(snap_path.stem + "_dedup.json")
    out.write_text(json.dumps(meta.stamp({
        "n_total_items": result["n_total_items"],
        "n_deduped": result["n_deduped"],
        "n_url_dupes": result["n_url_dupes"],
        "n_title_dupes": result["n_title_dupes"],
        "deduped_items": result["deduped_items"],
    }), indent=2, ensure_ascii=False))
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
