"""Unit tests for Phase B residuals: codebook validator + canary parser.

(Krippendorff / ensemble tests removed in meta-v7.0.0 along with the
multi-rater agreement gate.)

Mocks all network calls. Run: python3 -m unittest tests_phase_b.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from analytical import validate_analysis as V


# ---------------------------------------------------------------------------
# Codebook validator
# ---------------------------------------------------------------------------
class TestCodebookValidator(unittest.TestCase):
    def test_valid_frame_ids_pass(self):
        analysis = {
            "frames": [
                {"frame_id": "ECONOMIC", "buckets": ["it"], "evidence": []},
                {"frame_id": "SECURITY_DEFENSE", "buckets": ["us"], "evidence": []},
            ]
        }
        errs = V.check_codebook(analysis)
        self.assertEqual(errs, [])

    def test_missing_frame_id_fails(self):
        analysis = {"frames": [{"buckets": ["it"], "evidence": []}]}
        errs = V.check_codebook(analysis)
        self.assertEqual(len(errs), 1)
        self.assertIn("missing required frame_id", errs[0])

    def test_unknown_frame_id_fails(self):
        analysis = {"frames": [{"frame_id": "MADE_UP", "buckets": ["it"], "evidence": []}]}
        errs = V.check_codebook(analysis)
        self.assertEqual(len(errs), 1)
        self.assertIn("not in codebook", errs[0])

    def test_other_without_subframe_fails(self):
        analysis = {"frames": [{"frame_id": "OTHER", "buckets": ["it"], "evidence": []}]}
        errs = V.check_codebook(analysis)
        self.assertEqual(len(errs), 1)
        self.assertIn("OTHER requires a sub_frame", errs[0])

    def test_other_with_subframe_passes(self):
        analysis = {
            "frames": [
                {
                    "frame_id": "OTHER",
                    "sub_frame": "novel infrastructure framing",
                    "buckets": ["it"],
                    "evidence": [],
                }
            ]
        }
        errs = V.check_codebook(analysis)
        self.assertEqual(errs, [])


# ---------------------------------------------------------------------------
# Canary parser
# ---------------------------------------------------------------------------
class TestCanaryParser(unittest.TestCase):
    def test_parse_strict_json(self):
        from canary import run as C
        out = C._parse('{"primary_frame":"SECURITY_DEFENSE","secondary_frame":"ECONOMIC"}')
        self.assertEqual(out["primary_frame"], "SECURITY_DEFENSE")
        self.assertEqual(out["secondary_frame"], "ECONOMIC")

    def test_parse_with_prose_recovers(self):
        from canary import run as C
        out = C._parse(
            'Looking at this, my answer is:\n'
            '{"primary_frame":"HEALTH_SAFETY","secondary_frame":null}\n'
            'Let me know if needed.'
        )
        self.assertEqual(out["primary_frame"], "HEALTH_SAFETY")

    def test_parse_garbage_returns_empty(self):
        from canary import run as C
        self.assertEqual(C._parse("definitely not json"), {})

    def test_cosine_basic(self):
        from canary import run as C
        self.assertAlmostEqual(C.cosine([1, 0, 0], [1, 0, 0]), 1.0, places=5)
        self.assertAlmostEqual(C.cosine([1, 0, 0], [0, 1, 0]), 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
