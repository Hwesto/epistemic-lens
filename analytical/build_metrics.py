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
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"


def tokens_from_text(text: str) -> Counter:
    """Tokens via the pinned tokeniser (regex + stopwords + normalization)."""
    return Counter(meta.tokenize(text))


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
    vocabs: dict[str, Counter],
    min_count: int | None = None,
    max_doc_freq: int | None = None,
) -> dict[str, list[dict]]:
    """Terms with document frequency <= max_doc_freq, count >= min_count."""
    if min_count is None:
        min_count = int(meta.METRICS["exclusive_vocab_min_count"])
    if max_doc_freq is None:
        max_doc_freq = int(meta.METRICS["exclusive_vocab_max_doc_freq"])
    df = Counter()
    for c in vocabs.values():
        for term in c:
            df[term] += 1

    out: dict[str, list[dict]] = {}
    for bucket, counter in vocabs.items():
        exclusive = [
            {"term": t, "count": n}
            for t, n in counter.items()
            if df[t] <= max_doc_freq and n >= min_count
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
    out = {
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
            f"Jaccard over per-bucket token sets; tokens via meta.tokenize "
            f"(regex={meta.TOKENIZER['regex']!r}, len>={meta.TOKENIZER['min_token_length']}, "
            f"stopword-filtered, plural normalization). Bucket-exclusive = "
            f"doc_freq<={meta.METRICS['exclusive_vocab_max_doc_freq']}, "
            f"count>={meta.METRICS['exclusive_vocab_min_count']}."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return meta.stamp(out)


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
