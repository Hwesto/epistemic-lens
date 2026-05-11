"""Unit tests for Phase C: bucket weighting, auto-promote, sitemap diff,
HDBSCAN swap.

Run: python3 -m unittest tests_phase_c.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# C.1 — Bucket weighting
# ---------------------------------------------------------------------------
class TestBucketWeighting(unittest.TestCase):
    def setUp(self):
        import meta
        # Ensure cache is warm with the live bucket_weights.json.
        meta.bucket_weights_table.cache_clear()
        self.meta = meta

    def test_known_bucket_returns_pop_times_reach(self):
        # USA: 333 * 0.85 ≈ 283.05
        w = self.meta.bucket_weight("usa")
        self.assertGreater(w, 200)
        self.assertLess(w, 350)

    def test_unknown_bucket_returns_default(self):
        w = self.meta.bucket_weight("absolutely_not_a_bucket_xyz")
        self.assertEqual(w, 1.0)

    def test_excluded_bucket_weighted_to_zero(self):
        # Wire services / opinion mags / EXCLUDE_QUANT aggregators are 0.
        self.assertEqual(self.meta.bucket_weight("wire_services"), 0.0)
        self.assertEqual(self.meta.bucket_weight("google_news_reuters"), 0.0)

    def test_confidence_lookup(self):
        self.assertEqual(self.meta.bucket_weight_confidence("usa"), "high")
        self.assertEqual(self.meta.bucket_weight_confidence("yemen"), "low")
        self.assertEqual(self.meta.bucket_weight_confidence("unknown_xyz"), "unknown")

    def test_weighted_distribution_dominated_by_heavy_bucket(self):
        from analytical.build_metrics import weighted_frame_distribution
        analysis = {
            "frames": [
                {"frame_id": "SECURITY_DEFENSE", "buckets": ["india"]},  # weight ~640
                {"frame_id": "ECONOMIC", "buckets": ["italy", "spain"]},  # combined ~75
            ]
        }
        d = weighted_frame_distribution(analysis)
        sec = d["frames"]["SECURITY_DEFENSE"]["weighted_share"]
        eco = d["frames"]["ECONOMIC"]["weighted_share"]
        self.assertGreater(sec, eco,
                           "single India bucket should outweigh italy+spain combined")
        # Unweighted view inverts: 1 bucket vs 2.
        self.assertLess(
            d["frames"]["SECURITY_DEFENSE"]["unweighted_share"],
            d["frames"]["ECONOMIC"]["unweighted_share"],
        )

    def test_low_confidence_buckets_surfaced(self):
        from analytical.build_metrics import weighted_frame_distribution
        analysis = {
            "frames": [
                {"frame_id": "POLITICAL", "buckets": ["yemen", "syria", "lebanon"]},
            ]
        }
        d = weighted_frame_distribution(analysis)
        # All three are 'low' confidence in bucket_weights.json.
        self.assertGreaterEqual(len(d["low_confidence_buckets"]), 1)


# ---------------------------------------------------------------------------
# C.4 — Auto-promote
# ---------------------------------------------------------------------------
class TestAutoPromote(unittest.TestCase):
    def test_existing_canonical_tokens_filtered(self):
        from analytical import auto_promote
        existing = auto_promote.existing_canonical_tokens()
        # canonical_stories.json has "hormuz", "ukraine", "taiwan" tokens
        # baked into patterns.
        self.assertIn("hormuz", existing)
        self.assertIn("taiwan", existing)
        self.assertIn("ukrain", existing)  # \bukrain(?:e|ian)\b prefix

    def test_persistent_token_detection_with_synthetic_snapshots(self):
        from analytical import auto_promote
        # Mock snapshots: token "novelthing" appears 4 of 7 days; "oneoff" 1 of 7.
        from collections import defaultdict
        days_seen: dict[str, dict[str, set[str]]] = defaultdict(dict)

        def fake_load(date):
            if date.endswith(("-01", "-03", "-05", "-07")):
                # Days where "novelthing" appears
                return {"_marker": "novelthing"}
            elif date.endswith("-04"):
                return {"_marker": "oneoff"}
            return None

        def fake_emerging(snap, **kwargs):
            mark = snap.get("_marker") if snap else None
            if mark == "novelthing":
                return [("novelthing", {"bucket_a", "bucket_b", "bucket_c", "bucket_d"})]
            if mark == "oneoff":
                return [("oneoff", {"bucket_a", "bucket_b", "bucket_c", "bucket_d"})]
            return []

        with patch.object(auto_promote, "load_snapshot", fake_load), \
             patch.object(auto_promote, "find_emerging_stories", fake_emerging):
            cands = auto_promote.detect_persistent_tokens(
                "2026-05-08", window_days=7, persistence=3, min_buckets=4
            )
        names = [c["token"] for c in cands]
        self.assertIn("novelthing", names)
        self.assertNotIn("oneoff", names, "1-day appearances must not promote")

    def test_renders_no_candidates_message(self):
        from analytical import auto_promote
        out = auto_promote.render_markdown([], "2026-05-08", 7, 3)
        self.assertIn("No candidates met the persistence threshold", out)


# ---------------------------------------------------------------------------
# C.3 — Sitemap diff parser
# ---------------------------------------------------------------------------
class TestSitemapDiff(unittest.TestCase):
    def test_canonicalize_strips_www_and_trailing_slash(self):
        from pipeline.sitemap_diff import _canonicalize
        self.assertEqual(
            _canonicalize("https://www.bbc.com/news/world/"),
            _canonicalize("https://bbc.com/news/world"),
        )

    def test_canonicalize_drops_query(self):
        from pipeline.sitemap_diff import _canonicalize
        self.assertEqual(
            _canonicalize("https://example.com/article?utm_source=feed"),
            "https://example.com/article",
        )

    def test_category_extraction(self):
        from pipeline.sitemap_diff import _category_of
        self.assertEqual(_category_of("https://x.com/opinion/2026/foo"), "/opinion")
        self.assertEqual(_category_of("https://x.com/"), "/")

    def test_parse_rss_extracts_links(self):
        from pipeline.sitemap_diff import _parse_rss
        rss = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
        <title>X</title>
        <item><title>A</title><link>https://x.com/a</link><pubDate>Mon, 05 May 2026 10:00:00 +0000</pubDate></item>
        <item><title>B</title><link>https://x.com/b</link><pubDate>Tue, 06 May 2026 10:00:00 +0000</pubDate></item>
        </channel></rss>"""
        items = _parse_rss(rss)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["url"], "https://x.com/a")

    def test_parse_sitemap_extracts_locs(self):
        from pipeline.sitemap_diff import _parse_sitemap
        sm = b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://x.com/a</loc><lastmod>2026-05-05</lastmod></url>
          <url><loc>https://x.com/b</loc></url>
        </urlset>"""
        items = _parse_sitemap(sm)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["url"], "https://x.com/a")


# ---------------------------------------------------------------------------
# C.5 — HDBSCAN swap (graceful)
# ---------------------------------------------------------------------------
class TestClusteringSwap(unittest.TestCase):
    def test_cluster_topics_falls_back_to_dbscan_when_hdbscan_missing(self):
        try:
            import numpy as np
            from sklearn.cluster import DBSCAN  # noqa
        except ImportError:
            self.skipTest("sklearn / numpy not installed")
        from pipeline import ingest

        # 6 vectors in 2 obvious clusters
        vectors = np.array([
            [1.0, 0.0, 0.0],
            [0.99, 0.01, 0.0],
            [1.0, 0.0, 0.01],
            [0.0, 1.0, 0.0],
            [0.0, 0.99, 0.01],
            [0.01, 1.0, 0.0],
        ])
        # Force the DBSCAN fallback path by patching HDBSCAN_AVAILABLE.
        with patch.object(ingest, "HDBSCAN_AVAILABLE", False):
            labels = ingest.cluster_topics(vectors)
        self.assertEqual(ingest.cluster_topics.last_method, "DBSCAN")
        # 6 points → at least 2 clusters expected.
        self.assertGreaterEqual(len(set(labels)) - (1 if -1 in labels else 0), 2)

    def test_cluster_topics_uses_hdbscan_when_available(self):
        try:
            import hdbscan  # noqa
            import numpy as np
        except ImportError:
            self.skipTest("hdbscan not installed in test env")
        from pipeline import ingest

        vectors = np.array([
            [1.0, 0.0, 0.0],
            [0.99, 0.01, 0.0],
            [1.0, 0.0, 0.01],
            [0.0, 1.0, 0.0],
            [0.0, 0.99, 0.01],
            [0.01, 1.0, 0.0],
        ])
        labels = ingest.cluster_topics(vectors)
        self.assertEqual(ingest.cluster_topics.last_method, "HDBSCAN")
        # Stability scores should be populated for HDBSCAN runs.
        self.assertIsInstance(ingest.cluster_topics.last_stability_scores, list)


# ---------------------------------------------------------------------------
# C.2 — Common Crawl fallback (graceful skip + mocked network)
# ---------------------------------------------------------------------------
class TestCommonCrawlFallback(unittest.TestCase):
    def test_no_index_returns_no_index_status(self):
        from pipeline import commoncrawl_fallback as cc
        with patch.object(cc, "_list_recent_news_indices", lambda *a, **k: []):
            body, status = cc.fetch_body_via_cc("https://example.com/article")
        self.assertIsNone(body)
        self.assertEqual(status, "no_index")

    def test_indices_but_no_record(self):
        from pipeline import commoncrawl_fallback as cc
        with patch.object(cc, "_list_recent_news_indices", lambda *a, **k: ["http://fake-index"]), \
             patch.object(cc, "_query_cdx", lambda *a, **k: None):
            body, status = cc.fetch_body_via_cc("https://example.com/article")
        self.assertIsNone(body)
        self.assertEqual(status, "no_record")

    def test_record_but_warc_failure(self):
        from pipeline import commoncrawl_fallback as cc
        with patch.object(cc, "_list_recent_news_indices", lambda *a, **k: ["http://fake-index"]), \
             patch.object(cc, "_query_cdx", lambda *a, **k: {"filename": "x", "offset": 1, "length": 2}), \
             patch.object(cc, "_fetch_warc_record", lambda *a, **k: None):
            body, status = cc.fetch_body_via_cc("https://example.com/article")
        self.assertIsNone(body)
        self.assertEqual(status, "warc_failed")


if __name__ == "__main__":
    unittest.main()
