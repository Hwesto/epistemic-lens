"""within_language_llr.py — Dunning log-likelihood ratio for distinctive vocab.

Replaces the crude `bucket_exclusive_vocab` heuristic (`count≥3,
doc_freq≤1`) with a proper statistical test. For each (bucket, language)
in a story's briefing, computes LLR for every term against the
**same-language** cohort (the union of all other buckets that share the
bucket's dominant language). Emits effect size (log rate ratio) and a
chi-squared p-value.

Dunning, Ted. "Accurate methods for the statistics of surprise and
coincidence." *Computational Linguistics* 19, no. 1 (1993): 61-74.

The same-language constraint is what closes the language-confounding
critique: an Italian-only bucket's distinctive terms used to surface
Italian function words ("hanno", "stato"); now they're compared only to
other Italian-language buckets, so the test reflects framing, not
language identification.

Inputs: a briefing JSON with a `corpus[]` array carrying `bucket` + `lang`
+ `title` + `signal_text` per article.

Output: per-bucket distinctive-vocabulary list, each entry carrying:
  term, count_in_bucket, count_in_cohort, rate_in_bucket, rate_in_cohort,
  llr, log_ratio, p_value.

Filters applied:
  - min_term_count (default 5): bucket must use the term at least this often.
  - min_buckets_in_lang (default 2): need ≥2 buckets sharing the language.
  - p_value ≤ 0.001 (default; Bonferroni-conservative — the test runs over
    thousands of terms per language).
  - Over-represented only (rate_in_bucket > rate_in_cohort).

Usage:
  python -m analytical.within_language_llr                       # all today's
  python -m analytical.within_language_llr --date 2026-05-08
  python -m analytical.within_language_llr briefings/<file>.json # one file
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


def bucket_lang_vocabularies(corpus: list[dict]) -> dict[tuple[str, str], Counter]:
    """Per (bucket, lang), token Counter of title + signal_text."""
    by_bl: dict[tuple[str, str], list[str]] = defaultdict(list)
    for art in corpus:
        b = art.get("bucket")
        l = art.get("lang", "en")
        if not b:
            continue
        if (art.get("section") or "news") == "opinion":
            continue  # opinion items excluded by default (P1 section tagging)
        text = (art.get("title") or "") + "\n" + (art.get("signal_text") or "")
        by_bl[(b, l)].append(text)
    return {
        bl: Counter(meta.tokenize("\n".join(parts)))
        for bl, parts in by_bl.items()
    }


def _llpart(o: float, e: float) -> float:
    if o <= 0 or e <= 0:
        return 0.0
    return o * math.log(o / e)


def compute_llr_for_bucket(bucket_counter: Counter,
                            cohort_counter: Counter,
                            min_term_count: int = 5,
                            top_k: int = 20,
                            p_threshold: float = 0.001) -> list[dict]:
    """Run Dunning LLR for each term in `bucket_counter` against the
    `cohort_counter` (union of other same-language buckets). Returns the
    top-k over-represented terms by LLR, each with effect size + p-value.

    `cohort_counter` MUST exclude this bucket's tokens (caller is
    responsible for the subtraction)."""
    try:
        from scipy import stats  # type: ignore
        have_scipy = True
    except ImportError:
        have_scipy = False

    bucket_total = sum(bucket_counter.values()) or 1
    cohort_total = sum(cohort_counter.values()) or 1

    out: list[dict] = []
    for term, a in bucket_counter.items():
        if a < min_term_count:
            continue
        b = int(cohort_counter.get(term, 0))
        c = bucket_total - a
        d = cohort_total - b
        if c < 0 or d < 0:
            continue
        N = a + b + c + d
        if N == 0:
            continue
        E_a = (a + b) * (a + c) / N
        E_b = (a + b) * (b + d) / N
        E_c = (c + d) * (a + c) / N
        E_d = (c + d) * (b + d) / N
        llr = 2.0 * (_llpart(a, E_a) + _llpart(b, E_b)
                     + _llpart(c, E_c) + _llpart(d, E_d))
        rate_in_bucket = a / bucket_total
        rate_in_cohort = b / cohort_total if cohort_total else 0.0
        if rate_in_bucket <= rate_in_cohort:
            continue  # only over-represented terms
        log_ratio = (math.log(rate_in_bucket / rate_in_cohort)
                     if rate_in_cohort > 0 else None)
        if have_scipy:
            p = float(1 - stats.chi2.cdf(llr, df=1))
        else:
            p = None
        if p is not None and p > p_threshold:
            continue
        out.append({
            "term": term,
            "count_in_bucket": a,
            "count_in_cohort": b,
            "rate_in_bucket": round(rate_in_bucket, 5),
            "rate_in_cohort": round(rate_in_cohort, 5),
            "llr": round(llr, 3),
            "log_ratio": round(log_ratio, 3) if log_ratio is not None else None,
            "p_value": (round(p, 6) if p is not None else None),
        })
    out.sort(key=lambda r: -r["llr"])
    return out[:top_k]


def within_language_llr(briefing: dict,
                         min_term_count: int = 5,
                         top_k: int = 20,
                         p_threshold: float = 0.001) -> dict:
    """Top-level: run LLR per bucket against same-language cohort."""
    corpus = briefing.get("corpus") or []
    bl_vocabs = bucket_lang_vocabularies(corpus)
    if not bl_vocabs:
        return {"by_bucket": {}, "n_languages": 0}

    # Group by language
    by_lang: dict[str, list[tuple[str, Counter]]] = defaultdict(list)
    for (b, l), c in bl_vocabs.items():
        by_lang[l].append((b, c))

    by_bucket: dict[str, dict] = {}
    for lang, bcs in by_lang.items():
        if len(bcs) < 2:
            continue  # cohort needs ≥2 buckets in the language
        # Build full cohort counter once (sum of all bucket counters in this lang)
        cohort_full: Counter = Counter()
        for _, c in bcs:
            cohort_full.update(c)
        for bucket, c in bcs:
            # Cohort excludes this bucket
            cohort_excl = cohort_full - c
            distinctive = compute_llr_for_bucket(
                c, cohort_excl,
                min_term_count=min_term_count,
                top_k=top_k,
                p_threshold=p_threshold,
            )
            by_bucket[bucket] = {
                "lang": lang,
                "n_buckets_in_lang_cohort": len(bcs),
                "n_tokens_in_bucket": int(sum(c.values())),
                "n_tokens_in_cohort": int(sum(cohort_excl.values())),
                "distinctive_terms": distinctive,
            }

    return {
        "by_bucket": by_bucket,
        "n_languages": len(by_lang),
        "method": "dunning_llr",
        "params": {
            "min_term_count": min_term_count,
            "top_k": top_k,
            "p_threshold": p_threshold,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD; default: today UTC.")
    ap.add_argument("files", nargs="*",
                    help="Specific briefing file(s); default: all for --date.")
    ap.add_argument("--out-dir", default=str(BRIEFINGS),
                    help="Output dir for *_within_lang_llr.json.")
    ap.add_argument("--top-k", type=int, default=20)
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
        print(f"No briefings to process.", file=sys.stderr)
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in targets:
        try:
            briefing = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
            print(f"FAIL: {p}: {e}", file=sys.stderr)
            continue
        result = within_language_llr(briefing, top_k=args.top_k)
        result = meta.stamp({
            "date": briefing.get("date"),
            "story_key": briefing.get("story_key"),
            "story_title": briefing.get("story_title"),
            **result,
        })
        out_path = out_dir / f"{p.stem}_within_lang_llr.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        n_buckets = len(result["by_bucket"])
        n_terms_total = sum(len(v["distinctive_terms"])
                            for v in result["by_bucket"].values())
        print(f"  {p.stem:50s} buckets_with_cohort={n_buckets}  distinctive_terms={n_terms_total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
