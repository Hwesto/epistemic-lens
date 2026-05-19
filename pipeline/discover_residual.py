"""discover_residual.py — HDBSCAN clustering over articles the perception layer rejected.

PR2 Phase C. After build_briefing.py assigns articles to canonical stories
via softmax-argmax, anywhere from a few hundred to a few thousand articles
per day remain UNASSIGNED (story_key=None — either argmax cosine below floor,
or the cosine_gap filter rejected an equidistant article). Those unassigned
articles are the discovery surface for stories the canonical set doesn't
yet cover.

Algorithm:
  1. Load the day's embedding cache (snapshots/<DATE>_embeddings.npy +
     _embedding_ids.json) — produced by pipeline/embed_articles.py.
  2. Load every briefings/<DATE>_<story>.json (skipping _metrics.json
     siblings) to find which article_ids were ASSIGNED to a canonical story.
  3. Compute residual = all_articles - assigned_articles.
  4. HDBSCAN(min_cluster_size=meta.CLUSTERING['min_cluster_size']) over
     the residual vectors.
  5. For each non-noise cluster, emit:
       - cluster_id (stable within the day; reassigned next day)
       - member article_ids
       - bucket distribution (from snapshot lookup)
       - top tokens via meta.tokenize() on member titles
  6. Write snapshots/<DATE>_residual_clusters.json.

Why HDBSCAN, not k-means or centroid-based: HDBSCAN is density-adaptive,
doesn't require k, and exposes per-cluster stability scores (already pinned
to meta-v6.0.0 as the project's primary clusterer). Already in production
for cluster_diagnostic; reusing it keeps the pipeline self-consistent.

Why member-ID overlap (lineage in persistence_tracker.py) rather than
centroid-cosine: cluster centroids DRIFT day-to-day as the residual pool
changes. Member-article overlap is invariant to centroid composition — if
the same articles cluster together two days running, that's a real signal.

Usage:
  python -m pipeline.discover_residual                 # latest snapshot
  python -m pipeline.discover_residual --date 2026-05-12
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import meta
from analytical import perception

SNAPSHOTS = meta.REPO_ROOT / "snapshots"
BRIEFINGS = meta.REPO_ROOT / "briefings"


def _assigned_article_ids(date: str) -> set[str]:
    """All article_ids that landed in SOME canonical-story briefing for
    the given date. The discover_residual step looks at the complement."""
    assigned: set[str] = set()
    perception_cfg = getattr(meta, "PERCEPTION", None) or {}
    model_id = perception_cfg.get("embedding_model") or ""
    sig_version = perception_cfg.get("signal_text_version", "v1")
    if not model_id:
        return assigned  # Pre-9.0 transition: nothing to subtract
    for briefing_path in BRIEFINGS.glob(f"{date}_*.json"):
        if briefing_path.stem.endswith(("_metrics", "_within_lang_llr",
                                          "_within_lang_pmi", "_headline")):
            continue
        try:
            b = json.loads(briefing_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # Guard against picking up a stale briefing whose filename matched
        # by accident (e.g. a partially-written file from yesterday with
        # today's prefix). If the briefing's stamped date doesn't match
        # the discovery date, skip it — we'd be subtracting the wrong
        # article set and contaminating the residual.
        if b.get("date") and b["date"] != date:
            print(f"  skipping {briefing_path.name}: stamped date "
                  f"{b['date']} != {date}", flush=True)
            continue
        for entry in (b.get("corpus") or []):
            feed = entry.get("feed") or ""
            link = entry.get("link") or ""
            if not link:
                continue
            assigned.add(perception.article_id(feed, link, model_id, sig_version))
    return assigned


def _index_snapshot(snap: dict) -> dict[str, tuple[str, str]]:
    """One pass: map article_id -> (bucket_key, title). Used by `discover`
    for per-cluster bucket distribution and top-tokens. Merged from
    earlier _bucket_of_article + _title_of_article (2N) into single
    iteration (N) — audit follow-up cleanup."""
    perception_cfg = getattr(meta, "PERCEPTION", None) or {}
    model_id = perception_cfg.get("embedding_model") or ""
    sig_version = perception_cfg.get("signal_text_version", "v1")
    out: dict[str, tuple[str, str]] = {}
    for ck, cv in (snap.get("countries") or {}).items():
        for f in (cv.get("feeds") or []):
            feed_name = f.get("name") or ""
            for it in (f.get("items") or []):
                link = it.get("link") or ""
                if not link:
                    continue
                aid = perception.article_id(feed_name, link, model_id, sig_version)
                out[aid] = (ck, it.get("title") or "")
    return out


def discover(date: str, min_cluster_size: int | None = None) -> dict:
    """Run HDBSCAN over articles the perception layer didn't assign.
    Returns the residual_clusters.json shape (also writes it to disk)."""
    snap_path = SNAPSHOTS / f"{date}.json"
    if not snap_path.exists():
        raise FileNotFoundError(f"snapshot missing: {snap_path}")

    cache = perception.load_embedding_cache(date)
    if cache is None:
        raise FileNotFoundError(
            f"embedding cache missing for {date}; "
            "run `python -m pipeline.embed_articles --date {date}` first"
        )
    all_ids, all_vecs = cache

    assigned = _assigned_article_ids(date)
    print(f"  {len(assigned)} / {len(all_ids)} articles assigned to a "
          f"canonical story", flush=True)

    keep_mask = [aid not in assigned for aid in all_ids]
    residual_ids = [aid for aid, keep in zip(all_ids, keep_mask) if keep]
    if not residual_ids:
        print("  no residual articles to cluster", flush=True)
        return _write_clusters(date, [])

    import numpy as np  # type: ignore
    residual_vecs = all_vecs[np.array(keep_mask, dtype=bool)]
    print(f"  clustering {len(residual_ids)} residual articles...", flush=True)

    try:
        import hdbscan  # type: ignore
    except ImportError:
        print("hdbscan not installed; cannot cluster residuals", file=sys.stderr)
        return _write_clusters(date, [])

    mcs = min_cluster_size or int(
        (getattr(meta, "CLUSTERING", None) or {}).get("min_cluster_size", 3)
    )
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=max(mcs, 3),
        metric="euclidean",  # vectors are unit-normed → euclidean ~ cosine
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(residual_vecs)
    # Per-cluster member IDs (skip noise label -1)
    by_cluster: dict[int, list[int]] = defaultdict(list)
    for i, lbl in enumerate(labels):
        if lbl == -1:
            continue
        by_cluster[int(lbl)].append(i)
    n_clusters = len(by_cluster)
    n_noise = int((labels == -1).sum())
    print(f"  {n_clusters} clusters; {n_noise} noise points", flush=True)

    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    snap_index = _index_snapshot(snap)
    stability = (getattr(clusterer, "cluster_persistence_", None)
                 if hasattr(clusterer, "cluster_persistence_") else None)

    clusters_out: list[dict] = []
    for cid, idxs in sorted(by_cluster.items()):
        member_ids = [residual_ids[i] for i in idxs]
        # Member-article centroid (mean of unit vecs, then normalise)
        centroid = residual_vecs[idxs].mean(axis=0)
        cn = float(np.linalg.norm(centroid))
        if cn > 0:
            centroid = centroid / cn
        # Bucket distribution + top tokens via single snap_index lookup
        bucket_dist: Counter = Counter()
        tok_counter: Counter = Counter()
        for aid in member_ids:
            bucket, title = snap_index.get(aid, ("?", ""))
            bucket_dist[bucket] += 1
            for t in meta.tokenize(title):
                tok_counter[t] += 1
        top_tokens = [t for t, _ in tok_counter.most_common(10)]
        clusters_out.append({
            "cluster_id": cid,
            "n_articles": len(member_ids),
            "n_buckets": len(bucket_dist),
            "member_article_ids": sorted(member_ids),
            "bucket_distribution": dict(bucket_dist),
            "top_tokens": top_tokens,
            "centroid_dim": int(centroid.shape[0]),
            "stability": (float(stability[cid])
                          if stability is not None and cid < len(stability)
                          else None),
        })
    # Sort by n_buckets desc, then n_articles desc — broadest cross-bucket
    # clusters are the strongest promotion candidates.
    clusters_out.sort(key=lambda c: (-c["n_buckets"], -c["n_articles"]))
    return _write_clusters(date, clusters_out)


def _write_clusters(date: str, clusters: list[dict]) -> dict:
    out = meta.stamp({
        "date": date,
        "n_clusters": len(clusters),
        "clusters": clusters,
    })
    out_path = SNAPSHOTS / f"{date}_residual_clusters.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  wrote {out_path.name} ({len(clusters)} clusters)", flush=True)
    return out


def latest_snapshot_date() -> str | None:
    cands = sorted(p for p in SNAPSHOTS.glob("[0-9]*.json")
                   if not p.stem.endswith(("_convergence", "_similarity",
                                           "_prompt", "_dedup", "_health",
                                           "_pull_report", "_residual_clusters")))
    return cands[-1].stem if cands else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None,
                    help="Date (YYYY-MM-DD). Defaults to latest snapshot.")
    ap.add_argument("--min-cluster-size", type=int, default=None,
                    help="Override meta.CLUSTERING.min_cluster_size.")
    args = ap.parse_args()
    date = args.date or latest_snapshot_date()
    if not date:
        print("no snapshot found", file=sys.stderr)
        return 1
    try:
        discover(date, min_cluster_size=args.min_cluster_size)
    except FileNotFoundError as e:
        print(f"::warning::{e}")
        return 0  # not a fail — just nothing to discover yet
    return 0


if __name__ == "__main__":
    sys.exit(main())
