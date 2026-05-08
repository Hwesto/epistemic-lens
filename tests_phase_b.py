"""Unit tests for Phase B: codebook validator, Krippendorff alpha,
ensemble orchestration, canary parser.

Mocks all network calls. Run: python3 -m unittest tests_phase_b.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from analytical import krippendorff as K
from analytical import ensemble as E
from analytical import validate_analysis as V


# ---------------------------------------------------------------------------
# Krippendorff alpha
# ---------------------------------------------------------------------------
class TestKrippendorff(unittest.TestCase):
    def test_perfect_agreement(self):
        # Two raters perfectly agreeing across 4 items.
        ratings = [
            ["A", "A"],
            ["B", "B"],
            ["A", "A"],
            ["C", "C"],
        ]
        a = K.alpha_nominal(ratings)
        self.assertIsNotNone(a)
        self.assertAlmostEqual(a, 1.0, places=5)

    def test_complete_disagreement(self):
        ratings = [
            ["A", "B"],
            ["B", "A"],
            ["A", "B"],
            ["B", "A"],
        ]
        a = K.alpha_nominal(ratings)
        self.assertIsNotNone(a)
        self.assertLess(a, 0.0, "alpha goes negative when raters anti-correlate")

    def test_partial_agreement(self):
        # 3 raters, 4 items, mixed agreement.
        ratings = [
            ["A", "A", "A"],
            ["B", "B", "C"],
            ["A", "A", "A"],
            ["B", "C", "B"],
        ]
        a = K.alpha_nominal(ratings)
        self.assertIsNotNone(a)
        self.assertGreater(a, 0.0)
        self.assertLess(a, 1.0)

    def test_missing_ratings_handled(self):
        # Item 2 has only one non-missing rating; it should be ignored.
        ratings = [
            ["A", "A"],
            ["B", "B"],
            [None, "X"],
            ["A", "A"],
        ]
        a = K.alpha_nominal(ratings)
        self.assertIsNotNone(a)

    def test_undefined_when_unanimous_marginals(self):
        ratings = [["A", "A"], ["A", "A"]]
        # Marginal label is always A → expected disagreement is 0 → alpha undefined.
        self.assertIsNone(K.alpha_nominal(ratings))

    def test_summary_reports_disagreements(self):
        ratings = [["A", "A"], ["B", "C"], ["X", "X"]]
        s = K.agreement_summary(ratings)
        self.assertEqual(s["unanimous_count"], 2)
        self.assertEqual(s["disagreement_count"], 1)
        self.assertEqual(s["disagreements"][0]["index"], 1)
        self.assertEqual(s["disagreements"][0]["labels_seen"], ["B", "C"])


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
# Ensemble orchestration (mocked raters)
# ---------------------------------------------------------------------------
class TestEnsembleParser(unittest.TestCase):
    def test_parse_clean_json(self):
        valid = {"ECONOMIC", "SECURITY_DEFENSE"}
        out = E._parse_frame_ids(
            '{"frames":[{"frame_id":"ECONOMIC"},{"frame_id":"SECURITY_DEFENSE"}]}',
            valid,
        )
        self.assertEqual(out, ["ECONOMIC", "SECURITY_DEFENSE"])

    def test_parse_strips_code_fence(self):
        valid = {"ECONOMIC"}
        text = '```json\n{"frames":[{"frame_id":"ECONOMIC"}]}\n```'
        self.assertEqual(E._parse_frame_ids(text, valid), ["ECONOMIC"])

    def test_parse_drops_unknown_ids(self):
        valid = {"ECONOMIC"}
        text = '{"frames":[{"frame_id":"BOGUS"},{"frame_id":"ECONOMIC"}]}'
        self.assertEqual(E._parse_frame_ids(text, valid), ["ECONOMIC"])

    def test_parse_dedupes(self):
        valid = {"ECONOMIC"}
        text = '{"frames":[{"frame_id":"ECONOMIC"},{"frame_id":"ECONOMIC"}]}'
        self.assertEqual(E._parse_frame_ids(text, valid), ["ECONOMIC"])

    def test_parse_recovers_from_prose_wrapper(self):
        valid = {"ECONOMIC"}
        text = 'Sure! Here is the JSON: {"frames":[{"frame_id":"ECONOMIC"}]} hope that helps.'
        self.assertEqual(E._parse_frame_ids(text, valid), ["ECONOMIC"])


class TestEnsembleBuild(unittest.TestCase):
    def _briefing(self, td: Path) -> Path:
        b = {
            "date": "2026-05-08",
            "story_key": "test_story",
            "story_title": "Test",
            "n_buckets": 2,
            "n_articles_total": 2,
            "corpus": [
                {"bucket": "us", "feed": "AP", "lang": "en", "title": "T1",
                 "signal_text": "Crude prices spiked."},
                {"bucket": "it", "feed": "Repubblica", "lang": "it", "title": "T2",
                 "signal_text": "I prezzi.", "signal_text_en": "The prices.",
                 "title_en": "T2 EN"},
            ],
        }
        p = td / "2026-05-08_test_story.json"
        p.write_text(json.dumps(b), encoding="utf-8")
        return p

    def test_build_with_two_agreeing_raters(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            briefing_path = self._briefing(td_path)
            with patch.object(E, "ANALYSES", td_path):
                raters = [
                    {"name": "r1", "kind": "stub", "model": "stub-1"},
                    {"name": "r2", "kind": "stub", "model": "stub-2"},
                ]

                def stub_rate(rater, prompt, valid_ids):
                    return ["ECONOMIC", "SECURITY_DEFENSE"]

                art = E.build_ensemble(
                    briefing_path, raters=raters, rate_fn=stub_rate
                )
            self.assertEqual(art["gate"], "ship",
                             msg=f"expected ship, got {art['gate']} alpha={art['krippendorff_alpha']}")
            self.assertEqual(
                sorted(art["consensus_frame_ids"]),
                ["ECONOMIC", "SECURITY_DEFENSE"],
            )

    def test_build_with_disagreeing_raters_lowers_gate(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            briefing_path = self._briefing(td_path)
            with patch.object(E, "ANALYSES", td_path):
                # 3 raters wildly disagreeing across 15 codebook IDs.
                # We construct labels so alpha falls below the gate.
                outputs = [
                    ["ECONOMIC", "MORALITY", "FAIRNESS"],
                    ["SECURITY_DEFENSE", "POLITICAL", "CULTURAL"],
                    ["LEGALITY", "HEALTH_SAFETY", "PUBLIC_OPINION"],
                ]
                rater_iter = iter(outputs)
                raters = [
                    {"name": f"r{i}", "kind": "stub", "model": f"m{i}"}
                    for i in range(3)
                ]

                def stub_rate(rater, prompt, valid_ids):
                    return next(rater_iter)

                art = E.build_ensemble(
                    briefing_path, raters=raters, rate_fn=stub_rate
                )
            # Three raters each picking 3 unique frames → no overlap → alpha < 0.4
            self.assertIn(art["gate"], ("suppress", "preliminary"),
                          msg=f"expected suppress/preliminary, got {art['gate']}")

    def test_build_with_one_rater_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            briefing_path = self._briefing(td_path)
            with patch.object(E, "ANALYSES", td_path):
                raters = [
                    {"name": "r1", "kind": "stub", "model": "stub-1"},
                    {"name": "r2", "kind": "stub", "model": "stub-2"},
                ]

                def stub_rate(rater, prompt, valid_ids):
                    return ["ECONOMIC"] if rater["name"] == "r1" else None

                art = E.build_ensemble(
                    briefing_path, raters=raters, rate_fn=stub_rate
                )
            # Only one rater produced output → gate = single_rater
            self.assertEqual(art["gate"], "single_rater")
            self.assertEqual(art["consensus_frame_ids"], ["ECONOMIC"])


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
