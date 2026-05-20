"""cluster_daily.py — HDBSCAN over EVERY article in the day's snapshot.

v10 (Phase D.3). Replaces the v9 "discover_residual" approach where we
first matched articles to 15 pre-defined canonical stories via
softmax-argmax against embedding anchors, then clustered only the
residual (unmatched) articles. The closed-world matching produced
fossilized story keys, rejected 95% of articles, and made the daily
pipeline a fixed-15-dossier product.

v10 is OPEN-WORLD: cluster every article each day; let the clusters BE
the stories of the day. Lineage tracking across days (member-ID Jaccard
overlap ≥ 0.30, see core/cluster/lineage.py) carries persistent stories
forward; new clusters emerge naturally as breaking news happens; stale
stories disappear when outlets stop talking about them.

Pipeline:
  1. Load the day's embedding cache (data/snapshots/<DATE>_embeddings.npy
     + _embedding_ids.json) produced by core/embed/encode.py.
  2. HDBSCAN(min_cluster_size=meta.CLUSTERING['min_cluster_size'])
     over all article vectors.
  3. For each non-noise cluster, emit:
       - cluster_id (stable within the day)
       - member_article_ids
       - country_distribution (each article's outlet's country, via outlets.json)
       - outlet_distribution (raw outlet names)
       - lang_distribution
       - top_tokens (via meta.tokenize on member titles)
       - centroid_dim, stability
  4. Write data/snapshots/<DATE>_clusters.json.

Salience ranking (core/cluster/salience.py) consumes this file and
picks the top ~15 clusters as the day's stories for briefing + analysis.

Why HDBSCAN: density-adaptive (no k to pick); ignores outliers as noise
rather than forcing every article into a cluster; per-cluster stability
scores let downstream consumers reason about cluster quality.

Why cluster ALL articles (not just residual): the v9 residual approach
required a pre-set canonical list, which fossilized story names. v10
treats every article as a candidate, and any sufficiently dense subset
becomes a cluster.

Usage:
  python -m core.cluster.cluster_daily                # latest snapshot
  python -m core.cluster.cluster_daily --date 2026-05-12
  python -m core.cluster.cluster_daily --min-cluster-size 5
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import core.meta as meta
from core.embed import article_id as aid_module  # extracted from old perception.py

SNAPSHOTS = meta.SNAPSHOTS_DIR


def _load_embedding_cache(date: str) -> tuple[list[str], "np.ndarray"] | None:
    """Load article embedding cache for a date. Returns (ids, vecs) or None."""
    import numpy as np  # type: ignore
    vec_path = SNAPSHOTS / f"{date}_embeddings.npy"
    id_path = SNAPSHOTS / f"{date}_embedding_ids.json"
    if not vec_path.exists() or not id_path.exists():
        return None
    vecs = np.load(vec_path)
    ids = json.loads(id_path.read_text(encoding="utf-8"))
    if len(ids) != vecs.shape[0]:
        return None
    return ids, vecs


def _index_snapshot(snap: dict) -> dict[str, dict]:
    """One pass: map article_id -> {outlet, country, lang, title}.
    Used by `discover` for per-cluster outlet / country / lang distributions
    and top-tokens computation.

    v10: keys are now {outlet, country, lang}. The old "bucket" field is
    just the country in v10's outlet-first model.
    """
    perception_cfg = getattr(meta, "PERCEPTION", None) or {}
    model_id = perception_cfg.get("embedding_model") or ""
    sig_version = perception_cfg.get("signal_text_version", "v1")
    outlet_lookup = meta.outlet_by_name()
    out: dict[str, dict] = {}
    for ck, cv in (snap.get("countries") or {}).items():
        for f in (cv.get("feeds") or []):
            feed_name = f.get("name") or ""
            outlet_meta = outlet_lookup.get(feed_name) or {}
            lang = outlet_meta.get("lang") or f.get("lang") or "en"
            for it in (f.get("items") or []):
                link = it.get("link") or ""
                if not link:
                    continue
                article_id = aid_module.article_id(feed_name, link, model_id, sig_version)
                out[article_id] = {
                    "outlet": feed_name,
                    "country": ck,
                    "lang": lang,
                    "title": it.get("title") or "",
                }
    return out


def discover(date: str, min_cluster_size: int | None = None) -> dict:
    """Run HDBSCAN over every article in the day's embedding cache.
    Returns the clusters dict (also writes it to disk)."""
    snap_path = SNAPSHOTS / f"{date}.json"
    if not snap_path.exists():
        raise FileNotFoundError(f"snapshot missing: {snap_path}")

    cache = _load_embedding_cache(date)
    if cache is None:
        raise FileNotFoundError(
            f"embedding cache missing for {date}; "
            f"run `python -m core.embed.encode --date {date}` first"
        )
    all_ids, all_vecs = cache
    print(f"  clustering {len(all_ids)} articles (full daily set)...",
          flush=True)

    try:
        import hdbscan  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        print("hdbscan / numpy not installed; cannot cluster", file=sys.stderr)
        return _write_clusters(date, [])

    mcs = min_cluster_size or int(
        (getattr(meta, "CLUSTERING", None) or {}).get("min_cluster_size", 3)
    )
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=max(mcs, 3),
        metric="euclidean",  # vectors are unit-normed → euclidean ~ cosine
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(all_vecs)

    # Per-cluster member indexes (skip noise label -1)
    by_cluster: dict[int, list[int]] = {}
    for i, lbl in enumerate(labels):
        if lbl == -1:
            continue
        by_cluster.setdefault(int(lbl), []).append(i)
    n_clusters = len(by_cluster)
    n_noise = int((labels == -1).sum())
    print(f"  {n_clusters} clusters; {n_noise} noise points",
          flush=True)

    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    snap_index = _index_snapshot(snap)
    stability = (getattr(clusterer, "cluster_persistence_", None)
                 if hasattr(clusterer, "cluster_persistence_") else None)

    clusters_out: list[dict] = []
    for cid, idxs in sorted(by_cluster.items()):
        member_ids = [all_ids[i] for i in idxs]
        # Member-article centroid (mean of unit vecs, then normalise)
        centroid = all_vecs[idxs].mean(axis=0)
        cn = float(np.linalg.norm(centroid))
        if cn > 0:
            centroid = centroid / cn
        # Distributions
        country_dist: Counter = Counter()
        outlet_dist: Counter = Counter()
        lang_dist: Counter = Counter()
        tok_counter: Counter = Counter()
        for aid_ in member_ids:
            meta_ = snap_index.get(aid_) or {}
            country_dist[meta_.get("country") or "?"] += 1
            outlet_dist[meta_.get("outlet") or "?"] += 1
            lang_dist[meta_.get("lang") or "?"] += 1
            for t in meta.tokenize(meta_.get("title") or ""):
                tok_counter[t] += 1
        top_tokens = [t for t, _ in tok_counter.most_common(10)]
        clusters_out.append({
            "cluster_id": cid,
            "n_articles": len(member_ids),
            "n_countries": len(country_dist),
            "n_outlets": len(outlet_dist),
            "n_langs": len(lang_dist),
            "member_article_ids": sorted(member_ids),
            "country_distribution": dict(country_dist),
            "outlet_distribution": dict(outlet_dist),
            "lang_distribution": dict(lang_dist),
            "top_tokens": top_tokens,
            "centroid_dim": int(centroid.shape[0]),
            "stability": (float(stability[cid])
                          if stability is not None and cid < len(stability)
                          else None),
        })
    # Sort by n_countries desc, then n_articles desc — broadest cross-country
    # clusters first. Salience ranking (core/cluster/salience.py) will pick
    # top-N for actual analysis.
    clusters_out.sort(key=lambda c: (-c["n_countries"], -c["n_articles"]))
    return _write_clusters(date, clusters_out)


def _write_clusters(date: str, clusters: list[dict]) -> dict:
    out = meta.stamp({
        "date": date,
        "n_clusters": len(clusters),
        "clusters": clusters,
    })
    out_path = SNAPSHOTS / f"{date}_clusters.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  wrote {out_path.name} ({len(clusters)} clusters)", flush=True)
    return out


def latest_snapshot_date() -> str | None:
    cands = sorted(p for p in SNAPSHOTS.glob("[0-9]*.json")
                   if not p.stem.endswith(("_convergence", "_similarity",
                                           "_prompt", "_dedup", "_health",
                                           "_pull_report", "_clusters")))
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
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
