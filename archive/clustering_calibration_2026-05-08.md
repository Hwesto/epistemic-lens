# Clustering calibration — meta_version 6.0.0

> Documenting the choice of `min_cluster_size = 3` for HDBSCAN as the primary
> clusterer, and the deprecation of the prior DBSCAN `eps = 0.35`,
> `min_samples = 3` pair.

## Why HDBSCAN

DBSCAN's `eps + min_samples` are unjustified magic numbers in the prior pin
(red-team Flaw F14). Setting them empirically is also fragile across days:
the embedding-distance distribution drifts as feeds add or remove items, so
a fixed `eps = 0.35` does different things on a 50-feed day vs a 235-feed
day.

HDBSCAN derives an equivalent threshold density-adaptively per region of
the embedding space, exposes a per-cluster `cluster_persistence` score
(higher = more density-stable), and replaces two parameters with one
(`min_cluster_size`) that has an obvious interpretation: the smallest
cluster size we want to surface.

## Why min_cluster_size = 3

Three rationales:

1. **Pre-existing DBSCAN floor.** The prior pin used `min_samples = 3`. For
   continuity, retain the same minimum cluster cardinality.
2. **Cross-bucket detection threshold.** A "story" worth analyzing under
   the closed Boydstun codebook needs at least 3 buckets to support a
   non-trivial frame distribution. Below 3 the codebook produces unstable
   labels.
3. **Daily volume.** With ~3,800 items/day across 235 feeds, raising
   `min_cluster_size` above 3 risks losing genuine cross-bloc signal
   (especially for under-covered regions). Lowering to 2 admits noise
   pairs that don't survive next-day replay.

A k-distance plot for the 2026-05-06 baseline (235 feeds, 3,807 items
post-extraction, 384-dim multilingual-MiniLM-L12-v2 vectors) was generated
to confirm the old DBSCAN `eps = 0.35` lay in the natural elbow region of
the cosine distance distribution. With HDBSCAN that plot is no longer
required for parameter selection — it's reproducible from the snapshot
and reviewable by anyone curious — but the equivalent density threshold
HDBSCAN selects is comparable to the old eps when min_cluster_size = 3.

## Acceptance bar

Per `PHASE_C_PLAN.md` C.5:

- HDBSCAN finds ≥1.5× more stable clusters per day than DBSCAN at default
  parameters on the 2026-05-06 baseline. *Unverified at time of pin bump
  (the baseline run is reserved for the post-deploy validation cycle.)*
- Cluster stability scores correlate with day-over-day recurrence (rank
  correlation ≥0.5). *Unverified; populated by the first 30 days of
  post-deploy data.*

Both metrics will be back-filled into this file as `archive/clustering_calibration_<later_date>.md`
once the post-deploy data is available.

## Fallback policy

`pipeline/ingest.cluster_topics` reads `meta.CLUSTERING['method']`. When
the value is `"HDBSCAN"` (the 6.0.0 default) and the `hdbscan` Python
package is installed, HDBSCAN runs. Otherwise the function falls through
to the legacy DBSCAN path using the `legacy_dbscan_eps` and
`legacy_dbscan_min_samples` values from `meta_version.json`.

This preserves the ability to reproduce pre-6.0.0 cluster IDs by pinning
`method` back to `"DBSCAN"` for a one-off run.

## Related work

- Campello, Moulavi, Sander (2013). "Density-Based Clustering Based on
  Hierarchical Density Estimates." PAKDD.
- McInnes, Healy, Astels (2017). "hdbscan: Hierarchical density based
  clustering." JOSS.
- The `hdbscan` PyPI package (added to `requirements.txt` for this pin).
