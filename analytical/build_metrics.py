"""build_metrics.py — precompute numeric metrics for daily framing analysis.

Reads `briefings/<date>_<story>.json`, emits `briefings/<date>_<story>_metrics.json`
containing pairwise similarity, per-bucket isolation, and bucket-exclusive
vocabulary. The Claude analysis pass uses these numbers verbatim so it doesn't
fabricate counts or correlations.

Cross-bucket similarity is **LaBSE bucket-mean cosine on original
signal_text**. LaBSE is multilingual by construction (16+ languages share an
embedding space), so cross-lingual coverage no longer needs a translation
pivot — the original prose carries through. Surfaced as `pairwise_similarity`
and `isolation` with `mean_similarity` per bucket.

Bucket-exclusive vocabulary is computed on the same original text via the
pinned regex tokenizer + multilingual stopwords union. It surfaces tokens
that appear in only one bucket; with raw-original input, this is biased
toward language-specific vocabulary (e.g. French-only buckets surface French
tokens), so the analyzer is instructed to flag language confounding when it
appears.

Buckets at tier `EXCLUDE_QUANT` in `bucket_quality.json` are dropped from
both layers. They still appear in the briefing for narrative coverage; the
metrics layer just ignores them so stub-only aggregator buckets (Reuters via
Google News, China Global Times) don't poison cosine numbers with
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

    Operates on ORIGINAL text (no translation pivot). Buckets at tier
    EXCLUDE_QUANT are dropped entirely (see bucket_quality.json).
    """
    by_bucket: dict[str, list[str]] = defaultdict(list)
    for art in corpus:
        b = art.get("bucket", "")
        if not b:
            continue
        if meta.is_quant_excluded(b):
            continue
        text = (art.get("title") or "") + "\n" + (art.get("signal_text") or "")
        by_bucket[b].append(text)
    return {b: tokens_from_text("\n".join(parts)) for b, parts in by_bucket.items()}


def bucket_original_texts(corpus: list[dict]) -> dict[str, list[str]]:
    """For LaBSE: per-bucket list of original signal_text."""
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
# LaBSE cosine (primary, cross-lingual on originals)
# ---------------------------------------------------------------------------
def labse_pairwise_and_isolation(
    by_bucket: dict[str, list[str]],
    min_tokens_per_bucket: int | None = None,
    vocabs: dict[str, Counter] | None = None,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Returns (pairs, isolation, isolation_excluded_thin, status).

    Buckets with fewer than `min_tokens_per_bucket` tokens (default from
    `meta.METRICS["isolation_min_tokens"]`, falling back to 30) are moved
    into `isolation_excluded_thin` rather than `isolation`. The pairwise
    matrix still includes them so similarity remains directionally available,
    but consumers ranking "most isolated buckets" no longer surface a
    10-token Italian headline alongside multi-thousand-token corpora.
    `vocabs` carries the per-bucket token counts; passed in to avoid a
    redundant tokenization pass.
    """
    if min_tokens_per_bucket is None:
        min_tokens_per_bucket = int(meta.METRICS.get("isolation_min_tokens", 30))
    if len(by_bucket) < 2:
        return [], [], [], {"skipped": True, "reason": "fewer than 2 buckets"}

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return [], [], [], {"skipped": True, "reason": "sentence-transformers/numpy unavailable"}

    model_id = (
        meta.METRICS.get("primary_similarity_model")
        or "sentence-transformers/LaBSE"
    )
    try:
        model = SentenceTransformer(model_id)
    except Exception as e:  # pragma: no cover - exercised by integration test
        return [], [], [], {"skipped": True, "reason": f"model load failed: {e}"[:200]}

    buckets = sorted(by_bucket)
    bucket_vecs: list = []
    for b in buckets:
        try:
            vecs = model.encode(by_bucket[b], batch_size=8, show_progress_bar=False)
        except Exception as e:  # pragma: no cover
            return [], [], [], {"skipped": True, "reason": f"encode failed: {e}"[:200]}
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
                {"a": a, "b": buckets[j], "score": round(float(sim[i, j]), 3)}
            )
    pairs.sort(key=lambda r: -r["score"])

    # Per-bucket token counts decide whether a bucket carries enough body
    # text for its mean_similarity to be editorially meaningful. A bucket
    # with 10 tokens (e.g. an Italian headline-only single-feed bucket)
    # produces a real number but it's not the kind of "isolation" a reader
    # should rank against thousand-token corpora.
    token_counts = {b: int(sum((vocabs or {}).get(b, Counter()).values()))
                    for b in buckets}

    isolation: list[dict] = []
    isolation_excluded_thin: list[dict] = []
    for i, b in enumerate(buckets):
        others = [sim[i, j] for j in range(len(buckets)) if j != i]
        if not others:
            continue
        entry = {
            "bucket": b,
            "mean_similarity": round(float(sum(others) / len(others)), 3),
            "n_tokens": token_counts.get(b, 0),
        }
        if token_counts.get(b, 0) < min_tokens_per_bucket:
            isolation_excluded_thin.append(entry)
        else:
            isolation.append(entry)
    isolation.sort(key=lambda r: r["mean_similarity"])
    isolation_excluded_thin.sort(key=lambda r: r["mean_similarity"])
    return pairs, isolation, isolation_excluded_thin, {
        "skipped": False,
        "model": model_id,
        "isolation_min_tokens": min_tokens_per_bucket,
    }


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
# Population-weighted frame aggregates (C.1)
# ---------------------------------------------------------------------------
def weighted_frame_distribution(analysis: dict,
                                 bootstrap_iters: int = 1000,
                                 ci_pct: tuple[int, int] = (5, 95),
                                 seed: int | None = 42) -> dict:
    """Compute population-weighted frame share from an analysis JSON.

    Closes red-team Flaw F6 (geographic-equality fallacy). Each frame's share
    is the sum of its bucket weights divided by the total weight of all
    buckets that carry any frame in this analysis. The unweighted share is
    published in parentheses so transparency is preserved.

    Phase 1 addition: bootstrap CIs. Buckets are resampled with replacement
    `bootstrap_iters` times; per-frame weighted shares recomputed each time;
    `ci_pct` percentiles of the resulting distribution are emitted as
    `weighted_share_ci_lo` / `weighted_share_ci_hi`. Numpy required; if
    unavailable, CIs are omitted silently and analysis still ships.

    Returns:
      {
        "frames": {frame_id: {"weighted_share", "unweighted_share",
                              "weighted_share_ci_lo", "weighted_share_ci_hi",
                              "weighted_buckets_total", "buckets_total",
                              "low_confidence_share": float},
                   ...},
        "total_weight": float,
        "low_confidence_buckets": [bucket_keys],
        "default_weight_buckets": [bucket_keys not in bucket_weights.json],
        "bootstrap": {"iters": int, "ci_pct": [lo, hi], "seed": int|null} | null,
      }
    """
    frames = analysis.get("frames") or []
    if not frames:
        return {"frames": {}, "total_weight": 0.0,
                "low_confidence_buckets": [], "default_weight_buckets": [],
                "bootstrap": None}

    all_buckets: set[str] = set()
    for f in frames:
        for b in f.get("buckets") or []:
            all_buckets.add(b)
    total_weight = sum(meta.bucket_weight(b) for b in all_buckets)
    if total_weight == 0:
        # Fall back to unweighted if every bucket has weight 0.
        total_weight = float(len(all_buckets))

    by_frame: dict[str, dict] = {}
    low_conf: set[str] = set()
    default_weight: set[str] = set()
    for f in frames:
        fid = f.get("frame_id") or f.get("label") or "UNLABELED"
        buckets = list(f.get("buckets") or [])
        bucket_total_weight = 0.0
        for b in buckets:
            w = meta.bucket_weight(b)
            bucket_total_weight += w
            conf = meta.bucket_weight_confidence(b)
            if conf == "low":
                low_conf.add(b)
            elif conf == "unknown":
                default_weight.add(b)
        if total_weight == 0:
            weighted = 0.0
        else:
            weighted = bucket_total_weight / total_weight
        unweighted = len(buckets) / max(1, len(all_buckets))
        # Track existing entry: a frame may appear in the analysis twice
        # (shouldn't, but be defensive); merge by union of buckets.
        prev = by_frame.get(fid)
        if prev:
            merged_buckets = sorted(set(buckets) | set(prev.get("buckets", [])))
            buckets = merged_buckets
            bucket_total_weight = sum(meta.bucket_weight(b) for b in buckets)
            weighted = bucket_total_weight / total_weight if total_weight else 0.0
            unweighted = len(buckets) / max(1, len(all_buckets))
        by_frame[fid] = {
            "weighted_share": round(weighted, 3),
            "unweighted_share": round(unweighted, 3),
            "weighted_bucket_total": round(bucket_total_weight, 1),
            "buckets_total": len(buckets),
            "buckets": buckets,
        }

    # Bootstrap CIs over weighted_share: resample buckets with replacement,
    # recompute per-frame weighted_share, take percentiles. Skip silently if
    # numpy unavailable so the analysis still ships.
    bootstrap_meta = None
    if bootstrap_iters and bootstrap_iters > 0 and all_buckets:
        try:
            import numpy as np  # type: ignore
            rng = np.random.default_rng(seed)
            bucket_list = sorted(all_buckets)
            # Per-bucket weight + per-bucket frame membership
            bucket_weights = np.array(
                [meta.bucket_weight(b) for b in bucket_list], dtype=float
            )
            bucket_frame_membership: dict[str, "np.ndarray"] = {}
            for fid, info in by_frame.items():
                fb = set(info.get("buckets", []))
                bucket_frame_membership[fid] = np.array(
                    [b in fb for b in bucket_list], dtype=float
                )
            n = len(bucket_list)
            # Vectorised: sample indices once, compute all frames per iter
            shares: dict[str, list[float]] = {fid: [] for fid in by_frame}
            for _ in range(bootstrap_iters):
                idx = rng.integers(0, n, size=n)
                w_sample = bucket_weights[idx]
                tot = float(w_sample.sum()) or 1.0
                for fid, mem in bucket_frame_membership.items():
                    shares[fid].append(float((w_sample * mem[idx]).sum()) / tot)
            for fid, info in by_frame.items():
                arr = np.array(shares[fid])
                info["weighted_share_ci_lo"] = round(
                    float(np.percentile(arr, ci_pct[0])), 3
                )
                info["weighted_share_ci_hi"] = round(
                    float(np.percentile(arr, ci_pct[1])), 3
                )
            bootstrap_meta = {
                "iters": int(bootstrap_iters),
                "ci_pct": list(ci_pct),
                "seed": seed,
                "method": "bucket_resample_with_replacement",
            }
        except ImportError:
            bootstrap_meta = {"skipped": True, "reason": "numpy unavailable"}

    return {
        "frames": by_frame,
        "total_weight": round(total_weight, 1),
        "n_buckets_in_analysis": len(all_buckets),
        "low_confidence_buckets": sorted(low_conf),
        "default_weight_buckets": sorted(default_weight),
        "weighting_formula": "weight = population_m * audience_reach (bucket_weights.json)",
        "bootstrap": bootstrap_meta,
    }


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------
def build_metrics(briefing: dict) -> dict:
    corpus = briefing.get("corpus", [])
    vocabs = bucket_vocabularies(corpus)
    by_bucket_orig = bucket_original_texts(corpus)
    buckets = sorted(vocabs)

    pairs, isolation, isolation_excluded_thin, labse_status = (
        labse_pairwise_and_isolation(by_bucket_orig, vocabs=vocabs)
    )

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
        "pairwise_similarity": pairs,
        "isolation": isolation,
        "isolation_excluded_thin": isolation_excluded_thin,
        "embedding_status": labse_status,
        "bucket_exclusive_vocab": bucket_exclusive_vocab(vocabs),
        "method": (
            "Primary: LaBSE bucket-mean cosine on original signal_text "
            "(cross-lingual; skipped gracefully if model unavailable). "
            "Bucket-exclusive: tokens with doc_freq<="
            f"{meta.METRICS['exclusive_vocab_max_doc_freq']} and count>="
            f"{meta.METRICS['exclusive_vocab_min_count']}, "
            "tokenizer=meta.tokenize via "
            f"{meta.TOKENIZER['regex']!r}, len>={meta.TOKENIZER['min_token_length']}, "
            "stopword-filtered, plural normalization. Operates on raw "
            "originals; analyzer flags language confounding."
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
    status = metrics["embedding_status"]
    status_summary = "labse=skipped" if status.get("skipped") else "labse=ok"
    excluded_summary = (
        f"excluded={len(metrics['buckets_excluded_quant'])}"
        if metrics['buckets_excluded_quant'] else ""
    )
    print(
        f"  + {briefing_path.name:<48} "
        f"{metrics['n_buckets']:>2} buckets, "
        f"{len(metrics['pairwise_similarity']):>4} pairs "
        f"{status_summary} {excluded_summary} -> {out.name}".rstrip()
    )
    return out


def briefings_for_date(date: str, dir_: Path = BRIEFINGS) -> list[Path]:
    return sorted(
        p
        for p in dir_.glob(f"{date}_*.json")
        if not p.stem.endswith("_metrics")
    )


def augment_metrics_with_analysis(metrics_path: Path,
                                    analysis_path: Path) -> dict | None:
    """Read existing metrics JSON; compute weighted_frame_distribution from
    the analysis JSON; write the merged block back. Returns the augmented
    dict (or None when either input is missing).

    Intended to run AFTER the analyze step has written the analysis JSON —
    the metrics builder runs upstream of analysis (no frames yet), so
    weighted_frame_distribution is necessarily a post-analyze augmentation.
    Idempotent: re-running produces the same merged file.
    """
    if not (metrics_path.exists() and analysis_path.exists()):
        return None
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    wfd = weighted_frame_distribution(analysis)
    if not wfd.get("frames"):
        return metrics
    metrics["weighted_frame_distribution"] = wfd
    metrics_path.write_text(
        json.dumps(meta.stamp(metrics), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return metrics


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
    ap.add_argument(
        "--augment-from-analysis",
        action="store_true",
        help="Post-analyze mode: re-read existing _metrics.json plus the "
             "matching analyses/<date>_<story>.json and merge in the "
             "weighted_frame_distribution block. weighted_frame_distribution "
             "requires the analysis output (frame buckets) which doesn't "
             "exist yet at the upstream metrics-build time. Idempotent.",
    )
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

    if args.augment_from_analysis:
        analyses_dir = ROOT / "analyses"
        n_augmented = 0
        for briefing_path in targets:
            metrics_path = metrics_path_for(briefing_path)
            analysis_path = analyses_dir / briefing_path.name
            result = augment_metrics_with_analysis(metrics_path, analysis_path)
            if result is None:
                continue
            wfd = result.get("weighted_frame_distribution") or {}
            n_frames = len((wfd.get("frames") or {}))
            if n_frames:
                n_augmented += 1
                print(f"  + {metrics_path.name:<48} "
                      f"weighted_frame_distribution: {n_frames} frames")
        print(f"\n{n_augmented} metrics file(s) augmented with weighted_frame_distribution.")
        return

    for t in targets:
        process_one(t)


if __name__ == "__main__":
    main()
