"""analytical/krippendorff.py — pure-Python Krippendorff's alpha for nominal data.

Used by analytical/ensemble.py to score inter-LLM agreement on `frame_id`
selections (Boydstun closed taxonomy). Pure standard library; no numpy/SciPy
dependency for one small statistical primitive.

For the small N (one analysis = ≤ 8 frames × 2-4 raters), this is plenty.

Reference: Krippendorff, K. (2011). Computing Krippendorff's Alpha-Reliability.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations


def alpha_nominal(ratings: list[list[str | None]]) -> float | None:
    """Krippendorff's alpha for nominal data.

    `ratings`: list of items; each item is a list of rater labels for that
    item. Use None for missing ratings (raters who didn't label that item).
    For nominal data, the metric is 1 if labels match, 0 otherwise.

    Returns None when alpha is undefined (e.g., only one item, or all raters
    chose the same label so expected disagreement is zero).
    """
    if not ratings:
        return None

    # Coincidence-matrix construction:
    # For each item with n_i (>=2) non-missing ratings, contribute pair counts
    # weighted by 1/(n_i - 1). The marginal counts come directly from a flat
    # tally of all non-missing labels.
    coincidences: Counter[tuple[str, str]] = Counter()
    label_marginals: Counter[str] = Counter()
    n_pairable = 0

    for item in ratings:
        non_missing = [r for r in item if r is not None]
        n_i = len(non_missing)
        if n_i < 2:
            # Items with fewer than two non-missing labels contribute nothing.
            continue
        weight = 1.0 / (n_i - 1)
        for a, b in combinations(non_missing, 2):
            # Both orderings — symmetric coincidence matrix.
            coincidences[(a, b)] += weight
            coincidences[(b, a)] += weight
        for r in non_missing:
            label_marginals[r] += 1
            n_pairable += 1

    if n_pairable < 2:
        return None

    # Observed disagreement Do = sum of off-diagonal coincidences / (n - 1) ...
    # but for nominal alpha the standard simplification:
    #   Do = (n_pairable - sum_v c_vv) / (n_pairable - 1)
    # where c_vv = (sum over items, weighted) of within-item same-label pairs
    # is equivalent. We compute it directly from the coincidence matrix.
    same_label = 0.0
    diff_label = 0.0
    for (a, b), w in coincidences.items():
        if a == b:
            same_label += w
        else:
            diff_label += w
    # Each unordered pair was double-counted (a,b) and (b,a); halve.
    same_label /= 2.0
    diff_label /= 2.0
    total_pairs = same_label + diff_label
    if total_pairs == 0:
        return None
    Do = diff_label / total_pairs

    # Expected disagreement De under random labelling given the marginals.
    # De = 1 - sum_v (n_v * (n_v - 1)) / (n_pairable * (n_pairable - 1))
    if n_pairable <= 1:
        return None
    sum_collisions = sum(n * (n - 1) for n in label_marginals.values())
    De = 1.0 - (sum_collisions / (n_pairable * (n_pairable - 1)))
    if De == 0:
        # Perfect marginal agreement — alpha is undefined.
        return None

    return 1.0 - (Do / De)


def agreement_summary(ratings: list[list[str | None]]) -> dict:
    """Detail dict useful for human review.

    Returns:
      n_items, n_raters, alpha, unanimous_items (list of indices where all
      raters agreed), and disagreement_items (list of (idx, label_set)).
    """
    n_items = len(ratings)
    n_raters = max((len(r) for r in ratings), default=0)
    alpha = alpha_nominal(ratings)
    unanimous: list[int] = []
    disagreement: list[tuple[int, list[str]]] = []
    for i, item in enumerate(ratings):
        labels = [r for r in item if r is not None]
        if not labels:
            continue
        if len(set(labels)) == 1:
            unanimous.append(i)
        else:
            disagreement.append((i, sorted(set(labels))))
    return {
        "n_items": n_items,
        "n_raters": n_raters,
        "alpha": alpha,
        "unanimous_count": len(unanimous),
        "disagreement_count": len(disagreement),
        "disagreements": [
            {"index": i, "labels_seen": labels} for i, labels in disagreement
        ],
    }
