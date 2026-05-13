"""merge_labels.py — fold silver_labels.py over eval_set_candidates.jsonl.

PR2 Phase A. Produces `eval_set.jsonl` — one row per (article,
candidate_story) pair, augmented with the Opus silver label.

Usage:
  python -m calibration.merge_labels
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import meta
from calibration.silver_labels import LABELS

CALIBRATION = meta.REPO_ROOT / "calibration"


def main() -> int:
    candidates_path = CALIBRATION / "eval_set_candidates.jsonl"
    out_path = CALIBRATION / "eval_set.jsonl"
    with open(candidates_path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    if len(rows) != len(LABELS):
        print(f"WARNING: {len(rows)} candidates but {len(LABELS)} labels",
              file=sys.stderr)
    n_missing = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for i, row in enumerate(rows):
            label = LABELS.get(i)
            if label is None:
                n_missing += 1
                continue
            merged = {
                **row,
                "silver_label": bool(label["label"]),
                "silver_confidence": label["conf"],
                "silver_note": label.get("note", ""),
                "label_source": "opus_silver",
            }
            fh.write(json.dumps(merged, ensure_ascii=False) + "\n")
    n_written = len(rows) - n_missing
    print(f"wrote {n_written} labeled rows to {out_path}")
    if n_missing:
        print(f"  ({n_missing} unlabeled candidates dropped)")
    # Summary by story
    by_story_pos = {}
    by_story_neg = {}
    by_lang_pos = {}
    by_conf = {"high": 0, "medium": 0, "low": 0}
    for r in rows:
        i = rows.index(r)  # quadratic, fine for ~350
        label = LABELS.get(i)
        if label is None:
            continue
        sk = r["candidate_story"]
        if label["label"]:
            by_story_pos[sk] = by_story_pos.get(sk, 0) + 1
            by_lang_pos.setdefault(sk, {})
            by_lang_pos[sk][r["lang"]] = by_lang_pos[sk].get(r["lang"], 0) + 1
        else:
            by_story_neg[sk] = by_story_neg.get(sk, 0) + 1
        by_conf[label["conf"]] = by_conf.get(label["conf"], 0) + 1

    print(f"\nLabel distribution: {by_conf}")
    print(f"\nPer-story positive / negative counts (silver_label = True / False):")
    for sk in sorted(set(list(by_story_pos) + list(by_story_neg))):
        p = by_story_pos.get(sk, 0)
        n = by_story_neg.get(sk, 0)
        non_lat_pos = sum(
            v for lang, v in (by_lang_pos.get(sk) or {}).items()
            if lang not in {"en", "es", "fr", "de", "it", "pt", "nl",
                              "id", "vi", "tr", "ms", "tl"}
        )
        print(f"  {sk:<32} pos={p:>2} neg={n:>2} non_lat_pos={non_lat_pos:>2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
