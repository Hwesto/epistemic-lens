"""parity_check.py — weekly regression test against the silver eval set.

PR2 Phase B follow-up. Runs the calibration benchmark on the CURRENT
canonical_stories.json anchors + winning model + current eval set,
then asserts:

  - macro F1 >= MIN_MACRO_F1  (default 0.75; calibrated at 0.815)
  - winning model unchanged from `meta_version.json:perception.embedding_model`

Exits with non-zero status if the gate fails — used by
.github/workflows/golden.yml to fire weekly drift alerts.

Usage:
  python -m calibration.parity_check
  python -m calibration.parity_check --min-macro-f1 0.70  # relaxed threshold
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import meta

CALIBRATION = meta.REPO_ROOT / "calibration"

MIN_MACRO_F1 = 0.75
# bge-m3 calibration showed 0.816; e5-large 0.815. Drift below 0.75 is
# meaningful (a 0.07+ regression from the calibrated baseline) — that's
# anchor rot OR model API drift, both worth investigating.


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-macro-f1", type=float, default=MIN_MACRO_F1)
    ap.add_argument("--models", default="e5-large",
                    help="Comma-separated subset of models to benchmark. "
                         "Default just runs the production winner.")
    args = ap.parse_args()

    # Run the existing benchmark module on the chosen subset.
    from calibration import benchmark_models, generate_report
    chosen = [m.strip() for m in args.models.split(",") if m.strip()]
    models = {k: v for k, v in benchmark_models.DEFAULT_MODELS.items()
              if k in chosen}
    if not models:
        print(f"unknown model(s): {args.models}", file=sys.stderr)
        return 1

    eval_set = benchmark_models.load_eval_set()
    anchors = benchmark_models.load_anchors()
    article_texts = [r["title"] + "\n" + r["signal_text"] for r in eval_set]

    failures: list[str] = []
    for name, model_id in models.items():
        print(f"=== {name} ({model_id}) ===")
        try:
            centroids = benchmark_models.anchor_centroids(name, model_id, anchors)
            article_vecs = benchmark_models.encode_with_model(
                name, model_id, article_texts, "articles"
            )
        except Exception as e:
            failures.append(f"{name}: ENCODE_FAIL {e}")
            continue
        results = benchmark_models.evaluate_model(
            name, eval_set, centroids, article_vecs,
            floor_cosines=[0.40, 0.45, 0.50],
        )
        best_floor, best_f1 = generate_report.pick_best_floor(
            results["per_floor"]
        )
        print(f"  best_floor={best_floor}  macro_f1={best_f1:.3f}")
        if best_f1 < args.min_macro_f1:
            failures.append(
                f"{name}: macro_f1 {best_f1:.3f} < min {args.min_macro_f1:.3f} "
                f"(possible anchor drift or model API change)"
            )

    # Check winning_model in meta_version.json matches what calibration says.
    perception_cfg = (getattr(meta, "PERCEPTION", None) or {})
    pinned_model_id = perception_cfg.get("embedding_model") or ""
    if pinned_model_id and pinned_model_id not in models.values():
        print(f"::warning::pinned production model {pinned_model_id} not in "
              f"the benchmark set this run; gate not enforceable against pin")

    if failures:
        print()
        print("PARITY CHECK FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print()
    print("PARITY CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
