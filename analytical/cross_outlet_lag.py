"""cross_outlet_lag.py — cross-correlation function (CCF) for outlet pairs.

For curated outlet bucket pairs (wire ↔ regional flagship ↔ regional
follower), compute who covers a story first by what lag. Reads daily
`coverage/<DATE>.json` to build per-bucket binary coverage time series
per story, then computes Pearson correlation at integer lags 0..7 days.

This is **CCF, not Granger**. At our N (~30 days × 15 stories ≈ 450
samples) Granger gives spurious causal claims; CCF gives "B is
correlated with A at lag k" which the consumer reads as "B follows A
by k days when both cover this story." Same signal, more honest framing.

Skips with `insufficient_history` when fewer than `min_days` (default 30)
days of coverage matrices are available.

Output: `lag/<bucket_a>__<bucket_b>.json` per curated pair, with peak lag
+ correlation strength + per-story breakdown + overall.

Usage:
  python -m analytical.cross_outlet_lag                        # all pairs
  python -m analytical.cross_outlet_lag --min-days 30          # custom min
  python -m analytical.cross_outlet_lag --pairs wire,flagship  # subset
  python -m analytical.cross_outlet_lag --weekly               # weekly cron entry
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import meta
from analytical.mc_correction import bh_filter, bonferroni_filter, pearson_r_to_p

ROOT = meta.REPO_ROOT
COVERAGE_DIR = ROOT / "coverage"
LAG_DIR = ROOT / "lag"

# Curated pairs. Buckets named per `feeds.json/countries`. Phase 2 starts
# small; pairs can be added without a major bump (forward-compatible).
CURATED_PAIRS = [
    # (label, A_bucket, B_bucket, comment)
    ("wire→usa",            "wire_services", "usa",
     "Does mainstream US coverage track Reuters/AP/AFP wire framing?"),
    ("wire→china",          "wire_services", "china",
     "Does Chinese coverage echo wire framing or diverge from it?"),
    ("wire→russia_native",  "wire_services", "russia_native",
     "Does Russian-language Russian press track wire?"),
    ("usa→canada",          "usa", "canada",
     "Canada-as-follower test for US coverage."),
    ("usa→australia_nz",    "usa", "australia_nz",
     "ANZ-as-follower test for US coverage."),
    ("israel→pan_arab",     "israel", "pan_arab",
     "Does pan-Arab press track Israeli framing?"),
    ("iran_state→iran_opposition", "iran_state", "iran_opposition",
     "Does Iranian opposition press follow state framing's news cycle?"),
    ("china→asia_pacific_regional", "china", "asia_pacific_regional",
     "Asia-Pacific-as-follower for Chinese coverage."),
]


def load_coverage_history(window_days: int = 30,
                            today: str | None = None,
                            cov_dir: Path = COVERAGE_DIR) -> dict[str, dict]:
    """Load the last `window_days` of coverage matrices, keyed by date."""
    today_d = date.fromisoformat(today) if today else date.today()
    out: dict[str, dict] = {}
    if not cov_dir.is_dir():
        return out
    for d_offset in range(window_days):
        d = (today_d - timedelta(days=d_offset)).isoformat()
        p = cov_dir / f"{d}.json"
        if p.exists():
            try:
                out[d] = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
                print(f"FAIL: {p}: {e}", file=sys.stderr)
                continue
    return out


def time_series_per_bucket_per_story(history: dict[str, dict]) -> dict:
    """Build per-(bucket, story_key) binary coverage series (date → 1/0)."""
    series: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(dict))
    for date_iso, matrix in history.items():
        for story_key, rows in (matrix.get("coverage") or {}).items():
            covered_buckets = {row["bucket"] for row in rows
                                if row.get("section") == "news"}
            # Walk all known buckets (any seen across history)
            # We'll fill in zeros lazily later
            for b in covered_buckets:
                series[b][story_key][date_iso] = 1
    return series


def pearson_at_lag(a: list[int], b: list[int], lag: int) -> float | None:
    """Pearson correlation between a[t] and b[t + lag] over shared support.

    Positive lag = B trails A (A leads B by `lag` days). I.e. the
    correlation peaks at `lag = k` if B's series equals A's series shifted
    right by k positions. Returns None when fewer than 3 paired samples
    or when either side has zero variance (correlation undefined)."""
    if lag >= 0:
        a_lag = a[: len(a) - lag] if lag < len(a) else []
        b_lag = b[lag:]
    else:
        a_lag = a[-lag:]
        b_lag = b[: len(b) + lag] if -lag < len(b) else []
    if len(a_lag) != len(b_lag) or len(a_lag) < 3:
        return None
    n = len(a_lag)
    sa = sum(a_lag); sb = sum(b_lag)
    saa = sum(x * x for x in a_lag); sbb = sum(x * x for x in b_lag)
    sab = sum(x * y for x, y in zip(a_lag, b_lag))
    num = n * sab - sa * sb
    den = ((n * saa - sa * sa) * (n * sbb - sb * sb)) ** 0.5
    return num / den if den > 0 else None


def compute_ccf(a_series: dict[str, int], b_series: dict[str, int],
                 dates: list[str], max_lag: int = 7) -> dict:
    """Compute CCF over lags -max_lag..max_lag. Returns per-lag correlations
    and the peak lag (most positive correlation).

    Each lag also carries a two-sided Pearson p-value (t-distribution
    approximation, df = n-2). Family-wise correction across the (pair,
    story, lag) hypothesis space is applied in `apply_correction()` at
    the top of main(), not here — this function emits raw correlations
    + uncorrected p-values, the orchestrator decides BH vs Bonferroni.
    """
    a_vec = [a_series.get(d, 0) for d in dates]
    b_vec = [b_series.get(d, 0) for d in dates]
    # Skip degenerate series
    if sum(a_vec) == 0 or sum(b_vec) == 0:
        return {"skipped": True, "reason": "zero_variance"}
    correlations: dict[int, float | None] = {}
    p_values: dict[int, float | None] = {}
    for lag in range(-max_lag, max_lag + 1):
        r = pearson_at_lag(a_vec, b_vec, lag)
        correlations[lag] = r
        # Effective n is the paired-sample count at that lag.
        n_paired = max(0, len(a_vec) - abs(lag))
        p_values[lag] = pearson_r_to_p(r, n_paired) if r is not None else None
    valid = {k: v for k, v in correlations.items() if v is not None}
    if not valid:
        return {"skipped": True, "reason": "all_lags_undefined"}
    peak_lag, peak_corr = max(valid.items(), key=lambda kv: kv[1])
    return {
        "skipped": False,
        "n_dates": len(dates),
        "n_a_covered": sum(a_vec),
        "n_b_covered": sum(b_vec),
        "correlations": {str(k): (round(v, 3) if v is not None else None)
                         for k, v in correlations.items()},
        "p_values": {str(k): (round(v, 6) if v is not None else None)
                       for k, v in p_values.items()},
        "peak_lag": peak_lag,
        "peak_correlation": round(peak_corr, 3),
        "peak_p_value": (round(p_values[peak_lag], 6)
                           if p_values.get(peak_lag) is not None else None),
    }


def apply_correction_to_pairs(pair_records: list[dict],
                                correction: str = "bh",
                                q_level: float = 0.05) -> dict:
    """Apply BH/Bonferroni across every (pair, story, lag) hypothesis.

    Mutates pair_records in place: each lag entry's `p_values[str(lag)]`
    is checked against the family-wide threshold, and a parallel
    `significant_lags[str(lag)]` boolean dict is stamped per story.
    Each story also gets `peak_significant: bool`.

    Returns a summary dict for top-level stamping.
    """
    flat_ps: list[float] = []
    locator: list[tuple[int, str, str]] = []
    for pi, rec in enumerate(pair_records):
        for story_key, story in rec.get("by_story", {}).items():
            for lag, p in (story.get("p_values") or {}).items():
                if p is None:
                    continue
                flat_ps.append(p)
                locator.append((pi, story_key, lag))
    if correction == "bh":
        survives, info = bh_filter(flat_ps, q=q_level)
    elif correction == "bonferroni":
        survives, info = bonferroni_filter(flat_ps, alpha=q_level)
    else:  # "none"
        survives = [True] * len(flat_ps)
        info = {"correction": "none", "n_comparisons": len(flat_ps),
                "n_significant": len(flat_ps), "effective_p_critical": None}
    for ok, (pi, story_key, lag) in zip(survives, locator):
        story = pair_records[pi]["by_story"][story_key]
        story.setdefault("significant_lags", {})[lag] = bool(ok)
    # Stamp peak_significant on each (pair, story).
    for rec in pair_records:
        for story in rec.get("by_story", {}).values():
            peak_lag = story.get("peak_lag")
            if peak_lag is None:
                story["peak_significant"] = False
                continue
            sig_map = story.get("significant_lags") or {}
            story["peak_significant"] = bool(sig_map.get(str(peak_lag), False))
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--min-days", type=int, default=30,
                    help="Skip with insufficient_history if <N days available.")
    ap.add_argument("--window-days", type=int, default=30,
                    help="Look back N days into coverage/.")
    ap.add_argument("--max-lag", type=int, default=7,
                    help="Max lag in days for CCF.")
    ap.add_argument("--today", default=None,
                    help="Override 'today' (YYYY-MM-DD); useful for testing.")
    ap.add_argument("--pairs", default=None,
                    help="Comma-separated label substrings to filter pairs.")
    ap.add_argument("--out-dir", default=str(LAG_DIR))
    ap.add_argument(
        "--correction",
        choices=("bh", "bonferroni", "none"),
        default="bh",
        help="Multiple-comparison correction across the (pair, story, "
             "lag) hypothesis family. Default 'bh' (Benjamini-Hochberg "
             "FDR). At our N (pairs × stories × lags ≈ low thousands), "
             "Bonferroni's effective alpha is so small that almost no "
             "lag survives, making the dashboard meaningless.",
    )
    ap.add_argument(
        "--q-level", type=float, default=0.05,
        help="FDR level for BH (or alpha for Bonferroni). Default 0.05.",
    )
    args = ap.parse_args()

    history = load_coverage_history(window_days=args.window_days,
                                      today=args.today)
    n_days_available = len(history)

    if n_days_available < args.min_days:
        print(f"insufficient_history: have {n_days_available} days of coverage matrices, "
              f"need ≥{args.min_days}. Skipping CCF.")
        return 0

    series = time_series_per_bucket_per_story(history)
    dates_sorted = sorted(history.keys())

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pair_filter = (args.pairs.split(",") if args.pairs else None)

    # Phase 1: build per-pair records without correction.
    pair_records: list[dict] = []
    for label, a_bucket, b_bucket, comment in CURATED_PAIRS:
        if pair_filter and not any(f in label for f in pair_filter):
            continue
        per_story: dict[str, dict] = {}
        for story_key in (set(series.get(a_bucket, {}).keys())
                          & set(series.get(b_bucket, {}).keys())):
            a_s = series[a_bucket][story_key]
            b_s = series[b_bucket][story_key]
            r = compute_ccf(a_s, b_s, dates_sorted, max_lag=args.max_lag)
            if not r.get("skipped"):
                per_story[story_key] = r
        pair_records.append({
            "pair_label": label,
            "bucket_a": a_bucket,
            "bucket_b": b_bucket,
            "comment": comment,
            "window_days": args.window_days,
            "n_days_used": n_days_available,
            "max_lag": args.max_lag,
            "n_stories_in_common": len(per_story),
            "by_story": per_story,
        })

    # Phase 2: apply BH (or Bonferroni) across the whole (pair, story,
    # lag) hypothesis family. Mutates pair_records to stamp
    # significant_lags + peak_significant.
    correction_info = apply_correction_to_pairs(
        pair_records, correction=args.correction, q_level=args.q_level
    )

    n_written = 0
    for rec in pair_records:
        out = meta.stamp({
            **rec,
            "correction": {
                "method": args.correction,
                "q_level": args.q_level,
                **correction_info,
            },
        })
        out_path = out_dir / f"{rec['bucket_a']}__{rec['bucket_b']}.json"
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        n_written += 1
        peak_sig_count = sum(
            1 for s in rec["by_story"].values() if s.get("peak_significant")
        )
        print(f"  ✓ {rec['pair_label']:35s} "
              f"stories={len(rec['by_story'])} peak_sig={peak_sig_count}")

    print(f"\nwrote {n_written} CCF artefacts to {out_dir}")
    print(f"correction={args.correction} q={args.q_level} "
          f"n_hypotheses={correction_info.get('n_comparisons', 0)} "
          f"n_significant={correction_info.get('n_significant', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
