"""cluster_diagnostic.py — DBSCAN vs HDBSCAN parallel diagnostic.

PR 8: v8 swapped DBSCAN → HDBSCAN at meta-6.0.0 (Phase C.5). The
swap was justified in `archive/clustering_calibration_*.md`, but
ongoing comparison is the honest way to confirm the new choice is
still the right one as the corpus grows and changes shape.

This script runs BOTH algorithms over the same distance matrix and
emits `diagnostic/<date>_cluster_compare.json` recording:

  - cluster counts (excluding noise) per algorithm
  - noise-point counts per algorithm
  - HDBSCAN mean cluster persistence (its native quality metric)
  - DBSCAN mean silhouette coefficient (its native quality metric)
  - sample of N articles where the two algorithms placed them in
    different clusters (so a human can eyeball whether HDBSCAN's
    splits / merges look correct)

Zero production impact: nothing the daily cron writes is affected.
The script is invoked separately (recommended weekly) and writes
only to diagnostic/. Run for a week or two post-PR-merge; if
HDBSCAN's structural improvement isn't supported by the data, revert
the clustering.method pin at the next minor bump.

Usage:
  python -m pipeline.cluster_diagnostic                # today's snapshot
  python -m pipeline.cluster_diagnostic --date 2026-05-08
  python -m pipeline.cluster_diagnostic --sample 200   # cap corpus size
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
SNAPS = ROOT / "snapshots"
DIAG = ROOT / "diagnostic"


def _cluster_both(dist: "np.ndarray", min_cluster_size: int,
                  eps: float, min_samples: int) -> dict:
    """Run HDBSCAN + DBSCAN on the same precomputed distance matrix.

    Imports kept inside the function so the comparison logic can be
    tested by passing pre-built distance matrices, and so a missing
    HDBSCAN install fails this script not the daily cron.
    """
    import numpy as np
    from sklearn.cluster import DBSCAN
    try:
        from sklearn.metrics import silhouette_score
    except ImportError:
        silhouette_score = None
    try:
        import hdbscan as _hdbscan_lib
    except ImportError:
        return {"error": "hdbscan not installed"}

    hdb = _hdbscan_lib.HDBSCAN(
        min_cluster_size=min_cluster_size,
        metric="precomputed",
        cluster_selection_method="eom",
    )
    hdb_labels = hdb.fit_predict(dist.astype("float64"))
    pers_attr = getattr(hdb, "cluster_persistence_", None)
    hdb_persistence = (list(map(float, pers_attr))
                        if pers_attr is not None and len(pers_attr) else [])

    db = DBSCAN(eps=eps, min_samples=min_samples, metric="precomputed")
    db_labels = db.fit_predict(dist)

    def _cluster_stats(labels) -> dict:
        labels = np.asarray(labels)
        non_noise = labels[labels != -1]
        n_clusters = int(len(set(non_noise.tolist())))
        n_noise = int((labels == -1).sum())
        return {"n_clusters": n_clusters, "n_noise": n_noise,
                "n_total": int(len(labels))}

    out: dict = {
        "hdbscan": {
            **_cluster_stats(hdb_labels),
            "mean_persistence": (round(float(np.mean(hdb_persistence)), 4)
                                  if hdb_persistence else None),
            "params": {"min_cluster_size": min_cluster_size,
                       "cluster_selection_method": "eom"},
        },
        "dbscan": {
            **_cluster_stats(db_labels),
            "params": {"eps": eps, "min_samples": min_samples},
        },
    }

    # Silhouette is only valid with > 1 cluster, no noise-only labels.
    for name, labels in (("hdbscan", hdb_labels), ("dbscan", db_labels)):
        if silhouette_score is None:
            out[name]["silhouette"] = None
            continue
        mask = labels != -1
        if mask.sum() < 2 or len(set(labels[mask].tolist())) < 2:
            out[name]["silhouette"] = None
            continue
        try:
            sil = silhouette_score(dist[np.ix_(mask, mask)],
                                    labels[mask], metric="precomputed")
            out[name]["silhouette"] = round(float(sil), 4)
        except Exception:
            out[name]["silhouette"] = None

    # Per-article disagreement sample: same item, different cluster id.
    # A label-id mismatch isn't disagreement by itself (cluster ids are
    # arbitrary); what matters is whether two items in the same HDBSCAN
    # cluster are also in the same DBSCAN cluster.
    n = len(hdb_labels)
    n_pairs_checked = 0
    n_pairs_disagree = 0
    disagreement_examples: list[dict] = []
    for i in range(n):
        for j in range(i + 1, n):
            hi, hj = int(hdb_labels[i]), int(hdb_labels[j])
            di, dj = int(db_labels[i]), int(db_labels[j])
            if hi == -1 or hj == -1 or di == -1 or dj == -1:
                continue
            n_pairs_checked += 1
            hsame = (hi == hj)
            dsame = (di == dj)
            if hsame != dsame:
                n_pairs_disagree += 1
                if len(disagreement_examples) < 10:
                    disagreement_examples.append({
                        "i": i, "j": j,
                        "hdbscan_same_cluster": hsame,
                        "dbscan_same_cluster": dsame,
                        "distance": round(float(dist[i, j]), 4),
                    })
    out["pair_agreement"] = {
        "n_pairs_checked": n_pairs_checked,
        "n_pairs_disagree": n_pairs_disagree,
        "pct_disagree": (round(100.0 * n_pairs_disagree / n_pairs_checked, 2)
                          if n_pairs_checked else None),
        "examples": disagreement_examples,
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None)
    ap.add_argument("--sample", type=int, default=200,
                    help="Cap corpus size (random sample).")
    ap.add_argument("--out-dir", default=str(DIAG))
    args = ap.parse_args()

    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snap = SNAPS / f"{date}.json"
    if not snap.exists():
        print(f"No snapshot at {snap}", file=sys.stderr)
        return 1

    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as e:
        print(f"ML deps missing — cannot build distance matrix: {e}",
              file=sys.stderr)
        return 1

    # Pull signal_text from snapshot
    snap_doc = json.loads(snap.read_text(encoding="utf-8"))
    texts: list[str] = []
    for bucket in snap_doc.get("countries", {}).values():
        for f in bucket.get("feeds", []):
            for it in f.get("items", []) or []:
                t = it.get("signal_text") or it.get("title")
                if t:
                    texts.append(t)
    if len(texts) > args.sample:
        import random
        random.seed(0)
        texts = random.sample(texts, args.sample)
    if len(texts) < 10:
        print(f"insufficient_corpus: only {len(texts)} items", file=sys.stderr)
        return 1
    print(f"embedding {len(texts)} items")
    model = SentenceTransformer(meta.EMBEDDING.get(
        "model", "paraphrase-multilingual-MiniLM-L12-v2"))
    vectors = model.encode(texts, batch_size=int(meta.EMBEDDING.get("batch_size", 64)))
    dist = 1 - cosine_similarity(vectors)
    dist = np.maximum(dist, 0)

    result = _cluster_both(
        dist,
        min_cluster_size=int(meta.CLUSTERING.get("min_cluster_size", 3)),
        eps=float(meta.CLUSTERING.get("legacy_dbscan_eps", 0.35)),
        min_samples=int(meta.CLUSTERING.get("legacy_dbscan_min_samples", 3)),
    )
    result = meta.stamp({
        "date": date,
        "n_items": len(texts),
        **result,
    })
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date}_cluster_compare.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
