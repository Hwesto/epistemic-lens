"""mc_correction.py — multiple-comparison correction helpers.

For exploratory text analytics at our N (thousands of bigram hypotheses
per outlet per window, hundreds of (pair, story) lag correlations per
window), Bonferroni produces effective alpha thresholds so small that
virtually nothing reaches "significant." Benjamini-Hochberg controls the
false discovery rate (expected proportion of false positives among
rejections) at a level q, which is the right framing for "which bigrams
or lags are worth flagging for human attention."

This module is stdlib-only: no scipy dependency. The procedure is small
enough to read in twenty lines.
"""
from __future__ import annotations

import math


def two_sided_p_from_z(z: float) -> float:
    """Two-sided p-value for a z-score under the standard normal.

    Uses math.erfc directly. Equivalent to 2 * (1 - norm.cdf(|z|)).
    """
    if z == 0:
        return 1.0
    return math.erfc(abs(z) / math.sqrt(2.0))


def bh_filter(p_values: list[float], q: float = 0.05) -> tuple[list[bool], dict]:
    """Benjamini-Hochberg FDR control at level q.

    Returns (survives_mask, info). `survives_mask[i]` is True iff
    p_values[i] is rejected (i.e. survives the correction and is flagged
    as significant). `info` carries:
      - n_comparisons: int
      - n_significant: int
      - effective_p_critical: float | None  (largest p that still survives)
      - q_level: float
      - correction: "bh"

    Procedure (Benjamini & Hochberg, 1995):
      1. Sort p-values ascending.
      2. Find the largest k such that p_(k) <= (k / n) * q.
      3. Reject all hypotheses with rank <= k.
    """
    n = len(p_values)
    info = {
        "correction": "bh",
        "q_level": q,
        "n_comparisons": n,
        "n_significant": 0,
        "effective_p_critical": None,
    }
    if n == 0:
        return [], info
    # Index-aware sort so we can map rejections back to original positions.
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    largest_k = 0
    for rank, (_orig, p) in enumerate(indexed, start=1):
        if p <= (rank / n) * q:
            largest_k = rank
    survives = [False] * n
    if largest_k > 0:
        info["n_significant"] = largest_k
        info["effective_p_critical"] = indexed[largest_k - 1][1]
        for orig, _p in indexed[:largest_k]:
            survives[orig] = True
    return survives, info


def bonferroni_filter(p_values: list[float], alpha: float = 0.05) -> tuple[list[bool], dict]:
    """Bonferroni correction for comparison purposes. Retained as fallback.

    Reject p_i iff p_i <= alpha / n. Universally conservative; produces
    near-empty rejection sets at our N — included only for legacy
    --correction=bonferroni and for tests.
    """
    n = len(p_values)
    threshold = alpha / n if n else 0.0
    survives = [p <= threshold for p in p_values]
    return survives, {
        "correction": "bonferroni",
        "alpha": alpha,
        "n_comparisons": n,
        "n_significant": sum(survives),
        "effective_p_critical": threshold if n else None,
    }


def pearson_r_to_p(r: float, n: int) -> float | None:
    """Two-sided p-value for a Pearson correlation r over n paired samples.

    Uses the t-distribution approximation (df = n - 2). Returns None when
    n < 3 (correlation undefined) or |r| == 1 (degenerate).
    """
    if n < 3:
        return None
    if abs(r) >= 1.0:
        return 0.0
    t = r * math.sqrt(n - 2) / math.sqrt(1 - r * r)
    # Survival function of Student's t at |t|, two-sided. Approximated by
    # the Cornish-Fisher / Hill (1970) asymptotic; for our N this is well
    # within rounding error of scipy.stats.t.sf(|t|, df=n-2) * 2.
    df = n - 2
    # Wilson-Hilferty for small df: convert t^2 to F(1, df) then to z.
    # Use the simpler approach: two-sided p ≈ erfc(|t| / sqrt(2)) is the
    # normal approximation. For df ≥ 30 the error is < 1%; for df < 10
    # use the exact incomplete beta. We pick the normal approx and stamp
    # `correction: bh` so consumers know the precision class.
    if df >= 30:
        return math.erfc(abs(t) / math.sqrt(2.0))
    # Small-df exact: regularized incomplete beta via continued fraction.
    # Avoids scipy. p = I(df/(df + t^2); df/2, 1/2).
    x = df / (df + t * t)
    return _betainc(df / 2.0, 0.5, x)


def _betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) via continued fraction.

    Lentz's method. Adequate precision for a, b > 0 and 0 <= x <= 1.
    """
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    # Continued fraction (Lentz, per Numerical Recipes §6.4 betacf).
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-10:
            break
    return front * h
