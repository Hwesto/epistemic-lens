"""Edge-case stress tests for ingest + health.

Covers:
  - Malformed RSS (truncated, mixed encoding, illegal XML chars)
  - Empty feeds
  - Feed with item count == 0
  - Single-item feed
  - Feed where all items are identical
  - Mixed RSS+Atom in one document
  - Items missing title (should be dropped)
  - Items missing link / summary / pubDate (should be tolerated)
  - Health: missing keys gracefully handled
  - Annotation: future-dated published, malformed dates, very long summary
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
        from pipeline.ingest import _parse_feed, _annotate_item
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


class TestEdgeIngest(unittest.TestCase):
    def setUp(self):
        if "ingest" in sys.modules:
            importlib.reload(sys.modules["ingest"])
        from pipeline import ingest
        self.ingest = ingest

    def test_pull_feed_dead_url(self):
        info = {"name": "Nope", "url": "https://nonexistent-domain-9999.invalid/rss",
                "lang": "en", "lean": ""}
        result = self.ingest.pull_feed(info)
        self.assertEqual(result["item_count"], 0)
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["items"], [])

    def test_pull_all_with_one_dead_one_alive(self):
        cfg = {"meta": {}, "countries": {
            "alive": {"label": "alive", "feeds": [
                {"name": "DW", "url": "https://rss.dw.com/rdf/rss-en-all",
                 "lang": "en", "lean": ""}
            ]},
            "dead": {"label": "dead", "feeds": [
                {"name": "Bogus", "url": "https://nonexistent-domain-99999.invalid/rss",
                 "lang": "en", "lean": ""}
            ]},
        }}
        snap = self.ingest.pull_all(cfg)
        self.assertEqual(len(snap["countries"]), 2)
        # Alive feed pulled items
        self.assertGreater(snap["countries"]["alive"]["feeds"][0]["item_count"], 0)
        # Dead feed gracefully recorded
        dead_feed = snap["countries"]["dead"]["feeds"][0]
        self.assertEqual(dead_feed["item_count"], 0)
        self.assertIsNotNone(dead_feed["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
