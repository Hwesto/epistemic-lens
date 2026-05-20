"""tests_perception.py — perception-layer regression tests (PR2 Phase B).

These tests validate the structural shape of the perception module without
loading the multilingual model (which is 2GB+ and would dominate test
time). For the model-dependent parity tests against the silver eval set
(macro F1 ≥ 0.80, per-lang F1 ≥ 0.70 on supported langs), see
.github/workflows/golden.yml — a weekly cron that runs the full
benchmark and alerts on drift.

Run: python -m unittest tests_perception
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import core.meta as meta
from core.embed import perception


class TestArticleId(unittest.TestCase):
    """The versioned article_id is the join key between embed_articles
    (writes the cache) and build_briefing (reads the cache). Both must
    agree on the hash recipe."""

    def test_stable_across_calls(self):
        a = perception.article_id("BBC", "https://bbc.com/x", "m1", "v1")
        b = perception.article_id("BBC", "https://bbc.com/x", "m1", "v1")
        self.assertEqual(a, b)

    def test_changes_when_model_changes(self):
        a = perception.article_id("BBC", "https://bbc.com/x", "m1", "v1")
        b = perception.article_id("BBC", "https://bbc.com/x", "m2", "v1")
        self.assertNotEqual(a, b)

    def test_changes_when_signal_text_version_changes(self):
        a = perception.article_id("BBC", "https://bbc.com/x", "m1", "v1")
        b = perception.article_id("BBC", "https://bbc.com/x", "m1", "v2")
        self.assertNotEqual(a, b)

    def test_changes_when_feed_or_link_changes(self):
        a = perception.article_id("BBC", "https://bbc.com/x", "m1", "v1")
        b = perception.article_id("BBC", "https://bbc.com/y", "m1", "v1")
        c = perception.article_id("Guardian", "https://bbc.com/x", "m1", "v1")
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)

    def test_12_char_hex_id(self):
        aid = perception.article_id("BBC", "https://bbc.com/x", "m1", "v1")
        self.assertEqual(len(aid), 12)
        # Hex characters only
        self.assertRegex(aid, r"^[0-9a-f]+$")


class TestSignalExcerpt(unittest.TestCase):
    """The text fed to the embedding model. Must match the eval-set
    construction in calibration/build_eval_set.py — title + body[:1500],
    with summary fallback and title-only fallback."""

    def test_prefers_body_over_summary(self):
        item = {
            "title": "T",
            "body_text": "B" * 600,
            "summary": "S" * 200,
        }
        out = perception.signal_excerpt_for_embedding(item)
        self.assertIn("T", out)
        self.assertIn("B", out)
        self.assertNotIn("S", out)

    def test_falls_back_to_summary(self):
        item = {
            "title": "T",
            "body_text": "B" * 30,  # below 100-char body threshold
            "summary": "S" * 200,
        }
        out = perception.signal_excerpt_for_embedding(item)
        self.assertIn("T", out)
        self.assertIn("S", out)

    def test_falls_back_to_title_only(self):
        item = {"title": "Title only"}
        out = perception.signal_excerpt_for_embedding(item)
        self.assertEqual(out, "Title only")

    def test_truncates_at_max_chars(self):
        item = {"title": "T", "body_text": "X" * 5000}
        out = perception.signal_excerpt_for_embedding(item, max_chars=1500)
        # Title + newline + 1500 X
        self.assertEqual(len(out), 2 + 1500)


class TestSoftmaxArgmax(unittest.TestCase):
    """Disambiguation-by-competition: each article scored against ALL
    stories, argmax wins. Articles below floor get story_key=None.

    Mocked centroids — no model required."""

    def setUp(self):
        import numpy as np
        # 3 stories, 4-dim space. story_a centroid points along axis 0,
        # story_b along axis 1, story_c along axis 2.
        self.story_centroids = {
            "story_a": np.array([1, 0, 0, 0], dtype="float32"),
            "story_b": np.array([0, 1, 0, 0], dtype="float32"),
            "story_c": np.array([0, 0, 1, 0], dtype="float32"),
        }

    def test_argmax_assignment(self):
        import numpy as np
        # 2 articles: one points along axis 0 (→ story_a), one along axis 1.
        vecs = np.array([
            [1, 0, 0, 0],   # story_a
            [0, 1, 0, 0],   # story_b
        ], dtype="float32")
        out = perception.assign_articles_to_stories(
            item_ids=["a1", "a2"], item_langs=["en", "en"],
            article_vecs=vecs, story_centroids=self.story_centroids,
            floor=0.5, cosine_gap=0.0,  # disable gap for argmax-only test
        )
        self.assertEqual(out["a1"].story_key, "story_a")
        self.assertEqual(out["a2"].story_key, "story_b")
        self.assertAlmostEqual(out["a1"].cosine, 1.0)

    def test_below_floor_returns_none(self):
        import numpy as np
        # Article points along axis 3 — perpendicular to all story centroids.
        vecs = np.array([[0, 0, 0, 1]], dtype="float32")
        out = perception.assign_articles_to_stories(
            item_ids=["a1"], item_langs=["en"],
            article_vecs=vecs, story_centroids=self.story_centroids,
            floor=0.1, cosine_gap=0.0,
        )
        self.assertIsNone(out["a1"].story_key,
                          msg=f"argmax_cosine={out['a1'].cosine} below floor; should be None")

    def test_second_best_recorded(self):
        import numpy as np
        # Article aligns partially with story_a + a little with story_b.
        v = np.array([0.8, 0.5, 0.0, 0.0], dtype="float32")
        v = v / np.linalg.norm(v)
        vecs = v.reshape(1, -1)
        out = perception.assign_articles_to_stories(
            item_ids=["a1"], item_langs=["en"],
            article_vecs=vecs, story_centroids=self.story_centroids,
            floor=0.1, cosine_gap=0.0,
        )
        self.assertEqual(out["a1"].story_key, "story_a")
        self.assertEqual(out["a1"].second_best_story, "story_b")

    def test_cosine_gap_rejects_equidistant_article(self):
        """The open-world filter: an article roughly equidistant from
        many centroids (cos to argmax barely above second-best) is
        rejected. This is the Korean-Gwangju-shop failure mode where
        e5-large gives cosine ~0.75 to many unrelated stories."""
        import numpy as np
        # Article roughly equidistant from story_a and story_b: cos ~0.71
        # to both, gap ~0.0. Floor passes, but gap fails.
        v = np.array([0.5, 0.5, 0.0, 0.0], dtype="float32")
        v = v / np.linalg.norm(v)
        vecs = v.reshape(1, -1)
        out = perception.assign_articles_to_stories(
            item_ids=["a1"], item_langs=["en"],
            article_vecs=vecs, story_centroids=self.story_centroids,
            floor=0.4, cosine_gap=0.05,
        )
        self.assertIsNone(out["a1"].story_key,
                          msg=f"argmax={out['a1'].cosine} second={out['a1'].second_best_cosine}; "
                               "gap should fail filter")

    def test_per_lang_floor_delta(self):
        import numpy as np
        v = np.array([0.6, 0.5, 0.0, 0.0], dtype="float32")
        v = v / np.linalg.norm(v)
        vecs = v.reshape(1, -1)
        out_en = perception.assign_articles_to_stories(
            item_ids=["a1"], item_langs=["en"],
            article_vecs=vecs, story_centroids=self.story_centroids,
            floor=0.5, cosine_gap=0.0,
        )
        out_fa_strict = perception.assign_articles_to_stories(
            item_ids=["a1"], item_langs=["fa"],
            article_vecs=vecs, story_centroids=self.story_centroids,
            floor=0.5, cosine_gap=0.0,
            per_lang_floor_delta={"story_a": {"fa": 0.3}},
        )
        self.assertEqual(out_en["a1"].story_key, "story_a")
        # floor for story_a in fa = 0.5+0.3=0.8; article cos ~0.768; below.
        self.assertIsNone(out_fa_strict["a1"].story_key)


class TestCanonicalStoriesHaveAnchors(unittest.TestCase):
    """Phase B requires every canonical story to carry embedding_anchors
    + assignment_floor in canonical_stories.json. Without these the
    perception layer falls back to regex, defeating the whole swap."""

    def setUp(self):
        self.stories = meta.canonical_stories()

    def test_every_story_has_anchors(self):
        for sk, sv in self.stories.items():
            self.assertIn("embedding_anchors", sv, msg=f"{sk} missing embedding_anchors")
            self.assertGreaterEqual(len(sv["embedding_anchors"]), 3,
                                       msg=f"{sk}: anchors must be >= 3 sentences")
            self.assertLessEqual(len(sv["embedding_anchors"]), 7,
                                    msg=f"{sk}: too many anchor sentences")

    def test_every_story_has_assignment_floor(self):
        for sk, sv in self.stories.items():
            self.assertIn("assignment_floor", sv, msg=f"{sk} missing assignment_floor")
            f = sv["assignment_floor"]
            self.assertGreater(f, 0.0)
            self.assertLess(f, 1.0)


class TestArticleIdConsistencyAcrossPipeline(unittest.TestCase):
    """Audit follow-up: every stage of Phase B (embed_articles writing,
    build_briefing reading the cache, discover_residual subtracting
    assigned IDs from the universe) must compute identical article_ids
    for the same (feed, link, model, signal_text_version) tuple. They
    all call perception.article_id() — assert the helper is the sole
    source of truth by exercising all three call sites."""

    def test_embed_articles_and_perception_module_agree(self):
        """pipeline.embed_articles.encode_snapshot writes IDs by calling
        perception.article_id; pipeline.discover_residual subtracts IDs
        the same way; build_briefing reads them the same way. The
        helper is the single point of truth — this test enforces that."""
        from core.embed import encode as ea
        from core.cluster import cluster_daily as dr
        # All three modules must import the same article_id symbol.
        self.assertIs(perception.article_id, ea.perception.article_id)
        self.assertIs(perception.article_id, dr.perception.article_id)
        # And the symbol must produce identical IDs for matching inputs.
        a = perception.article_id("BBC", "https://x/y", "m1", "v1")
        b = ea.perception.article_id("BBC", "https://x/y", "m1", "v1")
        c = dr.perception.article_id("BBC", "https://x/y", "m1", "v1")
        self.assertEqual(a, b)
        self.assertEqual(a, c)


class TestPerceptionPinBlock(unittest.TestCase):
    """meta_version.json's perception block is the runtime config the
    matcher reads. Must have model_id, signal_text_version, floor."""

    def test_perception_block_exists(self):
        perception_cfg = getattr(meta, "PERCEPTION", None) or {}
        self.assertTrue(perception_cfg, msg="meta.PERCEPTION is empty")

    def test_required_fields(self):
        cfg = meta.PERCEPTION
        self.assertIn("embedding_model", cfg)
        self.assertIn("signal_text_version", cfg)
        self.assertIn("assignment_floor_default", cfg)
        self.assertIn("method", cfg)
        self.assertEqual(cfg["method"], "embedding_softmax_argmax")

    def test_assignment_floor_in_valid_range(self):
        cfg = meta.PERCEPTION
        f = cfg["assignment_floor_default"]
        self.assertGreater(f, 0.0)
        self.assertLess(f, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
