"""build_metrics.py — precompute numeric metrics for daily framing analysis.

Reads `briefings/<date>_<story>.json`, emits `briefings/<date>_<story>_metrics.json`
containing pairwise similarity, per-bucket isolation, and bucket-exclusive
vocabulary. The Claude analysis pass uses these numbers verbatim so it doesn't
fabricate counts or correlations.

Three similarity layers as of meta_version 5.0.0:

  1. **TF-IDF cosine** (primary). Frequency-weighted, length-normalized
     vocabulary similarity over the English-pivot text (`signal_text_en` /
     `title_en`). Replaces token-set Jaccard as the canonical metric — sets
     ignored frequency, which the red-team report flagged as Flaw F15.
  2. **Jaccard legacy** (kept). Same set-intersection-over-union as pre-5.0.0
     for diff-run continuity. Surfaced as `pairwise_jaccard_legacy` and
     `isolation_jaccard_legacy`. Will be removed in 6.0.0.
  3. **LaBSE embedding cosine** (parallel). Cross-lingual sentence-embedding
     similarity over the ORIGINAL `signal_text` (not translated — LaBSE is
     cross-lingual by design). When the lexical and semantic layers diverge
     for a bucket pair, the corpus is doing something non-obvious. Optional
     dependency: gracefully skipped if sentence-transformers / model isn't
     available.

Buckets at tier `EXCLUDE_QUANT` in `bucket_quality.json` are dropped from all
three layers. They still appear in the briefing for narrative coverage; the
metrics layer just ignores them so stub-only aggregator buckets (Reuters via
Google News, China Global Times) don't poison Jaccard/cosine numbers with
title-only statistics.

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


# ---------------------------------------------------------------------------
# Tokenization (delegates to meta.tokenize)
# ---------------------------------------------------------------------------
def tokens_from_text(text: str) -> Counter:
    """Tokens via the pinned tokeniser (regex + stopwords + normalization)."""
    return Counter(meta.tokenize(text))


def bucket_vocabularies(corpus: list[dict]) -> dict[str, Counter]:
    """Concat all title+signal_text per bucket → token Counter.

    Reads pivot-language fields (`title_en`, `signal_text_en`) when available
    via meta.effective_title / meta.effective_text. Buckets at tier
    EXCLUDE_QUANT are dropped entirely (see bucket_quality.json).
    """
    by_bucket: dict[str, list[str]] = defaultdict(list)
    for art in corpus:
        b = art.get("bucket", "")
        if not b:
            continue
        if meta.is_quant_excluded(b):
            continue
        text = meta.effective_title(art) + "\n" + meta.effective_text(art)
        by_bucket[b].append(text)
    return {b: tokens_from_text("\n".join(parts)) for b, parts in by_bucket.items()}


def bucket_original_texts(corpus: list[dict]) -> dict[str, list[str]]:
    """For LaBSE: per-bucket list of ORIGINAL signal_text (not translated)."""
    by_bucket: dict[str, list[str]] = defaultdict(list)
    for art in corpus:
        b = art.get("bucket", "")
        if not b or meta.is_quant_excluded(b):
            continue
        # LaBSE handles 16+ langs natively; truncate to a reasonable length.
        body = (art.get("signal_text") or "")[:1500]
        title = (art.get("title") or "")
        if body or title:
            by_bucket[b].append(f"{title}\n{body}".strip())
    return by_bucket


# ---------------------------------------------------------------------------
# TF-IDF cosine (primary)
# ---------------------------------------------------------------------------
def tfidf_pairwise_and_isolation(
    vocabs: dict[str, Counter],
) -> tuple[list[dict], list[dict]]:
    """Compute pairwise TF-IDF cosine and per-bucket mean (isolation)."""
    if len(vocabs) < 2:
        return [], []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        return [], []

    buckets = sorted(vocabs)
    docs = [" ".join(vocabs[b].elements()) for b in buckets]
    if not any(d.strip() for d in docs):
        return [], []

    vectorizer = TfidfVectorizer(min_df=1, lowercase=False, token_pattern=r"\S+")
    X = vectorizer.fit_transform(docs)
    sim = cosine_similarity(X)

    pairs: list[dict] = []
    for i, a in enumerate(buckets):
        for j in range(i + 1, len(buckets)):
            pairs.append(
                {"a": a, "b": buckets[j], "score": round(float(sim[i, j]), 3)}
            )
    pairs.sort(key=lambda r: -r["score"])

    isolation: list[dict] = []
    for i, b in enumerate(buckets):
        others = [sim[i, j] for j in range(len(buckets)) if j != i]
        if others:
            isolation.append(
                {"bucket": b, "mean_similarity": round(float(sum(others) / len(others)), 3)}
            )
    isolation.sort(key=lambda r: r["mean_similarity"])
    return pairs, isolation


# ---------------------------------------------------------------------------
# Jaccard legacy (kept for diff-runs)
# ---------------------------------------------------------------------------
def _jaccard(a: Counter, b: Counter) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def jaccard_legacy(
    vocabs: dict[str, Counter],
) -> tuple[list[dict], list[dict]]:
    if len(vocabs) < 2:
        return [], []
    buckets = sorted(vocabs)
    pairs: list[dict] = []
    for i, a in enumerate(buckets):
        for j in range(i + 1, len(buckets)):
            pairs.append(
                {"a": a, "b": buckets[j], "jaccard": round(_jaccard(vocabs[a], vocabs[buckets[j]]), 3)}
            )
    pairs.sort(key=lambda r: -r["jaccard"])

    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for p in pairs:
        sums[p["a"]] += p["jaccard"]
        counts[p["a"]] += 1
        sums[p["b"]] += p["jaccard"]
        counts[p["b"]] += 1
    isolation: list[dict] = []
    for b in buckets:
        if counts[b]:
            isolation.append(
                {"bucket": b, "mean_jaccard": round(sums[b] / counts[b], 3)}
            )
    isolation.sort(key=lambda r: r["mean_jaccard"])
    return pairs, isolation


# ---------------------------------------------------------------------------
# LaBSE parallel (semantic, cross-lingual on originals)
# ---------------------------------------------------------------------------
def labse_pairwise_and_isolation(
    by_bucket: dict[str, list[str]],
) -> tuple[list[dict], list[dict], dict | None]:
    """Returns (pairs, isolation, status). status carries reason if skipped."""
    if len(by_bucket) < 2:
        return [], [], {"skipped": True, "reason": "fewer than 2 buckets"}

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return [], [], {"skipped": True, "reason": "sentence-transformers/numpy unavailable"}

    model_id = (
        meta.METRICS.get("embedding_parallel", {}).get("model")
        or "sentence-transformers/LaBSE"
    )
    try:
        model = SentenceTransformer(model_id)
    except Exception as e:  # pragma: no cover - exercised by integration test
        return [], [], {"skipped": True, "reason": f"model load failed: {e}"[:200]}

    buckets = sorted(by_bucket)
    bucket_vecs: list = []
    for b in buckets:
        try:
            vecs = model.encode(by_bucket[b], batch_size=8, show_progress_bar=False)
        except Exception as e:  # pragma: no cover
            return [], [], {"skipped": True, "reason": f"encode failed: {e}"[:200]}
        if hasattr(vecs, "mean"):
            mean = vecs.mean(axis=0)
        else:
            mean = np.array(vecs).mean(axis=0)
        bucket_vecs.append(mean)

    M = np.array(bucket_vecs, dtype=float)
    norms = np.linalg.norm(M, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    Mn = M / norms
    sim = Mn @ Mn.T

    pairs: list[dict] = []
    for i, a in enumerate(buckets):
        for j in range(i + 1, len(buckets)):
            pairs.append(
                {"a": a, "b": buckets[j], "embedding_score": round(float(sim[i, j]), 3)}
            )
    pairs.sort(key=lambda r: -r["embedding_score"])

    isolation: list[dict] = []
    for i, b in enumerate(buckets):
        others = [sim[i, j] for j in range(len(buckets)) if j != i]
        if len(others) > 0:
            isolation.append(
                {
                    "bucket": b,
                    "mean_embedding_similarity": round(float(sum(others) / len(others)), 3),
                }
            )
    isolation.sort(key=lambda r: r["mean_embedding_similarity"])
    return pairs, isolation, {"skipped": False, "model": model_id}


# ---------------------------------------------------------------------------
# Exclusive vocab (unchanged, but tier exclusion happens upstream)
# ---------------------------------------------------------------------------
def bucket_exclusive_vocab(
    vocabs: dict[str, Counter],
    min_count: int | None = None,
    max_doc_freq: int | None = None,
) -> dict[str, list[dict]]:
    if min_count is None:
        min_count = int(meta.METRICS["exclusive_vocab_min_count"])
    if max_doc_freq is None:
        max_doc_freq = int(meta.METRICS["exclusive_vocab_max_doc_freq"])
    df: Counter = Counter()
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


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------
def build_metrics(briefing: dict) -> dict:
    corpus = briefing.get("corpus", [])
    vocabs = bucket_vocabularies(corpus)
    by_bucket_orig = bucket_original_texts(corpus)
    buckets = sorted(vocabs)

    pairs_tfidf, iso_tfidf = tfidf_pairwise_and_isolation(vocabs)
    pairs_jaccard_legacy, iso_jaccard_legacy = jaccard_legacy(vocabs)
    pairs_labse, iso_labse, labse_status = labse_pairwise_and_isolation(by_bucket_orig)

    excluded = sorted(
        b for b in {a.get("bucket", "") for a in corpus}
        if b and meta.is_quant_excluded(b)
    )

    out = {
        "date": briefing.get("date"),
        "story_key": briefing.get("story_key"),
        "story_title": briefing.get("story_title"),
        "n_buckets": len(buckets),
        "n_articles": len(corpus),
        "buckets": buckets,
        "buckets_excluded_quant": excluded,
        "bucket_token_counts": bucket_sizes(vocabs),
        "pairwise_similarity": pairs_tfidf,
        "isolation": iso_tfidf,
        "pairwise_jaccard_legacy": pairs_jaccard_legacy,
        "isolation_jaccard_legacy": iso_jaccard_legacy,
        "pairwise_embedding_similarity": pairs_labse,
        "isolation_embedding": iso_labse,
        "embedding_status": labse_status,
        "bucket_exclusive_vocab": bucket_exclusive_vocab(vocabs),
        "method": (
            "primary: TF-IDF cosine over per-bucket pivot-language token "
            "concatenations (sklearn TfidfVectorizer, min_df=1). "
            "Tokeniser: meta.tokenize via "
            f"{meta.TOKENIZER['regex']!r}, len>={meta.TOKENIZER['min_token_length']}, "
            "stopword-filtered, plural normalization. "
            "Bucket-exclusive: doc_freq<="
            f"{meta.METRICS['exclusive_vocab_max_doc_freq']}, count>="
            f"{meta.METRICS['exclusive_vocab_min_count']}. "
            "Parallel: LaBSE bucket-mean cosine on ORIGINAL signal_text "
            "(cross-lingual; skipped gracefully if model unavailable). "
            "Legacy: token-set Jaccard kept for diff-runs."
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
    embedding = metrics["embedding_status"]
    embedding_summary = (
        "labse=skipped" if embedding.get("skipped")
        else "labse=ok"
    )
    excluded_summary = (
        f"excluded={len(metrics['buckets_excluded_quant'])}"
        if metrics['buckets_excluded_quant'] else ""
    )
    print(
        f"  + {briefing_path.name:<48} "
        f"{metrics['n_buckets']:>2} buckets, "
        f"{len(metrics['pairwise_similarity']):>4} pairs "
        f"{embedding_summary} {excluded_summary} -> {out.name}".rstrip()
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
