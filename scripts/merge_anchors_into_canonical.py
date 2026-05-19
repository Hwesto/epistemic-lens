"""merge_anchors_into_canonical.py — fold calibration anchors into canonical_stories.json.

PR2 Phase B. One-shot script that copies the Phase A.2-calibrated
embedding_anchors from `calibration/embedding_anchors_draft.json` into the
production `canonical_stories.json`, adding `embedding_anchors` and
`assignment_floor` fields to each story while preserving existing fields
(title, patterns, exclude, tier).

Idempotent. Safe to re-run after re-calibrating anchors.

Usage:
  python scripts/merge_anchors_into_canonical.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    anchors_doc = json.loads(
        (REPO / "calibration" / "embedding_anchors_draft.json")
        .read_text(encoding="utf-8")
    )
    eval_doc = json.loads(
        (REPO / "calibration" / "perception_eval.json")
        .read_text(encoding="utf-8")
    )
    canon = json.loads(
        (REPO / "canonical_stories.json").read_text(encoding="utf-8")
    )

    anchors = anchors_doc["anchors"]
    winning = eval_doc.get("winning_model") or {}
    floor = winning.get("assignment_floor_default", 0.40)

    # Cross-check: anchor set must match canonical_stories set exactly.
    canon_keys = set(canon["stories"])
    anchor_keys = set(anchors)
    if canon_keys != anchor_keys:
        missing = canon_keys - anchor_keys
        extra = anchor_keys - canon_keys
        print(f"mismatch: missing={missing}, extra={extra}", file=sys.stderr)
        return 1

    for sk, anchor_list in anchors.items():
        story = canon["stories"][sk]
        story["embedding_anchors"] = anchor_list
        story["assignment_floor"] = floor

    out_path = REPO / "canonical_stories.json"
    out_path.write_text(
        json.dumps(canon, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"merged {len(anchors)} anchor sets into {out_path.name}")
    print(f"  assignment_floor={floor} (from {winning.get('name','?')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
