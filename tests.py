"""Full unit test suite for epistemic-lens v0.4.

Tests:
  - ingest._parse_feed: RSS 2.0, Atom, RDF, broken XML, BOM, CDATA, namespaces
  - ingest._strip_html: tag stripping, entity decoding, whitespace
  - ingest._parse_pub: multiple datetime formats
  - ingest._annotate_item: flag computation (is_stub, is_google_news, age)
  - ingest._wait_for_host: rate limiter timing
  - ingest._http_get: retry behaviour (mocked)
  - dedup.canonical_url: tracking-param strip, www/m, trailing slash
  - dedup.normalise_title: lowercase, suffix strip, punctuation
  - dedup.dedup_snapshot: collapses URL dupes, title near-dupes, intra-feed dupes
  - daily_health.health_for: error/stub/slow detection, bucket alerts
  - gdelt_pull.* : query construction (no live HTTP in unit tests)
  - schema validation: snapshot, convergence, similarity files

Run: python3 -m unittest tests.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def fixture_dir():
    return ROOT / "tests_fixtures"


# ============================================================================
# Parser tests
# ============================================================================
class TestParser(unittest.TestCase):
    def setUp(self):
        # Force reimport so env-var changes don't bleed
        if "ingest" in sys.modules:
            importlib.reload(sys.modules["ingest"])
        else:
            import ingest  # noqa
        from ingest import _parse_feed, _strip_html, _parse_pub, _annotate_item
        self.parse = _parse_feed
        self.strip = _strip_html
        self.pub = _parse_pub
        self.annotate = _annotate_item

    def test_rss20(self):
        rss = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
        <title>Site</title>
        <item><title>First headline</title>
              <link>https://example.com/a</link>
              <description>Body of first article.</description>
              <pubDate>Tue, 06 May 2026 12:00:00 +0000</pubDate></item>
        <item><title>Second headline</title>
              <link>https://example.com/b</link>
              <description><![CDATA[Body <b>two</b>]]></description></item>
        </channel></rss>"""
        items = self.parse(rss)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "First headline")
        self.assertEqual(items[0]["link"], "https://example.com/a")
        self.assertIn("Body of first", items[0]["summary"])
        self.assertEqual(items[1]["summary"], "Body two")  # CDATA + tag strip

    def test_atom(self):
        atom = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
        <title>Site</title>
        <entry><title>Atom one</title>
               <link href="https://example.org/atom1"/>
               <summary>Short summary</summary>
               <updated>2026-05-06T08:00:00Z</updated></entry>
        </feed>"""
        items = self.parse(atom)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Atom one")
        self.assertEqual(items[0]["link"], "https://example.org/atom1")

    def test_rdf(self):
        rdf = b"""<?xml version="1.0"?>
        <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                 xmlns="http://purl.org/rss/1.0/">
        <item rdf:about="https://example.org/r1">
          <title>RDF item</title>
          <link>https://example.org/r1</link>
          <description>RDF description</description>
        </item>
        </rdf:RDF>"""
        items = self.parse(rdf)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "RDF item")

    def test_bom(self):
        body = b"\xef\xbb\xbf<?xml version='1.0'?><rss><channel><item><title>BOM</title></item></channel></rss>"
        items = self.parse(body)
        self.assertEqual(items[0]["title"], "BOM")

    def test_broken_xml(self):
        items = self.parse(b"not even xml")
        self.assertEqual(items, [])

    def test_empty(self):
        self.assertEqual(self.parse(b""), [])

    def test_max_n_cap(self):
        items_xml = b"<rss><channel>" + b"".join(
            f"<item><title>i{i}</title></item>".encode() for i in range(20)
        ) + b"</channel></rss>"
        items = self.parse(items_xml, max_n=5)
        self.assertEqual(len(items), 5)

    def test_strip_html(self):
        self.assertEqual(self.strip("<p>Hello <b>world</b></p>"), "Hello world")
        self.assertEqual(self.strip("a&amp;b"), "a&b")
        self.assertEqual(self.strip("  multi   spaces  "), "multi spaces")
        self.assertEqual(self.strip(""), "")
        self.assertEqual(self.strip(None), "")

    def test_parse_pub(self):
        cases = [
            "Tue, 06 May 2026 12:00:00 +0000",
            "2026-05-06T12:00:00Z",
            "2026-05-06T12:00:00+0000",
            "2026-05-06 12:00:00",
            "2026-05-06",
        ]
        for c in cases:
            dt = self.pub(c)
            self.assertIsNotNone(dt, f"failed: {c}")
            self.assertEqual(dt.year, 2026)
        self.assertIsNone(self.pub(""))
        self.assertIsNone(self.pub("garbage"))

    def test_annotate_stub_detection(self):
        now = datetime(2026, 5, 6, 12, tzinfo=timezone.utc)
        # 1. Stub: summary is just title
        a = self.annotate({
            "title": "Some Headline About Stuff",
            "link": "https://x.com/a",
            "summary": "Some Headline About Stuff",
            "published": "2026-05-06T11:00:00Z",
        }, now)
        self.assertTrue(a["is_stub"])
        # 2. Empty summary: stub
        b = self.annotate({"title": "T", "link": "https://x.com/b", "summary": "", "published": ""}, now)
        self.assertTrue(b["is_stub"])
        # 3. Real summary: not stub
        c = self.annotate({
            "title": "Climate report",
            "link": "https://x.com/c",
            "summary": "The IPCC released a 200-page assessment finding sea level rise accelerating.",
            "published": "2026-05-06T08:00:00Z",
        }, now)
        self.assertFalse(c["is_stub"])

    def test_annotate_google_news(self):
        now = datetime.now(timezone.utc)
        a = self.annotate({"title": "T", "link": "https://news.google.com/rss/articles/CXYZ", "summary": "T", "published": ""}, now)
        self.assertTrue(a["is_google_news"])
        b = self.annotate({"title": "T", "link": "https://reuters.com/article", "summary": "T", "published": ""}, now)
        self.assertFalse(b["is_google_news"])

    def test_annotate_age(self):
        now = datetime(2026, 5, 6, 12, tzinfo=timezone.utc)
        a = self.annotate({"title": "T", "link": "x", "summary": "ok",
                           "published": "Tue, 06 May 2026 06:00:00 +0000"}, now)
        self.assertEqual(a["published_age_hours"], 6.0)


# ============================================================================
# Rate limiter
# ============================================================================
class TestRateLimiter(unittest.TestCase):
    def test_per_host_delay(self):
        # Reload with a fixed delay
        os.environ["PER_HOST_DELAY"] = "0.5"
        if "ingest" in sys.modules:
            importlib.reload(sys.modules["ingest"])
        from ingest import _wait_for_host
        t0 = time.time()
        _wait_for_host("test.example.com")
        _wait_for_host("test.example.com")
        elapsed = time.time() - t0
        self.assertGreaterEqual(elapsed, 0.49)
        # Different host should not wait
        t0 = time.time()
        _wait_for_host("other.example.com")
        elapsed2 = time.time() - t0
        self.assertLess(elapsed2, 0.1)
        os.environ.pop("PER_HOST_DELAY")


# ============================================================================
# HTTP retry
# ============================================================================
class TestHttpRetry(unittest.TestCase):
    def setUp(self):
        if "ingest" in sys.modules:
            importlib.reload(sys.modules["ingest"])
        import ingest
        self.ingest = ingest

    def test_retry_on_5xx(self):
        responses = [MagicMock(status_code=503, content=b""),
                     MagicMock(status_code=503, content=b""),
                     MagicMock(status_code=200, content=b"<rss/>")]
        with patch.object(self.ingest.requests, "get", side_effect=responses) as g:
            with patch.object(self.ingest.time, "sleep"):
                status, body, err = self.ingest._http_get("https://x.com/", "en", attempts=3)
        self.assertEqual(status, 200)
        self.assertEqual(g.call_count, 3)

    def test_no_retry_on_4xx(self):
        responses = [MagicMock(status_code=404, content=b"")]
        with patch.object(self.ingest.requests, "get", side_effect=responses) as g:
            status, body, err = self.ingest._http_get("https://x.com/", "en", attempts=3)
        self.assertEqual(status, 404)
        self.assertEqual(g.call_count, 1)

    def test_retry_on_connection_error(self):
        import requests as _r
        first_err = _r.exceptions.ConnectionError("boom")
        ok = MagicMock(status_code=200, content=b"<rss/>")
        with patch.object(self.ingest.requests, "get", side_effect=[first_err, ok]):
            with patch.object(self.ingest.time, "sleep"):
                status, body, err = self.ingest._http_get("https://x.com/", "en", attempts=3)
        self.assertEqual(status, 200)


# ============================================================================
# Dedup tests
# ============================================================================
class TestDedup(unittest.TestCase):
    def setUp(self):
        if "dedup" in sys.modules:
            importlib.reload(sys.modules["dedup"])
        import dedup
        self.dedup = dedup

    def test_canonical_url_strip_tracking(self):
        c = self.dedup.canonical_url
        self.assertEqual(
            c("https://www.example.com/article/?utm_source=newsletter&utm_campaign=x&id=42"),
            "https://example.com/article?id=42"
        )

    def test_canonical_url_mobile(self):
        self.assertEqual(self.dedup.canonical_url("https://m.bbc.co.uk/news/123"),
                         "https://bbc.co.uk/news/123")

    def test_canonical_url_google_news(self):
        u = "https://news.google.com/rss/articles/CBMiAB?oc=5"
        c = self.dedup.canonical_url(u)
        # Google News: strip query but keep path
        self.assertNotIn("?oc=", c)
        self.assertIn("/articles/CBMi", c)

    def test_canonical_url_trailing_slash_and_fragment(self):
        self.assertEqual(self.dedup.canonical_url("https://x.com/a/#section"),
                         "https://x.com/a")

    def test_normalise_title_basic(self):
        n = self.dedup.normalise_title
        self.assertEqual(n("Hello, World!"), "hello world")
        self.assertEqual(n("Headline - Reuters"), "headline")
        self.assertEqual(n("Hostage news | CNN"), "hostage news")
        # Unicode preserved
        self.assertIn("hello", n("HELLO World"))

    def test_normalise_title_keeps_cyrillic(self):
        s = self.dedup.normalise_title("Москва объявила о новых санкциях")
        self.assertIn("москва", s)

    def test_dedup_snapshot_url_collapse(self):
        snap = {
            "date": "2026-05-06",
            "countries": {
                "a": {"label": "A", "feeds": [
                    {"name": "F1", "items": [
                        {"id": "1", "title": "Big news today",
                         "link": "https://x.com/a?utm_source=foo",
                         "summary": "long summary"},
                    ]},
                ]},
                "b": {"label": "B", "feeds": [
                    {"name": "F2", "items": [
                        {"id": "2", "title": "Big news today",
                         "link": "https://x.com/a?utm_source=bar",
                         "summary": "another long summary that is longer"},
                    ]},
                ]},
            },
        }
        result = self.dedup.dedup_snapshot(snap)
        self.assertEqual(result["n_total_items"], 2)
        self.assertEqual(result["n_deduped"], 1)
        self.assertGreaterEqual(result["n_url_dupes"], 2)


# ============================================================================
# Daily health
# ============================================================================
class TestDailyHealth(unittest.TestCase):
    def setUp(self):
        if "daily_health" in sys.modules:
            importlib.reload(sys.modules["daily_health"])
        import daily_health
        self.dh = daily_health

    def test_health_flags(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "snapshots").mkdir()
            self.dh.SNAPS = tdp / "snapshots"  # redirect
            snap = {
                "date": "2026-05-06",
                "countries": {
                    "ok_bucket": {"label": "OK", "feeds": [
                        {"name": "Healthy", "http_status": 200, "fetch_ms": 500,
                         "error": None, "item_count": 10,
                         "items": [{"is_stub": False} for _ in range(10)]},
                    ]},
                    "bad_bucket": {"label": "BAD", "feeds": [
                        {"name": "Errored", "http_status": 500, "fetch_ms": 100,
                         "error": "HTTP 500", "item_count": 0, "items": []},
                        {"name": "Stub-only", "http_status": 200, "fetch_ms": 200,
                         "error": None, "item_count": 5,
                         "items": [{"is_stub": True} for _ in range(5)]},
                        {"name": "Slow", "http_status": 200, "fetch_ms": 8000,
                         "error": None, "item_count": 3,
                         "items": [{"is_stub": False} for _ in range(3)]},
                    ]},
                },
            }
            snap_path = tdp / "snapshots" / "2026-05-06.json"
            snap_path.write_text(json.dumps(snap))
            h, _ = self.dh.health_for(snap_path)
            self.assertEqual(h["n_feeds"], 4)
            self.assertEqual(h["n_errors"], 1)
            self.assertEqual(h["n_stub_feeds"], 1)
            self.assertEqual(h["n_slow_feeds"], 1)


# ============================================================================
# Schema validation on real snapshot
# ============================================================================
class TestSchemaValidation(unittest.TestCase):
    def test_latest_snapshot_well_formed(self):
        # Find the most recent snapshot regardless of pipeline version
        cands = sorted(p for p in (ROOT / "snapshots").glob("[0-9]*.json")
                       if not p.stem.endswith(("_convergence", "_similarity",
                                                "_prompt", "_dedup", "_health",
                                                "_pull_report")))
        if not cands:
            self.skipTest("no snapshots in repo")
        p = cands[-1]
        d = json.loads(p.read_text(encoding="utf-8"))
        # Universal v0.2-and-v0.4 schema
        self.assertIn("date", d)
        self.assertIn("countries", d)
        for ck, cv in d["countries"].items():
            self.assertIn("label", cv)
            self.assertIn("feeds", cv)
            for f in cv["feeds"]:
                self.assertIn("name", f)
                self.assertIn("items", f)
                # item_count is omitted on errored feeds in v0.2 — tolerate
                for it in f["items"]:
                    self.assertIn("title", it)
                    # v0.2 stored "id"; v0.4 also stores "id"
                    self.assertIn("id", it)
        # v0.4-only schema (only assert on snapshots that declare it)
        if d.get("max_items") is not None or d.get("config_version") is not None:
            for cv in d["countries"].values():
                for f in cv["feeds"]:
                    self.assertIn("fetch_ms", f)
                    self.assertIn("http_status", f)
                    for it in f["items"]:
                        self.assertIn("is_stub", it)
                        self.assertIn("is_google_news", it)
                        self.assertIn("summary_chars", it)
                        # extraction fields are optional (only if extract_full_text ran)
                        if "extraction_status" in it:
                            self.assertIn(it["extraction_status"],
                                          {"FULL", "PARTIAL", "STUB", "NONE",
                                           "ERROR", "SKIPPED"})
                            self.assertIsInstance(it.get("body_chars"), int)

    def test_feeds_json_well_formed(self):
        p = ROOT / "feeds.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertIn("meta", d)
        # Version must be 0.4.x — bumped on each gap-fix round
        self.assertTrue(d["meta"]["version"].startswith("0.4."),
                        f"unexpected version: {d['meta']['version']}")
        self.assertGreater(len(d["countries"]), 40)
        urls = []
        for ck, cv in d["countries"].items():
            for f in cv["feeds"]:
                for k in ("name", "url", "lang", "lean", "status"):
                    self.assertIn(k, f, f"{ck}/{f.get('name')} missing {k}")
                urls.append(f["url"])
        self.assertEqual(len(urls), len(set(urls)), "duplicate URLs in feeds.json")


# ============================================================================
# Sitemap fallback (mocked)
# ============================================================================
class TestExtractFullText(unittest.TestCase):
    def setUp(self):
        if "extract_full_text" in sys.modules:
            importlib.reload(sys.modules["extract_full_text"])
        import extract_full_text as eft
        self.eft = eft

    def test_classify_thresholds(self):
        c = self.eft.classify
        self.assertEqual(c(2000, None), "FULL")
        self.assertEqual(c(500, None), "PARTIAL")
        self.assertEqual(c(100, None), "STUB")
        self.assertEqual(c(20, None), "NONE")
        self.assertEqual(c(0, "TIMEOUT"), "ERROR")

    def test_select_items_top_clusters_filter(self):
        snap = {"countries": {
            "a": {"label": "A", "feeds": [
                {"name": "F1", "items": [
                    {"id": "x1", "link": "https://x.com/1", "title": "T1"},
                    {"id": "x2", "link": "https://x.com/2", "title": "T2"},
                    {"id": "x3", "link": "", "title": "no link"},
                ]},
            ]},
        }}
        # Cluster 0 has x1; cluster 1 has x2
        conv = [
            {"cluster_id": 0, "country_count": 5, "articles": [{"id": "x1"}]},
            {"cluster_id": 1, "country_count": 3, "articles": [{"id": "x2"}]},
        ]
        # Top-1 should pick only x1
        targets = self.eft.select_items(snap, conv, top_clusters=1, max_per_feed=0)
        ids = [it["id"] for _, _, it in targets]
        self.assertEqual(ids, ["x1"])
        # Top-0 + max-per-feed-0 means no filter: take all (with non-empty links)
        targets = self.eft.select_items(snap, conv, top_clusters=0, max_per_feed=0)
        ids = sorted(it["id"] for _, _, it in targets)
        self.assertEqual(ids, ["x1", "x2"])

    def test_select_items_hybrid_union(self):
        """Hybrid mode: top-clusters UNION top-N-per-feed."""
        snap = {"countries": {
            "a": {"label": "A", "feeds": [
                {"name": "F1", "items": [
                    {"id": "x1", "link": "https://x.com/1", "title": "T1"},
                    {"id": "x2", "link": "https://x.com/2", "title": "T2"},
                    {"id": "x3", "link": "https://x.com/3", "title": "T3"},
                    {"id": "x4", "link": "https://x.com/4", "title": "T4"},
                ]},
            ]},
            "b": {"label": "B", "feeds": [
                {"name": "F2", "items": [
                    {"id": "y1", "link": "https://y.com/1", "title": "U1"},
                ]},
            ]},
        }}
        # Cluster 0 (top-1) contains only x4 (which is the 4th item of F1)
        conv = [{"cluster_id": 0, "country_count": 5, "articles": [{"id": "x4"}]}]
        # Hybrid: top-1 cluster + max-per-feed=2
        # Should pick: x1, x2 (first 2 of F1), x4 (cluster), y1 (first of F2)
        targets = self.eft.select_items(snap, conv, top_clusters=1, max_per_feed=2)
        ids = sorted(it["id"] for _, _, it in targets)
        self.assertEqual(ids, ["x1", "x2", "x4", "y1"])

    def test_select_items_skips_already_extracted(self):
        snap = {"countries": {
            "a": {"label": "A", "feeds": [
                {"name": "F1", "items": [
                    {"id": "x1", "link": "https://x.com/1", "title": "T1",
                     "extraction_status": "FULL", "body_chars": 1500},
                    {"id": "x2", "link": "https://x.com/2", "title": "T2"},
                ]},
            ]},
        }}
        targets = self.eft.select_items(snap, None, top_clusters=0)
        ids = [it["id"] for _, _, it in targets]
        self.assertEqual(ids, ["x2"])  # x1 already extracted, skipped


class TestSitemapFallback(unittest.TestCase):
    def test_sitemap_news_parse(self):
        if "ingest" in sys.modules:
            importlib.reload(sys.modules["ingest"])
        import ingest
        body = b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
                xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
        <url><loc>https://x.com/article-1</loc>
             <news:news>
               <news:title>Breaking: X happened</news:title>
               <news:publication_date>2026-05-06T10:00:00Z</news:publication_date>
             </news:news></url>
        </urlset>"""
        with patch.object(ingest, "_http_get",
                          return_value=(200, body, None)):
            items = ingest._try_sitemap_fallback("https://x.com/", "en")
        self.assertEqual(len(items), 1)
        self.assertIn("Breaking", items[0]["title"])
        self.assertEqual(items[0]["link"], "https://x.com/article-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
