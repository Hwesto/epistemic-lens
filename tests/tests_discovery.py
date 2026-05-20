"""tests_discovery.py — Phase C residual-discovery + lineage tests.

PR2 Phase C. Validates the structural shape of the discovery pipeline
without requiring the embedding model (those run weekly via the
golden cron). Mocks residual_clusters.json files on a tmp dir for the
lineage logic.

Run: python -m unittest tests_discovery
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import core.meta as meta


class TestPersistenceTracker(unittest.TestCase):
    """Cross-day lineage construction via member-article-ID Jaccard.

    Centroid drift makes raw centroid-cosine linkage unstable; member-ID
    overlap is invariant to centroid composition. The test seeds three
    days of residual_clusters.json with overlapping member sets and
    asserts the lineage is detected."""

    def setUp(self):
        from core.cluster import lineage as pt
        self.pt = pt
        self.tmp = tempfile.mkdtemp()
        self.snapshots = Path(self.tmp) / "snapshots"
        self.snapshots.mkdir()
        self.archive = Path(self.tmp) / "archive"
        self.archive.mkdir()
        self._orig_snapshots = pt.SNAPSHOTS
        self._orig_archive = pt.ARCHIVE
        pt.SNAPSHOTS = self.snapshots
        pt.ARCHIVE = self.archive

    def tearDown(self):
        self.pt.SNAPSHOTS = self._orig_snapshots
        self.pt.ARCHIVE = self._orig_archive
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_day(self, date: str, clusters: list[dict]):
        (self.snapshots / f"{date}_residual_clusters.json").write_text(
            json.dumps({"date": date, "n_clusters": len(clusters),
                          "clusters": clusters})
        )

    def test_jaccard_helper(self):
        self.assertEqual(self.pt._jaccard(set(), set()), 0.0)
        self.assertEqual(self.pt._jaccard({"a"}, {"a"}), 1.0)
        self.assertAlmostEqual(self.pt._jaccard({"a", "b", "c"}, {"b", "c", "d"}),
                                  2/4)

    def test_single_day_returns_empty(self):
        """A lineage requires ≥2 days. One-day data → no lineages."""
        self._write_day("2026-05-12", [
            {"cluster_id": 0, "member_article_ids": ["a", "b", "c"],
             "bucket_distribution": {"usa": 2, "uk": 1}, "top_tokens": ["x"]}
        ])
        out = self.pt.build_lineages(7, "2026-05-12", 0.30)
        self.assertEqual(out, [])

    def test_two_day_overlap_creates_lineage(self):
        """Day-1 cluster shares 3 of 5 articles with day-2 cluster
        (Jaccard 3/7 = 0.43, above 0.30 default). → one lineage of
        day_count=2."""
        self._write_day("2026-05-11", [
            {"cluster_id": 0, "member_article_ids": ["a", "b", "c", "d", "e"],
             "bucket_distribution": {"usa": 2, "uk": 2, "germany": 1},
             "top_tokens": ["x", "y"]}
        ])
        self._write_day("2026-05-12", [
            {"cluster_id": 5, "member_article_ids": ["a", "b", "c", "f", "g"],
             "bucket_distribution": {"usa": 2, "uk": 2, "france": 1},
             "top_tokens": ["x", "z"]}
        ])
        out = self.pt.build_lineages(7, "2026-05-12", 0.30)
        self.assertEqual(len(out), 1, msg=f"got: {out}")
        L = out[0]
        self.assertEqual(L["day_count"], 2)
        self.assertEqual(L["seed_date"], "2026-05-11")
        self.assertEqual(L["latest_date"], "2026-05-12")
        # Union of buckets across days
        self.assertEqual(L["n_buckets_union"], 4)

    def test_three_day_promotion_candidate(self):
        """Three consecutive days, each cluster sharing ≥30% members with
        previous day's. ≥3 days + ≥4 buckets → meets promotion gate."""
        self._write_day("2026-05-10", [
            {"cluster_id": 0, "member_article_ids": ["a", "b", "c", "d"],
             "bucket_distribution": {"a1": 1, "a2": 1, "a3": 1, "a4": 1},
             "top_tokens": ["foo"]}
        ])
        self._write_day("2026-05-11", [
            {"cluster_id": 1, "member_article_ids": ["a", "b", "e", "f"],
             "bucket_distribution": {"a1": 1, "a5": 1, "a6": 1, "a7": 1},
             "top_tokens": ["foo"]}
        ])
        self._write_day("2026-05-12", [
            {"cluster_id": 2, "member_article_ids": ["a", "e", "g", "h"],
             "bucket_distribution": {"a8": 1, "a9": 1, "a5": 1, "a10": 1},
             "top_tokens": ["foo"]}
        ])
        out = self.pt.build_lineages(7, "2026-05-12", 0.20)
        self.assertEqual(len(out), 1)
        L = out[0]
        self.assertEqual(L["day_count"], 3)
        self.assertGreaterEqual(L["n_buckets_union"], 4)

    def test_below_jaccard_threshold_splits(self):
        """Two clusters share only 1 of 8 articles (Jaccard 1/8 = 0.125,
        below 0.30 default). → no lineage."""
        self._write_day("2026-05-11", [
            {"cluster_id": 0, "member_article_ids": ["a", "b", "c", "d"],
             "bucket_distribution": {"a1": 1}, "top_tokens": []}
        ])
        self._write_day("2026-05-12", [
            {"cluster_id": 1, "member_article_ids": ["a", "z", "y", "x"],
             "bucket_distribution": {"a2": 1}, "top_tokens": []}
        ])
        out = self.pt.build_lineages(7, "2026-05-12", 0.30)
        # 1/7 = 0.14 → below 0.30. No lineage.
        self.assertEqual(out, [])

    def test_lineage_id_is_stable(self):
        """Lineage ID = hash of seed (date, cluster_id). Reproducible
        across runs as long as seed doesn't change."""
        a = self.pt._lineage_id("2026-05-12", 7)
        b = self.pt._lineage_id("2026-05-12", 7)
        c = self.pt._lineage_id("2026-05-12", 8)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith("L"))


class TestDiscoverResidualArticleIDs(unittest.TestCase):
    """Phase C invariant: pipeline.discover_residual computes assigned
    and residual article_ids via the same perception.article_id helper
    that embed_articles uses to write the cache and build_briefing uses
    to read it. The audit found no direct test of this — adding one."""

    def test_discover_residual_uses_perception_article_id(self):
        from core.cluster import cluster_daily as dr
        from core.embed import perception
        # _assigned_article_ids and _index_snapshot both call
        # perception.article_id. Assert they're the SAME symbol — if
        # discover_residual ever stops importing from perception, this
        # fails loudly.
        self.assertIs(dr.perception.article_id, perception.article_id)

    def test_snap_index_returns_bucket_title_tuples(self):
        """_index_snapshot collapses two earlier passes into one; verify
        the (bucket, title) tuple shape stays correct."""
        from core.cluster import cluster_daily as dr
        snap = {
            "date": "2026-05-12",
            "countries": {
                "uk": {
                    "feeds": [{
                        "name": "BBC",
                        "items": [{"link": "https://bbc/x", "title": "Headline 1"}]
                    }]
                }
            }
        }
        idx = dr._index_snapshot(snap)
        self.assertEqual(len(idx), 1)
        bucket, title = next(iter(idx.values()))
        self.assertEqual(bucket, "uk")
        self.assertEqual(title, "Headline 1")


class TestAutoPromoteLineagePath(unittest.TestCase):
    """The auto_promote.py extension that surfaces lineage candidates
    alongside the legacy token-based ones."""

    def setUp(self):
        from core.cluster import auto_promote as ap
        self.ap = ap
        self.tmp = tempfile.mkdtemp()
        self.archive = Path(self.tmp) / "archive"
        self.archive.mkdir()
        self._orig_archive = ap.ARCHIVE
        ap.ARCHIVE = self.archive

    def tearDown(self):
        self.ap.ARCHIVE = self._orig_archive
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lineage_candidates_filtered_by_gate(self):
        """Only lineages with day_count >= 3 AND n_buckets_union >= 4
        surface as promotion candidates."""
        (self.archive / "persistent_residual_2026-05-12.json").write_text(
            json.dumps({"lineages": [
                {"lineage_id": "L1", "day_count": 5, "n_buckets_union": 7},  # PASS
                {"lineage_id": "L2", "day_count": 4, "n_buckets_union": 3},  # FAIL (buckets)
                {"lineage_id": "L3", "day_count": 2, "n_buckets_union": 9},  # FAIL (days)
                {"lineage_id": "L4", "day_count": 3, "n_buckets_union": 4},  # PASS (exact)
            ]})
        )
        out = self.ap.load_lineage_candidates("2026-05-12")
        self.assertEqual(sorted([L["lineage_id"] for L in out]), ["L1", "L4"])

    def test_missing_lineage_file_returns_empty(self):
        """Before persistence_tracker has ever run: zero lineages."""
        self.assertEqual(self.ap.load_lineage_candidates("2026-05-12"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
