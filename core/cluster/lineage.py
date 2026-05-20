"""lineage.py — member-ID Jaccard lineage across daily cluster files (v10).

After core/cluster/cluster_daily.py writes per-day `<DATE>_clusters.json`,
this script links clusters across days into LINEAGES — sequences of
clusters that share a substantial fraction of member articles. A lineage
is a story that persisted: the same articles re-clustering day over day.

The lineage_id this emits is the stable cross-day identity that
core/briefing/build.py stamps onto each briefing filename
(`data/briefings/<DATE>_<lineage_id>.json`), so a story keeps the same ID
for as long as it keeps surfacing.

Why member-ID Jaccard rather than centroid-cosine:
  HDBSCAN cluster centroids drift day-to-day as the day's article pool
  changes. The same underlying story may produce drifting centroids while
  still being carried by overlapping article sets. Member-article-ID
  Jaccard is invariant to centroid composition — if the same N articles
  appear in clusters two days running, that's signal.

Algorithm:
  1. Walk data/snapshots/<DATE>_clusters.json for the last N days.
  2. For each adjacent day-pair, compute Jaccard overlap on
     member_article_ids between every cluster pair.
  3. Link clusters across days when Jaccard ≥ jaccard_threshold (default
     0.30 — empirically picked, may need calibration).
  4. Union-find: emit lineages, each with a stable lineage_id, day_count,
     countries_seen (union of country distributions across days),
     latest_top_tokens, seed/latest cluster ids.
  5. Write data/archive/persistent_lineages_<DATE>.json — the file
     core/briefing/build.py reads to reuse lineage_ids.

Usage:
  python -m core.cluster.lineage                  # 7-day window
  python -m core.cluster.lineage --window 14
  python -m core.cluster.lineage --jaccard 0.40   # stricter
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date as date_cls, timedelta
from pathlib import Path

import core.meta as meta

SNAPSHOTS = meta.SNAPSHOTS_DIR
ARCHIVE = meta.ARCHIVE_DIR
# Defensive: if archive/ exists but is something other than a directory
# (corruption; recovery from a checkout that hit a file collision), fail
# loudly with a clear message rather than letting mkdir explode.
if ARCHIVE.exists() and not ARCHIVE.is_dir():
    raise RuntimeError(
        f"{ARCHIVE} exists but is not a directory; "
        "remove or rename it before running the lineage tracker."
    )
ARCHIVE.mkdir(exist_ok=True)


def _load_day(date: str) -> dict | None:
    p = SNAPSHOTS / f"{date}_clusters.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b) or 1
    return inter / union


def _lineage_id(seed_date: str, seed_cluster_id: int) -> str:
    """Stable opaque ID for a lineage. Hashed so re-running cluster_daily
    with a different min_cluster_size (which renumbers clusters) doesn't
    rename existing lineages — the seed_date+seed_cluster pair is enough
    for human inspection."""
    h = hashlib.sha256(f"{seed_date}|{seed_cluster_id}".encode()).hexdigest()
    return f"L{h[:10]}"


def build_lineages(window_days: int, end_date: str,
                    jaccard_threshold: float) -> list[dict]:
    end = date_cls.fromisoformat(end_date)
    days: list[tuple[str, dict]] = []
    for offset in range(window_days - 1, -1, -1):  # oldest first
        d = (end - timedelta(days=offset)).isoformat()
        doc = _load_day(d)
        if doc:
            days.append((d, doc))

    if len(days) < 2:
        return []

    # Each (date, cluster_id) is a node. Edges: same lineage if Jaccard ≥
    # threshold AND days are adjacent (consecutive dates).
    parent: dict[tuple[str, int], tuple[str, int]] = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Pre-extract member sets per (date, cluster_id)
    members: dict[tuple[str, int], set[str]] = {}
    metadata: dict[tuple[str, int], dict] = {}
    for d, doc in days:
        for c in (doc.get("clusters") or []):
            key = (d, int(c["cluster_id"]))
            members[key] = set(c.get("member_article_ids") or [])
            metadata[key] = c
            parent[key] = key  # init

    # Link adjacent days where Jaccard ≥ threshold
    for i in range(len(days) - 1):
        d_prev, doc_prev = days[i]
        d_next, doc_next = days[i + 1]
        prev_keys = [(d_prev, int(c["cluster_id"]))
                     for c in (doc_prev.get("clusters") or [])]
        next_keys = [(d_next, int(c["cluster_id"]))
                     for c in (doc_next.get("clusters") or [])]
        for nk in next_keys:
            best_j = 0.0
            best_pk = None
            for pk in prev_keys:
                j = _jaccard(members[pk], members[nk])
                if j > best_j:
                    best_j = j
                    best_pk = pk
            if best_pk is not None and best_j >= jaccard_threshold:
                union(best_pk, nk)

    # Group by root
    grouped: dict = defaultdict(list)
    for k in members:
        grouped[find(k)].append(k)

    lineages: list[dict] = []
    for root, keys in grouped.items():
        if len(keys) < 2:
            continue  # singleton — not a lineage
        keys.sort()  # oldest first
        seed_date, seed_cid = keys[0]
        latest_date, latest_cid = keys[-1]
        countries_seen: set[str] = set()
        token_counter: defaultdict = defaultdict(int)
        for k in keys:
            md = metadata[k]
            for c in (md.get("country_distribution")
                      or md.get("bucket_distribution") or {}):
                countries_seen.add(c)
            for t in (md.get("top_tokens") or [])[:10]:
                token_counter[t] += 1
        lineages.append({
            "lineage_id": _lineage_id(seed_date, seed_cid),
            "seed_date": seed_date,
            "seed_cluster_id": seed_cid,
            "latest_date": latest_date,
            "latest_cluster_id": latest_cid,
            "day_count": len({d for d, _ in keys}),
            "n_countries_union": len(countries_seen),
            "countries_seen": sorted(countries_seen),
            "latest_top_tokens": metadata[(latest_date, latest_cid)].get("top_tokens") or [],
            "latest_member_ids": metadata[(latest_date, latest_cid)].get("member_article_ids") or [],
            "consensus_tokens": [t for t, n in sorted(
                token_counter.items(), key=lambda kv: -kv[1])[:10] if n >= 2],
        })
    lineages.sort(key=lambda L: (-L["day_count"], -L["n_countries_union"]))
    return lineages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end-date", default=None,
                    help="Date (YYYY-MM-DD). Defaults to today UTC.")
    ap.add_argument("--window", type=int, default=7,
                    help="Days of <DATE>_clusters.json to walk. Default 7.")
    ap.add_argument("--jaccard", type=float, default=0.30,
                    help="Min member-ID Jaccard for cross-day linkage. Default 0.30.")
    args = ap.parse_args()
    from datetime import datetime, timezone
    end_date = args.end_date or datetime.now(timezone.utc).date().isoformat()

    lineages = build_lineages(args.window, end_date, args.jaccard)
    out = meta.stamp({
        "end_date": end_date,
        "window_days": args.window,
        "jaccard_threshold": args.jaccard,
        "n_lineages": len(lineages),
        "lineages": lineages,
    })
    out_path = ARCHIVE / f"persistent_lineages_{end_date}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"wrote {out_path.relative_to(meta.REPO_ROOT)} "
          f"({len(lineages)} lineages)")
    persistent = [L for L in lineages
                  if L["day_count"] >= 3 and L["n_countries_union"] >= 4]
    if persistent:
        print(f"  {len(persistent)} persistent lineage(s) "
              f"(>=3 days, >=4 countries):")
        for L in persistent[:5]:
            print(f"    {L['lineage_id']}: day_count={L['day_count']} "
                  f"countries={L['n_countries_union']} "
                  f"tokens={L['consensus_tokens'][:5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
