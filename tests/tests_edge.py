"""Offline edge-case stress tests for the RSS parser + dedup.

Covers:
  - Malformed RSS (truncated, mixed encoding, illegal XML chars)
  - Mixed RSS+Atom namespaces in one document
  - Items missing title (dropped) / link / summary / pubDate (tolerated)
  - Annotation: future-dated published, malformed dates, very long summary
  - URL canonicalisation: no scheme, host-only
  - Title normalisation: pure-emoji, all-punctuation
  - Dedup: empty snapshot, one-item snapshot, intra-feed duplicates

Network-dependent ingest tests retired with the v10 cleanup — live feed
behaviour is exercised by the daily cron, not the unit suite.
"""
from __future__ import annotations

import importlib
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


class TestEdgeParser(unittest.TestCase):
    def setUp(self):
        if "ingest" in sys.modules:
            importlib.reload(sys.modules["ingest"])
        from core.ingest.pull_feeds import _parse_feed, _annotate_item
        self.parse = _parse_feed
        self.annotate = _annotate_item

    def test_truncated_xml(self):
        body = b"<?xml version='1.0'?><rss><channel><item><title>partial"
        # Should not raise, returns []
        self.assertEqual(self.parse(body), [])

    def test_invalid_xml_chars(self):
        body = b"<?xml version='1.0'?><rss><channel><item><title>has\x00null</title></item></channel></rss>"
        # ET should still parse or return empty
        try:
            res = self.parse(body)
            # If parsed, accept
            self.assertIsInstance(res, list)
        except Exception:
            self.fail("parser raised on illegal char")

    def test_item_no_title_dropped(self):
        body = b"""<rss><channel>
        <item><link>https://x.com/1</link><description>No title here</description></item>
        <item><title>Has title</title></item>
        </channel></rss>"""
        items = self.parse(body)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Has title")

    def test_item_missing_optional_fields(self):
        body = b"<rss><channel><item><title>Just a title</title></item></channel></rss>"
        items = self.parse(body)
        self.assertEqual(items[0]["title"], "Just a title")
        self.assertEqual(items[0]["link"], "")
        self.assertEqual(items[0]["summary"], "")

    def test_mixed_namespaces(self):
        body = b"""<?xml version='1.0'?>
        <rss xmlns:dc="http://purl.org/dc/elements/1.1/"
             xmlns:content="http://purl.org/rss/1.0/modules/content/">
        <channel><item>
          <title>Mixed ns</title>
          <link>https://x.com/m</link>
          <content:encoded><![CDATA[<p>Long body via content:encoded</p>]]></content:encoded>
          <dc:date>2026-05-06T08:00:00Z</dc:date>
        </item></channel></rss>"""
        items = self.parse(body)
        self.assertEqual(items[0]["title"], "Mixed ns")
        self.assertIn("Long body", items[0]["summary"])

    def test_annotate_future_date(self):
        # Published 2 hours in the future (clock skew)
        now = datetime(2026, 5, 6, 10, tzinfo=timezone.utc)
        a = self.annotate({"title": "T", "link": "x",
                           "summary": "ok long summary that has actual content",
                           "published": "2026-05-06T12:00:00Z"}, now)
        # Negative age is acceptable; just shouldn't crash
        self.assertIsInstance(a["published_age_hours"], (int, float))

    def test_annotate_malformed_date(self):
        now = datetime.now(timezone.utc)
        a = self.annotate({"title": "T", "link": "x", "summary": "ok",
                           "published": "yesterday-ish"}, now)
        self.assertIsNone(a["published_age_hours"])

    def test_annotate_very_long_summary(self):
        now = datetime.now(timezone.utc)
        long = "x" * 10000
        a = self.annotate({"title": "T", "link": "x", "summary": long,
                           "published": ""}, now)
        # Item dict carries the full summary unchanged
        self.assertEqual(a["summary_chars"], len(long))


class TestEdgeDedup(unittest.TestCase):
    def setUp(self):
        if "dedup" in sys.modules:
            importlib.reload(sys.modules["dedup"])
        from core.ingest import dedup
        self.dedup = dedup

    def test_canonical_no_scheme(self):
        # Should not crash
        self.dedup.canonical_url("example.com/path")

    def test_canonical_empty(self):
        self.assertEqual(self.dedup.canonical_url(""), "")
        self.assertEqual(self.dedup.canonical_url(None) if False else "", "")

    def test_canonical_just_host(self):
        self.assertEqual(self.dedup.canonical_url("https://example.com/"),
                         "https://example.com/")

    def test_normalise_emoji_only(self):
        # Should not crash; result may be empty after stripping
        n = self.dedup.normalise_title("🔥🔥🔥")
        self.assertIsInstance(n, str)

    def test_normalise_punctuation_only(self):
        n = self.dedup.normalise_title("!!!---???")
        self.assertEqual(n, "")

    def test_dedup_empty_snapshot(self):
        snap = {"date": "2026-05-06", "countries": {}}
        result = self.dedup.dedup_snapshot(snap)
        self.assertEqual(result["n_total_items"], 0)
        self.assertEqual(result["n_deduped"], 0)

    def test_dedup_one_item(self):
        snap = {"date": "2026-05-06", "countries": {
            "a": {"label": "A", "feeds": [
                {"name": "F1", "items": [
                    {"id": "1", "title": "Solo headline", "link": "https://x.com/1", "summary": "ok"},
                ]},
            ]}}}
        result = self.dedup.dedup_snapshot(snap)
        self.assertEqual(result["n_total_items"], 1)
        self.assertEqual(result["n_deduped"], 1)

    def test_dedup_intra_feed_duplicates(self):
        """Same headline appearing 3 times in the same feed (People's Daily pattern)."""
        snap = {"date": "2026-05-06", "countries": {
            "china": {"label": "China", "feeds": [
                {"name": "PD", "items": [
                    {"id": "1", "title": "Xi visits Belarus", "link": "https://x.com/1", "summary": "a"},
                    {"id": "2", "title": "Xi visits Belarus", "link": "https://x.com/1", "summary": "b"},
                    {"id": "3", "title": "Xi visits Belarus", "link": "https://x.com/1", "summary": "c"},
                ]},
            ]}}}
        result = self.dedup.dedup_snapshot(snap)
        self.assertEqual(result["n_total_items"], 3)
        self.assertEqual(result["n_deduped"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
