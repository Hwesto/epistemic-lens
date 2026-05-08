"""Unit tests for the Phase A items that were deferred to Phase 5.0.0:
Unicode-aware tokenizer, TF-IDF cosine primary, LaBSE parallel skip,
bucket-quality EXCLUDE_QUANT tier.

Run: python3 -m unittest tests_phase_a_deferred.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


class TestUnicodeTokenizer(unittest.TestCase):
    def test_diacritics_preserved_when_regex_lib_present(self):
        try:
            import regex  # noqa
        except ImportError:
            self.skipTest("`regex` library not installed")
        import meta
        # Translation outputs sometimes preserve proper-noun diacritics.
        # The ASCII regex [A-Za-z]{4,} silently dropped "México" (split on é
        # and "Mxico" was never a token); the Unicode-aware \p{L}{4,} keeps
        # diacritic characters as letters so "méxico" survives as one token.
        toks = meta.tokenize("México announced new policy. Résumé pending review.")
        self.assertIn("méxico", toks)
        self.assertIn("résumé", toks)

    def test_short_words_still_dropped(self):
        import meta
        toks = meta.tokenize("It is a test of the system here.")
        # 1-3 char words dropped by min_token_length=4
        self.assertNotIn("it", toks)
        self.assertNotIn("is", toks)
        self.assertNotIn("a", toks)
        self.assertIn("test", toks)
        self.assertIn("system", toks)


class TestTfidfPrimary(unittest.TestCase):
    def setUp(self):
        try:
            import sklearn  # noqa
        except ImportError:
            self.skipTest("scikit-learn not installed")
        from analytical import build_metrics
        self.bm = build_metrics

    def test_pairs_have_score_field_not_jaccard(self):
        vocabs = {
            "a": Counter({"alpha": 2, "beta": 2}),
            "b": Counter({"alpha": 2, "beta": 2}),
        }
        pairs, _ = self.bm.tfidf_pairwise_and_isolation(vocabs)
        self.assertEqual(len(pairs), 1)
        self.assertIn("score", pairs[0])
        self.assertNotIn("jaccard", pairs[0])

    def test_isolation_uses_mean_similarity_field(self):
        vocabs = {
            "x": Counter({"alpha": 1}),
            "y": Counter({"beta": 1}),
            "z": Counter({"gamma": 1}),
        }
        _, iso = self.bm.tfidf_pairwise_and_isolation(vocabs)
        for r in iso:
            self.assertIn("mean_similarity", r)
            self.assertNotIn("mean_jaccard", r)

    def test_frequency_weighted_unlike_jaccard(self):
        # Two buckets share token "war" but with very different frequencies.
        # Jaccard sees them as 100% identical (set match); TF-IDF cosine
        # accounts for frequency.
        vocabs = {
            "a": Counter({"war": 100, "peace": 1}),
            "b": Counter({"war": 1, "peace": 100}),
        }
        pairs_jacc, _ = self.bm.jaccard_legacy(vocabs)
        pairs_tfidf, _ = self.bm.tfidf_pairwise_and_isolation(vocabs)
        # Jaccard treats them as identical (1.0)
        self.assertEqual(pairs_jacc[0]["jaccard"], 1.0)
        # TF-IDF cosine sees frequency divergence — should be < 1.0
        self.assertLess(pairs_tfidf[0]["score"], 1.0)


class TestLaBSEGracefulSkip(unittest.TestCase):
    def test_skips_when_sentence_transformers_unavailable(self):
        from analytical import build_metrics
        # Patch the import inside the function to raise.
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            pairs, iso, status = build_metrics.labse_pairwise_and_isolation(
                {"a": ["Hello world"], "b": ["Bonjour le monde"]}
            )
        # Should not raise; just return empty + skipped status.
        self.assertEqual(pairs, [])
        self.assertEqual(iso, [])
        self.assertTrue(status["skipped"])
        self.assertIn("reason", status)

    def test_skips_when_only_one_bucket(self):
        from analytical import build_metrics
        pairs, iso, status = build_metrics.labse_pairwise_and_isolation(
            {"only_one": ["text"]}
        )
        self.assertEqual(pairs, [])
        self.assertTrue(status["skipped"])


class TestBucketQualityTier(unittest.TestCase):
    def test_quant_excluded_buckets_dropped_from_vocab(self):
        from analytical import build_metrics
        import meta

        # Mock bucket_quality to mark "stub_bucket" as EXCLUDE_QUANT.
        original = meta.bucket_quality.cache_clear
        meta.bucket_quality.cache_clear()
        try:
            with patch.object(
                meta,
                "bucket_quality",
                lambda: {"stub_bucket": {"tier": "EXCLUDE_QUANT"}},
            ):
                # is_quant_excluded reads bucket_quality(); stub it inline:
                with patch.object(
                    meta, "is_quant_excluded",
                    lambda b: b == "stub_bucket",
                ):
                    corpus = [
                        {"bucket": "ok_bucket", "title": "Hi", "signal_text": "real body"},
                        {"bucket": "stub_bucket", "title": "Hi", "signal_text": "stub body"},
                    ]
                    vocabs = build_metrics.bucket_vocabularies(corpus)
            self.assertIn("ok_bucket", vocabs)
            self.assertNotIn("stub_bucket", vocabs)
        finally:
            meta.bucket_quality.cache_clear()

    def test_excluded_buckets_listed_in_metrics_output(self):
        from analytical import build_metrics
        import meta

        meta.bucket_quality.cache_clear()
        try:
            with patch.object(
                meta, "is_quant_excluded",
                lambda b: b == "stub_bucket",
            ):
                briefing = {
                    "date": "2026-05-08",
                    "story_key": "test",
                    "story_title": "Test",
                    "corpus": [
                        {"bucket": "ok_bucket_a", "title": "T",
                         "signal_text": "alpha beta gamma"},
                        {"bucket": "ok_bucket_b", "title": "T",
                         "signal_text": "delta epsilon"},
                        {"bucket": "stub_bucket", "title": "T",
                         "signal_text": "should not appear"},
                    ],
                }
                m = build_metrics.build_metrics(briefing)
            self.assertIn("stub_bucket", m["buckets_excluded_quant"])
            self.assertNotIn("stub_bucket", m["buckets"])
        finally:
            meta.bucket_quality.cache_clear()


if __name__ == "__main__":
    unittest.main()
