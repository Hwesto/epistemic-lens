"""build_metrics.py — precompute numeric metrics for daily framing analysis.

Reads briefings/<date>_<story>.json, emits briefings/<date>_<story>_metrics.json
containing pairwise Jaccard similarity, per-bucket isolation, and
bucket-exclusive vocabulary. The Claude analysis pass uses these numbers
verbatim so it doesn't fabricate counts or correlations.

Method matches docs/HORMUZ_CORRELATION.md "Recap of method":
  - Jaccard on per-bucket vocabulary (signal_text + title concatenated)
  - lowercase, stopword-filtered, len>3, light-touch normalization
  - bucket-exclusive: terms with document frequency == 1, count >= 3

Usage:
  python build_metrics.py                            # all today's briefings
  python build_metrics.py briefings/<file>.json      # one file
  python build_metrics.py --date 2026-05-06          # a specific date
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
BRIEFINGS = ROOT / "briefings"

# Stopwords kept conservative — losing too many words flattens the signal.
# The HORMUZ_CORRELATION exemplar used a similar small set.
STOP = set("""
the and that with from this their have been over into about because while
says will could would should might must just like also even then than they
them there here when where what which whose whom into upon onto without
within against between among across through during before after under such
some most more many much these those very only ever never said say saying
told tells telling reports reported reporting according via per amid amidst
toward towards yet still already once also however nevertheless meanwhile
furthermore therefore thus hence indeed perhaps maybe likely possibly
""".split())

# Trailing-character normalization: cheap stand-in for lemmatization.
PLURAL_SUFFIXES = ("ies", "es", "s")


def normalize_token(tok: str) -> str:
    tok = tok.lower()
    if len(tok) > 4:
        for suf in PLURAL_SUFFIXES:
            if tok.endswith(suf) and len(tok) - len(suf) >= 4:
                return tok[: -len(suf)]
    return tok


def tokens_from_text(text: str) -> Counter:
    """Lowercase tokens, len>3, stopword-filtered, lightly normalized."""
    raw = re.findall(r"[A-Za-z]{4,}", text or "")
    out = Counter()
    for t in raw:
        n = normalize_token(t)
        if n in STOP or len(n) < 4:
            continue
        out[n] += 1
    return out


def bucket_vocabularies(corpus: list[dict]) -> dict[str, Counter]:
    """Concat all signal_text+title per bucket → token Counter."""
    by_bucket: dict[str, list[str]] = defaultdict(list)
    for art in corpus:
        b = art.get("bucket", "")
        if not b:
            continue
        text = (art.get("title", "") or "") + "\n" + (art.get("signal_text", "") or "")
        by_bucket[b].append(text)
    return {b: tokens_from_text("\n".join(parts)) for b, parts in by_bucket.items()}


def jaccard(a: Counter, b: Counter) -> float:
    """Jaccard similarity over token *sets* (presence, not frequency)."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def pairwise_jaccard(vocabs: dict[str, Counter]) -> list[dict]:
    """All bucket pairs, sorted by similarity descending."""
    buckets = sorted(vocabs)
    out = []
    for i, a in enumerate(buckets):
        for b in buckets[i + 1 :]:
            out.append(
                {
                    "a": a,
                    "b": b,
                    "jaccard": round(jaccard(vocabs[a], vocabs[b]), 3),
                }
            )
    out.sort(key=lambda r: -r["jaccard"])
    return out


def bucket_isolation(pairs: list[dict], buckets: list[str]) -> list[dict]:
    """Mean Jaccard of each bucket vs every other bucket. Lower = more isolated."""
    sums = defaultdict(float)
    counts = defaultdict(int)
    for p in pairs:
        sums[p["a"]] += p["jaccard"]
        counts[p["a"]] += 1
        sums[p["b"]] += p["jaccard"]
        counts[p["b"]] += 1
    rows = []
    for b in buckets:
        if counts[b]:
            rows.append({"bucket": b, "mean_jaccard": round(sums[b] / counts[b], 3)})
    rows.sort(key=lambda r: r["mean_jaccard"])
    return rows


def bucket_exclusive_vocab(
    vocabs: dict[str, Counter], min_count: int = 3
) -> dict[str, list[dict]]:
    """Terms with document frequency == 1 (one bucket only), count >= min_count."""
    df = Counter()
    for c in vocabs.values():
        for term in c:
            df[term] += 1

    out: dict[str, list[dict]] = {}
    for bucket, counter in vocabs.items():
        exclusive = [
            {"term": t, "count": n}
            for t, n in counter.items()
            if df[t] == 1 and n >= min_count
        ]
        exclusive.sort(key=lambda r: -r["count"])
        out[bucket] = exclusive
    return out


def bucket_sizes(vocabs: dict[str, Counter]) -> dict[str, int]:
    return {b: sum(c.values()) for b, c in vocabs.items()}


def build_metrics(briefing: dict) -> dict:
    corpus = briefing.get("corpus", [])
    vocabs = bucket_vocabularies(corpus)
    buckets = sorted(vocabs)
    pairs = pairwise_jaccard(vocabs)
    return {
        "date": briefing.get("date"),
        "story_key": briefing.get("story_key"),
        "story_title": briefing.get("story_title"),
        "n_buckets": len(buckets),
        "n_articles": len(corpus),
        "buckets": buckets,
        "bucket_token_counts": bucket_sizes(vocabs),
        "pairwise_jaccard": pairs,
        "isolation": bucket_isolation(pairs, buckets),
        "bucket_exclusive_vocab": bucket_exclusive_vocab(vocabs),
        "method": (
            "Jaccard over per-bucket token sets; tokens lowercased, "
            "len>3, stopword-filtered, light plural normalization. "
            "Bucket-exclusive = document frequency 1, count>=3."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def metrics_path_for(briefing_path: Path) -> Path:
    return briefing_path.with_name(briefing_path.stem + "_metrics.json")


def process_one(briefing_path: Path) -> Path:
    briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
    if "corpus" not in briefing:
        raise SystemExit(f"{briefing_path} is not a briefing JSON (no 'corpus' key)")
    metrics = build_metrics(briefing)
    out = metrics_path_for(briefing_path)
    out.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(
        f"  + {briefing_path.name:<48} "
        f"{metrics['n_buckets']:>2} buckets, "
        f"{len(metrics['pairwise_jaccard']):>4} pairs -> {out.name}"
    )
    return out


def briefings_for_date(date: str, dir_: Path = BRIEFINGS) -> list[Path]:
    return sorted(
        p
        for p in dir_.glob(f"{date}_*.json")
        if not p.stem.endswith("_metrics")
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Specific briefing file(s). Default: all briefings for --date.",
    )
    ap.add_argument(
        "--date",
        default=None,
        help="Date in YYYY-MM-DD. Default: today UTC.",
    )
    ap.add_argument("--out-dir", type=Path, default=BRIEFINGS)
    args = ap.parse_args()

    targets: list[Path]
    if args.files:
        targets = list(args.files)
    else:
        date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        targets = briefings_for_date(date, args.out_dir)
        if not targets:
            print(f"No briefings found for {date}")
            return

    for t in targets:
        process_one(t)


if __name__ == "__main__":
    main()
