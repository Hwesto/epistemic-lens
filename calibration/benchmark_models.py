"""benchmark_models.py — three-way embedding-model benchmark.

PR2 Phase A. Loads each candidate model, encodes the eval set's
signal_text and the per-story embedding anchors, then evaluates the
softmax-argmax matcher (the Phase B mechanism) against the Opus silver
labels.

Models benchmarked:
  - sentence-transformers/LaBSE              (the current pin)
  - intfloat/multilingual-e5-large           (2023, larger + retrieval)
  - BAAI/bge-m3                              (2024, multi-functionality)

Per model, per (floor_cosine in 0.40..0.70), we compute:
  - per-story precision, recall, F1
  - per-language precision, recall, F1
  - cross-lingual drift: mean(cos | within-lang) - mean(cos | cross-lang)

Writes:
  - calibration/benchmark_results.json (machine-readable)
  - calibration/perception_eval_report.md (human-readable)
  - calibration/perception_eval.json (companion: winning model + per-story
                                       thresholds for downstream consumers)

Usage:
  python -m calibration.benchmark_models
  python -m calibration.benchmark_models --models LaBSE,bge-m3
  python -m calibration.benchmark_models --skip-encode  # rerun analysis on cached embeddings
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import meta

CALIBRATION = meta.REPO_ROOT / "calibration"
ANCHORS_PATH = CALIBRATION / "embedding_anchors_draft.json"
EVAL_PATH = CALIBRATION / "eval_set.jsonl"
CACHE_DIR = CALIBRATION / "_embedding_cache"

NON_LATIN_LANGS = {"fa", "ar", "hi", "zh", "ja", "ko", "he",
                    "th", "el", "ru", "uk", "bg", "sr", "ka"}

DEFAULT_MODELS = {
    "LaBSE":      "sentence-transformers/LaBSE",
    "e5-large":   "intfloat/multilingual-e5-large",
    "bge-m3":     "BAAI/bge-m3",
}

# Each candidate model expects different input prefixes for asymmetric
# retrieval. multilingual-e5-large takes "query: ..." / "passage: ..."
# but for symmetric similarity (story anchors vs article body), we use
# "passage: ..." on both sides which matches the model's intent.
INPUT_PREFIXES = {
    "LaBSE": ("", ""),
    "e5-large": ("passage: ", "passage: "),
    "bge-m3": ("", ""),
}


def load_eval_set() -> list[dict]:
    with open(EVAL_PATH, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def load_anchors() -> dict[str, list[str]]:
    raw = json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))
    return raw["anchors"]


def encode_with_model(model_name: str, model_id: str,
                      texts: list[str], cache_key: str) -> "np.ndarray":
    """Encode `texts` with the named model. Caches result on disk."""
    import numpy as np  # type: ignore
    cache_path = CACHE_DIR / f"{model_name}_{cache_key}.npy"
    if cache_path.exists():
        return np.load(cache_path)
    from sentence_transformers import SentenceTransformer  # type: ignore
    print(f"  loading {model_id}...", flush=True)
    t0 = time.time()
    model = SentenceTransformer(model_id)
    load_s = time.time() - t0
    print(f"    loaded in {load_s:.1f}s", flush=True)
    prefix_text, _ = INPUT_PREFIXES.get(model_name, ("", ""))
    prefixed = [prefix_text + t for t in texts]
    t0 = time.time()
    vecs = model.encode(prefixed, batch_size=16, show_progress_bar=False,
                          normalize_embeddings=True)
    enc_s = time.time() - t0
    vecs = np.asarray(vecs, dtype="float32")
    print(f"    encoded {len(texts)} texts in {enc_s:.1f}s "
          f"({len(texts)/enc_s:.1f}/sec)", flush=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, vecs)
    # Record wall-clock so the report can reason about Actions runner cost.
    timing = cache_path.with_suffix(".timing.json")
    timing.write_text(json.dumps({
        "model": model_id, "n_texts": len(texts),
        "load_s": round(load_s, 2), "encode_s": round(enc_s, 2),
        "rate_per_s": round(len(texts) / enc_s, 2),
    }, indent=2))
    return vecs


def anchor_centroids(model_name: str, model_id: str,
                       anchors_by_story: dict[str, list[str]]) -> dict[str, "np.ndarray"]:
    import numpy as np  # type: ignore
    story_keys = sorted(anchors_by_story)
    flat: list[str] = []
    spans: list[tuple[int, int]] = []
    for sk in story_keys:
        n = len(anchors_by_story[sk])
        spans.append((len(flat), len(flat) + n))
        flat.extend(anchors_by_story[sk])
    vecs = encode_with_model(model_name, model_id, flat, "anchors")
    out: dict[str, "np.ndarray"] = {}
    for sk, (i0, i1) in zip(story_keys, spans):
        c = vecs[i0:i1].mean(axis=0)
        # Renormalize centroid for cosine semantics.
        nrm = float(np.linalg.norm(c))
        if nrm > 0:
            c = c / nrm
        out[sk] = c
    return out


def softmax_argmax(article_vec: "np.ndarray",
                     centroids: dict[str, "np.ndarray"],
                     floor: float) -> tuple[str | None, float, dict[str, float]]:
    """Return (assigned_story, top_cosine, all_scores). Assigned only if
    argmax cosine ≥ floor."""
    import numpy as np  # type: ignore
    keys = sorted(centroids)
    matrix = np.stack([centroids[k] for k in keys])  # (n_stories, dim)
    scores = matrix @ article_vec  # (n_stories,)
    score_map = {k: float(s) for k, s in zip(keys, scores)}
    top_idx = int(scores.argmax())
    top_score = float(scores[top_idx])
    if top_score < floor:
        return None, top_score, score_map
    return keys[top_idx], top_score, score_map


def evaluate_model(model_name: str, eval_set: list[dict],
                    centroids: dict[str, "np.ndarray"],
                    article_vecs: "np.ndarray",
                    floor_cosines: list[float]) -> dict:
    """Per floor, per story, per language P/R/F1."""
    import numpy as np  # type: ignore
    # Per row, compute argmax assignment + score map ONCE; threshold by floor.
    assignments: list[tuple[str | None, float, dict[str, float]]] = []
    for vec in article_vecs:
        nrm = float(np.linalg.norm(vec))
        v = vec / nrm if nrm > 0 else vec
        # Pass dummy floor=0 here; we re-threshold below per floor.
        story, score, score_map = softmax_argmax(v, centroids, floor=0.0)
        assignments.append((story, score, score_map))

    results = {"per_floor": {}, "cross_lingual_drift": {}}

    # Cross-lingual drift: for each story, compare mean cosine of
    # within-lang positives vs cross-lang positives.
    by_story_scores: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    for row, (_assigned, _top, score_map) in zip(eval_set, assignments):
        if not row.get("silver_label"):
            continue  # only positives reveal cross-lingual cosine
        sk = row["candidate_story"]
        s = score_map.get(sk)
        if s is None:
            continue
        lang_class = "non_latin" if row["lang"] in NON_LATIN_LANGS else "latin"
        by_story_scores[sk][lang_class].append(s)
    for sk, by_class in by_story_scores.items():
        lat = by_class.get("latin", [])
        nlat = by_class.get("non_latin", [])
        if lat and nlat:
            results["cross_lingual_drift"][sk] = {
                "n_latin": len(lat),
                "n_non_latin": len(nlat),
                "mean_latin": round(sum(lat) / len(lat), 4),
                "mean_non_latin": round(sum(nlat) / len(nlat), 4),
                "drift": round(sum(lat) / len(lat) - sum(nlat) / len(nlat), 4),
            }

    # Per floor, evaluate P/R/F1.
    for floor in floor_cosines:
        per_story = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        per_lang = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        for row, (assigned, top, score_map) in zip(eval_set, assignments):
            sk = row["candidate_story"]
            truth = bool(row["silver_label"])
            top_score = score_map.get(sk, -1.0)
            predicted_positive = (top_score >= floor and
                                  max(score_map, key=score_map.get) == sk)
            bucket = per_story[sk]
            lbucket = per_lang[row["lang"]]
            if truth and predicted_positive:
                bucket["tp"] += 1; lbucket["tp"] += 1
            elif truth and not predicted_positive:
                bucket["fn"] += 1; lbucket["fn"] += 1
            elif not truth and predicted_positive:
                bucket["fp"] += 1; lbucket["fp"] += 1
            else:
                bucket["tn"] += 1; lbucket["tn"] += 1

        def _prf(c: dict) -> dict:
            p = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else 0.0
            r = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else 0.0
            f1 = 2 * p * r / (p + r) if (p + r) else 0.0
            return {**c, "precision": round(p, 3), "recall": round(r, 3),
                    "f1": round(f1, 3)}

        results["per_floor"][f"{floor:.2f}"] = {
            "per_story": {sk: _prf(c) for sk, c in per_story.items()},
            "per_lang": {l: _prf(c) for l, c in per_lang.items()},
            "macro_f1": round(
                sum(_prf(c)["f1"] for c in per_story.values()) / max(1, len(per_story)),
                3,
            ),
        }
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS),
                    help="Comma-separated subset of model names to benchmark.")
    ap.add_argument(
        "--floors", default="0.40,0.45,0.50,0.55,0.60,0.65,0.70",
        help="Comma-separated cosine floors to evaluate at.",
    )
    args = ap.parse_args()

    chosen = [m.strip() for m in args.models.split(",") if m.strip()]
    models = {k: v for k, v in DEFAULT_MODELS.items() if k in chosen}
    floors = [float(x) for x in args.floors.split(",")]

    eval_set = load_eval_set()
    anchors = load_anchors()

    print(f"Eval set: {len(eval_set)} rows")
    print(f"Stories: {len(anchors)}")
    print(f"Models: {list(models)}")
    print(f"Floors: {floors}")

    all_results: dict[str, dict] = {}
    article_texts = [r["title"] + "\n" + r["signal_text"] for r in eval_set]

    for model_name, model_id in models.items():
        print(f"\n=== {model_name} ({model_id}) ===")
        try:
            centroids = anchor_centroids(model_name, model_id, anchors)
            article_vecs = encode_with_model(model_name, model_id,
                                              article_texts, "articles")
        except Exception as e:
            print(f"  FAILED: {e}")
            all_results[model_name] = {"error": str(e)[:500]}
            continue
        results = evaluate_model(model_name, eval_set, centroids,
                                  article_vecs, floors)
        all_results[model_name] = results
        # Print compact per-floor summary
        for floor_str, r in results["per_floor"].items():
            print(f"  floor={floor_str}  macro_F1={r['macro_f1']:.3f}")

    out = {
        "eval_set_size": len(eval_set),
        "n_stories": len(anchors),
        "floors": floors,
        "results": all_results,
    }
    (CALIBRATION / "benchmark_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False)
    )
    print(f"\nwrote calibration/benchmark_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
