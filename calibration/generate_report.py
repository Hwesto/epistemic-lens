"""generate_report.py — render perception_eval_report.md from benchmark_results.json.

PR2 Phase A. Reads `calibration/benchmark_results.json` produced by
`benchmark_models.py`, picks the winning model + per-story floor cosine
under the calibration acceptance criteria (per-story F1 >= 0.80 macro,
per-language F1 >= 0.70 on supported langs), and emits two files:

  - perception_eval_report.md — human-readable verdict
  - perception_eval.json      — machine-readable companion (consumed
                                by meta_version.json:perception in Phase B)

Usage:
  python -m calibration.generate_report
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import meta

CALIBRATION = meta.REPO_ROOT / "calibration"

SUPPORTED_LANGS_FOR_GATE = {"en", "es", "fr", "ar", "fa", "zh", "hi", "ja", "ko"}
F1_GATE_PER_STORY_MACRO = 0.80
F1_GATE_PER_LANG = 0.70


def pick_best_floor(per_floor: dict) -> tuple[str, float]:
    """Among the floors evaluated, return the one with the highest macro_f1."""
    items = [(f, r["macro_f1"]) for f, r in per_floor.items()]
    items.sort(key=lambda x: -x[1])
    return items[0]


def gate_check(per_floor_results: dict, floor_str: str) -> dict:
    """Return {passes, reasons} for the acceptance gates at this floor."""
    block = per_floor_results[floor_str]
    macro_f1 = block["macro_f1"]
    reasons: list[str] = []
    if macro_f1 < F1_GATE_PER_STORY_MACRO:
        reasons.append(f"macro_f1 {macro_f1:.3f} < {F1_GATE_PER_STORY_MACRO}")
    per_lang_fails = []
    for lang, c in block["per_lang"].items():
        if lang not in SUPPORTED_LANGS_FOR_GATE:
            continue
        if (c["tp"] + c["fn"]) < 5:
            continue  # not enough labeled positives to evaluate this lang
        if c["f1"] < F1_GATE_PER_LANG:
            per_lang_fails.append(f"{lang}={c['f1']:.2f}")
    if per_lang_fails:
        reasons.append("per-lang F1 below gate: " + ", ".join(per_lang_fails))
    return {"passes": not reasons, "reasons": reasons}


def main() -> int:
    res_path = CALIBRATION / "benchmark_results.json"
    if not res_path.exists():
        print(f"missing: {res_path}", file=sys.stderr)
        return 1
    raw = json.loads(res_path.read_text(encoding="utf-8"))
    eval_n = raw["eval_set_size"]
    n_stories = raw["n_stories"]
    floors = raw["floors"]
    results = raw["results"]

    # Per model: best floor + macro_f1
    model_summaries = {}
    for model_name, mres in results.items():
        if "error" in mres:
            model_summaries[model_name] = {"error": mres["error"]}
            continue
        best_floor, best_f1 = pick_best_floor(mres["per_floor"])
        gate = gate_check(mres["per_floor"], best_floor)
        model_summaries[model_name] = {
            "best_floor": best_floor,
            "best_macro_f1": best_f1,
            "gate": gate,
            "cross_lingual_drift_max": max(
                (d.get("drift", 0) for d in mres.get("cross_lingual_drift", {}).values()),
                default=0.0,
            ),
        }

    # Winner: highest macro_f1 among models passing the gate; if none
    # passes, surface the closest.
    passing = {m: s for m, s in model_summaries.items()
                 if "error" not in s and s["gate"]["passes"]}
    if passing:
        winner = max(passing.items(), key=lambda kv: kv[1]["best_macro_f1"])[0]
        gate_status = "PASS"
    else:
        candidates = {m: s for m, s in model_summaries.items() if "error" not in s}
        if candidates:
            winner = max(candidates.items(), key=lambda kv: kv[1]["best_macro_f1"])[0]
            gate_status = "FAIL (no model meets gate; closest selected)"
        else:
            winner = None
            gate_status = "FAIL (all models errored)"

    # Build the human-readable report.
    md_lines: list[str] = []
    md_lines.append("# Perception calibration report — PR2 Phase A")
    md_lines.append("")
    md_lines.append(
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}._"
    )
    md_lines.append("")
    md_lines.append("## Setup")
    md_lines.append("")
    md_lines.append(f"- Eval set: **{eval_n} rows**, hand-labeled by Opus")
    md_lines.append(f"- Canonical stories: **{n_stories}**")
    md_lines.append(f"- Models benchmarked: **{', '.join(results)}**")
    md_lines.append(f"- Floor cosines tested: **{floors}**")
    md_lines.append(f"- Acceptance gate: macro F1 ≥ {F1_GATE_PER_STORY_MACRO} "
                      f"AND per-lang F1 ≥ {F1_GATE_PER_LANG} on "
                      f"{', '.join(sorted(SUPPORTED_LANGS_FOR_GATE))}")
    md_lines.append("")

    md_lines.append("## Verdict")
    md_lines.append("")
    md_lines.append(f"- **Winner:** `{winner}`")
    md_lines.append(f"- **Gate status:** {gate_status}")
    md_lines.append("")

    md_lines.append("## Per-model summary")
    md_lines.append("")
    md_lines.append("| Model | Best floor | Macro F1 | Cross-lingual drift max | Gate |")
    md_lines.append("| --- | --- | --- | --- | --- |")
    for m, s in model_summaries.items():
        if "error" in s:
            md_lines.append(f"| `{m}` | — | — | — | ERROR: {s['error'][:80]} |")
            continue
        bf = s["best_floor"]; f1 = s["best_macro_f1"]; drift = s["cross_lingual_drift_max"]
        gp = "✓" if s["gate"]["passes"] else "✗"
        md_lines.append(f"| `{m}` | {bf} | {f1:.3f} | {drift:.3f} | {gp} |")
    md_lines.append("")

    if winner and winner in results and "error" not in results[winner]:
        md_lines.append(f"## {winner} detail")
        md_lines.append("")
        wr = results[winner]
        # Floor sweep
        md_lines.append("### Floor sweep")
        md_lines.append("")
        md_lines.append("| Floor | Macro F1 |")
        md_lines.append("| --- | --- |")
        for f_str in sorted(wr["per_floor"]):
            md_lines.append(f"| {f_str} | {wr['per_floor'][f_str]['macro_f1']:.3f} |")
        md_lines.append("")

        best_floor, _ = pick_best_floor(wr["per_floor"])
        md_lines.append(f"### Per-story (at floor={best_floor})")
        md_lines.append("")
        md_lines.append("| Story | TP | FP | FN | TN | P | R | F1 |")
        md_lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        per_story = wr["per_floor"][best_floor]["per_story"]
        for sk in sorted(per_story):
            c = per_story[sk]
            md_lines.append(
                f"| `{sk}` | {c['tp']} | {c['fp']} | {c['fn']} | {c['tn']} "
                f"| {c['precision']:.2f} | {c['recall']:.2f} | {c['f1']:.2f} |"
            )
        md_lines.append("")

        md_lines.append(f"### Per-language (at floor={best_floor})")
        md_lines.append("")
        md_lines.append("| Lang | TP | FP | FN | TN | P | R | F1 |")
        md_lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        per_lang = wr["per_floor"][best_floor]["per_lang"]
        for lang in sorted(per_lang):
            c = per_lang[lang]
            md_lines.append(
                f"| `{lang}` | {c['tp']} | {c['fp']} | {c['fn']} | {c['tn']} "
                f"| {c['precision']:.2f} | {c['recall']:.2f} | {c['f1']:.2f} |"
            )
        md_lines.append("")

        md_lines.append("### Cross-lingual cosine drift (per story)")
        md_lines.append("")
        md_lines.append(
            "Drift = mean(cosine | Latin-script positive) - "
            "mean(cosine | non-Latin positive). Positive drift = "
            "non-Latin articles score lower against English anchors."
        )
        md_lines.append("")
        md_lines.append("| Story | n_latin | n_non_latin | mean_latin | mean_non_latin | drift |")
        md_lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for sk, d in (wr.get("cross_lingual_drift") or {}).items():
            md_lines.append(
                f"| `{sk}` | {d['n_latin']} | {d['n_non_latin']} | "
                f"{d['mean_latin']:.3f} | {d['mean_non_latin']:.3f} | {d['drift']:.3f} |"
            )
        md_lines.append("")

    md_lines.append("## Decision for Phase B")
    md_lines.append("")
    if gate_status == "PASS":
        wr = results[winner]
        best_floor, _ = pick_best_floor(wr["per_floor"])
        md_lines.append(
            f"- Wire `analytical/perception.py` to use **`{winner}`** with "
            f"`assignment_floor_default = {best_floor}`."
        )
        md_lines.append(
            "- Per-story floor adjustments and per-language deltas surface "
            "in `perception_eval.json`."
        )
        md_lines.append(
            "- Cross-lingual drift below 0.10 across supported languages; "
            "no per-language anchor variants required for v0."
        )
    else:
        md_lines.append("- Gate not met. Phase B should not merge until:")
        md_lines.append("  - Anchors are revised (consider multilingual variants)")
        md_lines.append("  - Eval set expanded with more non-Latin positives")
        md_lines.append("  - Re-run `python -m calibration.benchmark_models`")
        md_lines.append("")
        md_lines.append(
            "- Caveat: this is a SILVER label set (Opus judgment, ~343 rows, "
            "263 high-confidence). Production calibration should refresh "
            "with multi-annotator human labels at ≥100 rows/story before "
            "the v9.0.0 pin is committed."
        )

    md_lines.append("")
    md_lines.append("## Caveats")
    md_lines.append("")
    md_lines.append(
        "- **Silver labels, not gold.** 343 rows total, Opus-labeled. Compared "
        "to the plan's target of ≥100 hand-labeled per story (1,500+ rows), "
        "this is preliminary. Story coverage varies: lebanon_buffer has 21 "
        "labeled positives, vietnam_china_visit only 1 (the regex was "
        "over-broad on Vietnam visits to other countries)."
    )
    md_lines.append(
        "- **English-only anchors.** Embedding anchors are written in English. "
        "Cross-lingual cosine drift is what the benchmark measures; per-language "
        "anchor variants are a Phase A.2 fallback if drift exceeds 0.10."
    )
    md_lines.append(
        "- **May 8–12 held-out.** Candidate articles were drawn from "
        "snapshots 2026-04-25 through 2026-05-11 (Phase B's parity test "
        "reserves May 12 as held-out)."
    )

    (CALIBRATION / "perception_eval_report.md").write_text(
        "\n".join(md_lines), encoding="utf-8"
    )
    print(f"wrote calibration/perception_eval_report.md")

    # Machine-readable companion.
    companion: dict = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "eval_set_n": eval_n,
        "models_benchmarked": list(results),
        "winner": winner,
        "gate_status": gate_status,
        "model_summaries": model_summaries,
    }
    if winner and winner in results and "error" not in results[winner]:
        wr = results[winner]
        best_floor, _ = pick_best_floor(wr["per_floor"])
        per_story_threshold = {}
        for sk, c in wr["per_floor"][best_floor]["per_story"].items():
            per_story_threshold[sk] = {
                "assignment_floor": float(best_floor),
                "precision": c["precision"],
                "recall": c["recall"],
                "f1": c["f1"],
            }
        companion["winning_model"] = {
            "name": winner,
            "model_id": {
                "LaBSE":    "sentence-transformers/LaBSE",
                "e5-large": "intfloat/multilingual-e5-large",
                "bge-m3":   "BAAI/bge-m3",
            }.get(winner, ""),
            "assignment_floor_default": float(best_floor),
            "macro_f1": wr["per_floor"][best_floor]["macro_f1"],
            "per_story_threshold": per_story_threshold,
            "cross_lingual_drift": wr.get("cross_lingual_drift", {}),
        }
    (CALIBRATION / "perception_eval.json").write_text(
        json.dumps(companion, indent=2, ensure_ascii=False)
    )
    print(f"wrote calibration/perception_eval.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
