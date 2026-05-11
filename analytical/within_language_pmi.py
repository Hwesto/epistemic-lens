"""within_language_pmi.py — log-odds bigram associations within language groups.

Per (bucket, language), find bigrams that appear at a substantially higher
rate than in the same-language cohort. Uses **log-odds-with-smoothing**
(Monroe, Colaresi & Quinn 2008, "Fightin' Words") which handles small N
gracefully by adding a 0.5 prior to all counts; emits a Z-score so the
consumer can filter by significance.

Why log-odds, not raw PMI? PMI rewards rare-co-occurrence over magnitude:
a bigram that appears once in a bucket and zero in cohort scores infinitely
high. Log-odds with the variance estimate (z = log_odds / sqrt(var))
penalises low-N bigrams appropriately. The trade-off is interpretability:
PMI says "X co-occurs with Y N times the chance baseline"; log-odds says
"this bucket prefers (X, Y) more than the cohort, with significance Z."

Bigram construction: adjacent pairs in the **stopword-filtered** token
sequence (i.e., over the same tokens that `meta.tokenize` returns). Filters
opinion items by default (Phase 1 section tagging).

Inputs: a briefing JSON.
Output: per (bucket, lang) top-k bigram-association list.

Usage:
  python -m analytical.within_language_pmi
  python -m analytical.within_language_pmi --date 2026-05-08
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"


def bucket_lang_bigrams(corpus: list[dict]) -> dict[tuple[str, str], Counter]:
    """Per (bucket, lang), bigram Counter over stopword-filtered tokens."""
    by_bl: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for art in corpus:
        b = art.get("bucket")
        l = art.get("lang", "en")
        if not b:
            continue
        if (art.get("section") or "news") == "opinion":
            continue
        text = (art.get("title") or "") + "\n" + (art.get("signal_text") or "")
        toks = meta.tokenize(text)
        for i in range(len(toks) - 1):
            by_bl[(b, l)][(toks[i], toks[i + 1])] += 1
    return by_bl


def log_odds_with_prior(a: int, b: int,
                         total_a: int, total_b: int,
                         alpha: float = 0.5) -> tuple[float, float, float]:
    """Smoothed log-odds + variance + Z-score per Monroe/Colaresi/Quinn 2008.

    a = count of bigram in bucket
    b = count of bigram in cohort
    total_a, total_b = totals across each corpus
    alpha = Dirichlet smoothing prior (default 0.5 — Jeffreys prior)
    Returns (log_odds, variance, z_score).
    """
    a_s = a + alpha
    b_s = b + alpha
    a_total_s = total_a + alpha
    b_total_s = total_b + alpha
    # log-odds-ratio
    odds_a = a_s / max(1e-9, (a_total_s - a_s))
    odds_b = b_s / max(1e-9, (b_total_s - b_s))
    log_odds = math.log(odds_a) - math.log(odds_b)
    # Variance
    var = (1.0 / a_s) + (1.0 / b_s)
    z = log_odds / math.sqrt(var) if var > 0 else 0.0
    return log_odds, var, z


def compute_bigram_associations(bucket_bigrams: Counter,
                                  cohort_bigrams: Counter,
                                  min_count: int = 2,
                                  z_threshold: float = 1.96,
                                  top_k: int = 25) -> list[dict]:
    """Find bigrams in `bucket_bigrams` that score above z_threshold against
    `cohort_bigrams`. Returns the top-k by Z-score, descending."""
    total_b = sum(bucket_bigrams.values()) or 1
    total_c = sum(cohort_bigrams.values()) or 1
    out: list[dict] = []
    for bg, a in bucket_bigrams.items():
        if a < min_count:
            continue
        c = int(cohort_bigrams.get(bg, 0))
        log_odds, var, z = log_odds_with_prior(a, c, total_b, total_c)
        if z < z_threshold:
            continue
        rate_in_bucket = a / total_b
        rate_in_cohort = c / total_c if total_c else 0.0
        # Lift = ratio of rates (for human readability alongside log_odds)
        lift = (rate_in_bucket / rate_in_cohort
                if rate_in_cohort > 0 else None)
        out.append({
            "bigram": list(bg),
            "count_in_bucket": a,
            "count_in_cohort": c,
            "log_odds": round(log_odds, 3),
            "z_score": round(z, 2),
            "lift": round(lift, 2) if lift is not None else None,
            "rate_in_bucket": round(rate_in_bucket, 6),
            "rate_in_cohort": round(rate_in_cohort, 6),
        })
    out.sort(key=lambda r: -r["z_score"])
    return out[:top_k]


def within_language_pmi(briefing: dict,
                         min_count: int = 2,
                         z_threshold: float = 1.96,
                         top_k: int = 25) -> dict:
    """Top-level: per (bucket, lang), score bigrams vs same-language cohort."""
    corpus = briefing.get("corpus") or []
    bl_bigrams = bucket_lang_bigrams(corpus)
    if not bl_bigrams:
        return {"by_bucket": {}, "n_languages": 0}

    by_lang: dict[str, list[tuple[str, Counter]]] = defaultdict(list)
    for (b, l), counter in bl_bigrams.items():
        by_lang[l].append((b, counter))

    by_bucket: dict[str, dict] = {}
    for lang, bucket_counters in by_lang.items():
        if len(bucket_counters) < 2:
            continue
        cohort_full: Counter = Counter()
        for _, c in bucket_counters:
            cohort_full.update(c)
        for bucket, c in bucket_counters:
            cohort_excl = cohort_full - c
            assoc = compute_bigram_associations(
                c, cohort_excl,
                min_count=min_count, z_threshold=z_threshold, top_k=top_k,
            )
            by_bucket[bucket] = {
                "lang": lang,
                "n_buckets_in_lang_cohort": len(bucket_counters),
                "n_bigrams_in_bucket": int(sum(c.values())),
                "n_bigrams_in_cohort": int(sum(cohort_excl.values())),
                "associations": assoc,
            }

    return {
        "by_bucket": by_bucket,
        "n_languages": len(by_lang),
        "method": "log_odds_with_jeffreys_prior",
        "params": {
            "min_count": min_count,
            "z_threshold": z_threshold,
            "top_k": top_k,
            "smoothing_alpha": 0.5,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--out-dir", default=str(BRIEFINGS))
    ap.add_argument("--top-k", type=int, default=25)
    args = ap.parse_args()

    if args.files:
        targets = [Path(f) for f in args.files]
    else:
        date = args.date or datetime.now(timezone.utc).date().isoformat()
        targets = [
            p for p in BRIEFINGS.glob(f"{date}_*.json")
            if not p.stem.endswith(("_metrics", "_within_lang_llr",
                                    "_within_lang_pmi", "_headline"))
        ]
    if not targets:
        print("No briefings to process.", file=sys.stderr)
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in targets:
        try:
            briefing = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
            print(f"FAIL: {p}: {e}", file=sys.stderr)
            continue
        result = within_language_pmi(briefing, top_k=args.top_k)
        result = meta.stamp({
            "date": briefing.get("date"),
            "story_key": briefing.get("story_key"),
            "story_title": briefing.get("story_title"),
            **result,
        })
        out_path = out_dir / f"{p.stem}_within_lang_pmi.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        n_buckets = len(result["by_bucket"])
        n_assoc = sum(len(v["associations"])
                      for v in result["by_bucket"].values())
        print(f"  {p.stem:50s} buckets_with_cohort={n_buckets}  associations={n_assoc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
