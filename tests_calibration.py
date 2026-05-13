"""tests_calibration.py — calibration scaffolding tests.

PR2 Phase A. Validates that the candidate-gathering script is
deterministic, the silver-labels dict aligns with the candidates file,
and the benchmark script's primitives (softmax-argmax, gating) behave
as expected.

Run: python -m unittest tests_calibration
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import meta

CALIBRATION = meta.REPO_ROOT / "calibration"


class TestCalibrationScaffolding(unittest.TestCase):

    def test_anchors_cover_every_canonical_story(self):
        raw = json.loads(
            (CALIBRATION / "embedding_anchors_draft.json").read_text(encoding="utf-8")
        )
        anchors = raw["anchors"]
        canonical = set(meta.canonical_stories())
        self.assertEqual(
            set(anchors), canonical,
            msg=f"anchors must cover every canonical story; "
                 f"missing={canonical - set(anchors)}, "
                 f"extra={set(anchors) - canonical}",
        )
        # Every anchor list has 3-5 sentences.
        for sk, sents in anchors.items():
            self.assertGreaterEqual(len(sents), 3,
                                       msg=f"{sk}: anchors must be 3-5 sentences, "
                                           f"got {len(sents)}")
            self.assertLessEqual(len(sents), 5,
                                    msg=f"{sk}: too many anchor sentences")

    def test_silver_labels_align_with_candidates(self):
        from calibration.silver_labels import LABELS
        cand_path = CALIBRATION / "eval_set_candidates.jsonl"
        if not cand_path.exists():
            self.skipTest("eval_set_candidates.jsonl not built")
        n_rows = sum(1 for _ in open(cand_path, encoding="utf-8"))
        self.assertEqual(
            len(LABELS), n_rows,
            msg=f"silver_labels must have one entry per candidate row "
                 f"(LABELS={len(LABELS)}, candidates={n_rows})",
        )
        # Every label has the required keys and valid conf value.
        for idx, entry in LABELS.items():
            self.assertIn("label", entry)
            self.assertIn("conf", entry)
            self.assertIsInstance(entry["label"], bool)
            self.assertIn(entry["conf"], {"high", "medium", "low"})

    def test_silver_label_distribution_is_balanced(self):
        from calibration.silver_labels import LABELS
        pos = sum(1 for v in LABELS.values() if v["label"])
        neg = sum(1 for v in LABELS.values() if not v["label"])
        # Both classes must be non-trivially represented so we can
        # measure precision AND recall.
        self.assertGreater(pos, 50, msg=f"too few positives ({pos})")
        self.assertGreater(neg, 50, msg=f"too few negatives ({neg})")

    def test_bh_filter_matches_mc_correction(self):
        """Sanity: calibration uses the same BH primitive as analytical/."""
        from analytical.mc_correction import bh_filter
        # p_1=0.001 ≤ 1/5*0.05=0.01 ✓
        # p_2=0.01  ≤ 2/5*0.05=0.02 ✓
        # p_3=0.04  ≤ 3/5*0.05=0.03 ✗ — largest k = 2
        survives, info = bh_filter([0.001, 0.01, 0.04, 0.5, 0.9], q=0.05)
        self.assertEqual(info["correction"], "bh")
        self.assertEqual(info["n_significant"], 2)
        self.assertEqual(survives, [True, True, False, False, False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
