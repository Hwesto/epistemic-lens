"""Full unit test suite for epistemic-lens v0.4.

Tests:
  - ingest._parse_feed: RSS 2.0, Atom, RDF, broken XML, BOM, CDATA, namespaces
  - ingest._strip_html: tag stripping, entity decoding, whitespace
  - ingest._parse_pub: multiple datetime formats
  - ingest._annotate_item: flag computation (is_stub, is_google_news, age)
  - ingest._wait_for_host: rate limiter timing
  - ingest._http_get: retry behaviour (mocked)
  - daily_health.health_for: error/stub/slow detection, bucket alerts
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
        if "pipeline.ingest" in sys.modules:
            importlib.reload(sys.modules["pipeline.ingest"])
        else:
            from pipeline import ingest  # noqa
        from pipeline.ingest import _parse_feed, _strip_html, _parse_pub, _annotate_item
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
        if "pipeline.ingest" in sys.modules:
            importlib.reload(sys.modules["pipeline.ingest"])
        from pipeline.ingest import _wait_for_host
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
        if "pipeline.ingest" in sys.modules:
            importlib.reload(sys.modules["pipeline.ingest"])
        from pipeline import ingest
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
# Dedup tests removed when the dedup stage was deleted — see commit
# "Stage 3: delete unused dedup stage". The annotations it wrote
# (canonical_url, normalised_title, url_dup_*, title_dup_*) were never
# read by any downstream consumer.


# ============================================================================
# Daily health
# ============================================================================
class TestDailyHealth(unittest.TestCase):
    def setUp(self):
        if "pipeline.daily_health" in sys.modules:
            importlib.reload(sys.modules["pipeline.daily_health"])
        from pipeline import daily_health
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

    def _snap_with_extraction(self, date, statuses_per_bucket):
        """Build a snapshot where each bucket has one feed whose items
        carry the given extraction_status values."""
        countries = {}
        for bucket, statuses in statuses_per_bucket.items():
            items = [{"is_stub": False, "extraction_status": s} for s in statuses]
            countries[bucket] = {"label": bucket, "feeds": [{
                "name": f"{bucket}_feed",
                "http_status": 200, "fetch_ms": 500,
                "error": None, "item_count": len(items), "items": items,
            }]}
        return {"date": date, "countries": countries}

    def test_low_extraction_alert_fires_on_low_full_pct(self):
        """Bucket with attempted >= low_extraction_min_attempted (5)
        but FULL-rate < low_extraction_full_pct (50%) must fire an alert."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td); (tdp / "snapshots").mkdir()
            self.dh.SNAPS = tdp / "snapshots"
            # 6 attempted, 1 FULL → 16.7%, well below 50% threshold
            snap = self._snap_with_extraction("2026-05-06", {
                "uk": ["FULL", "ERROR", "ERROR", "ERROR", "ERROR", "NONE"],
            })
            sp = tdp / "snapshots" / "2026-05-06.json"
            sp.write_text(json.dumps(snap))
            h, _ = self.dh.health_for(sp)
            alerts = [a for a in h["bucket_alerts"]
                      if a["alert_type"] == "low_extraction"]
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0]["bucket"], "uk")
            self.assertEqual(alerts[0]["attempted"], 6)
            self.assertEqual(alerts[0]["full"], 1)

    def test_low_extraction_alert_suppressed_below_min_attempted(self):
        """If fewer than low_extraction_min_attempted items have a status,
        the alert must not fire even if FULL-rate is 0%."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td); (tdp / "snapshots").mkdir()
            self.dh.SNAPS = tdp / "snapshots"
            snap = self._snap_with_extraction("2026-05-06", {
                "uk": ["NONE", "NONE"],  # 2 attempted < 5 threshold
            })
            sp = tdp / "snapshots" / "2026-05-06.json"
            sp.write_text(json.dumps(snap))
            h, _ = self.dh.health_for(sp)
            self.assertEqual(
                [a for a in h["bucket_alerts"]
                 if a["alert_type"] == "low_extraction"], []
            )

    def test_health_output_passes_schema(self):
        """The validate_schema call inside health_for must not raise on a
        well-formed snapshot. Guards the cross-stage hand-off contract."""
        import meta as _meta
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td); (tdp / "snapshots").mkdir()
            self.dh.SNAPS = tdp / "snapshots"
            snap = self._snap_with_extraction("2026-05-06", {
                "uk": ["FULL"] * 5,
                "us": ["FULL"] * 3 + ["PARTIAL"] * 2,
            })
            sp = tdp / "snapshots" / "2026-05-06.json"
            sp.write_text(json.dumps(snap))
            h, _ = self.dh.health_for(sp)
            # If schema validation broke, health_for would raise; the
            # explicit re-validation here documents the hand-off.
            _meta.validate_schema(h, "health")

    def test_health_for_tolerates_missing_feeds_key(self):
        """Defensive .get('feeds', []) — a malformed bucket entry
        without the 'feeds' key shouldn't crash the run."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td); (tdp / "snapshots").mkdir()
            self.dh.SNAPS = tdp / "snapshots"
            snap = {"date": "2026-05-06", "countries": {
                "wonky": {"label": "no feeds key here"},
                "ok": {"label": "OK", "feeds": [
                    {"name": "f", "http_status": 200, "fetch_ms": 1,
                     "error": None, "item_count": 0, "items": []},
                ]},
            }}
            sp = tdp / "snapshots" / "2026-05-06.json"
            sp.write_text(json.dumps(snap))
            h, _ = self.dh.health_for(sp)  # must not raise
            self.assertEqual(h["n_feeds"], 1)
            self.assertEqual(h["items_per_bucket_now"]["wonky"], 0)


# ============================================================================
# Schema validation on real snapshot
# ============================================================================
class TestSchemaValidation(unittest.TestCase):
    def test_latest_snapshot_well_formed(self):
        # Find the most recent canonical snapshot via the shared helper
        # (excludes every sidecar including legacy _dedup.json files).
        from pipeline._paths import latest_snapshot
        p = latest_snapshot(ROOT / "snapshots")
        if p is None:
            self.skipTest("no snapshots in repo")
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
        self.assertTrue(d["meta"]["version"].startswith("0."),
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
        if "pipeline.extract_full_text" in sys.modules:
            importlib.reload(sys.modules["pipeline.extract_full_text"])
        from pipeline import extract_full_text as eft
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
        ids = [it["id"] for *_, it in targets]
        self.assertEqual(ids, ["x1"])
        # Top-0 + max-per-feed-0 means no filter: take all (with non-empty links)
        targets = self.eft.select_items(snap, conv, top_clusters=0, max_per_feed=0)
        ids = sorted(it["id"] for *_, it in targets)
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
        ids = sorted(it["id"] for *_, it in targets)
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
        ids = [it["id"] for *_, it in targets]
        self.assertEqual(ids, ["x2"])  # x1 already extracted, skipped


class TestSitemapFallback(unittest.TestCase):
    def test_sitemap_news_parse(self):
        if "pipeline.ingest" in sys.modules:
            importlib.reload(sys.modules["pipeline.ingest"])
        from pipeline import ingest
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


class TestBuildBriefing(unittest.TestCase):
    """build_briefing.py: matches_story, _title_tokens, novelty dedup,
    find_emerging_stories, schema validation."""

    def setUp(self):
        if "analytical.build_briefing" in sys.modules:
            importlib.reload(sys.modules["analytical.build_briefing"])
        from analytical import build_briefing
        self.bb = build_briefing

    def test_matches_story_positive_and_negative(self):
        story = {"patterns": [r"\bhormuz\b"], "exclude": []}
        self.assertTrue(self.bb.matches_story(
            {"title": "Tankers in the Strait of Hormuz", "summary": "", "body_text": ""},
            story["patterns"]))
        self.assertFalse(self.bb.matches_story(
            {"title": "Unrelated headline", "summary": "", "body_text": ""},
            story["patterns"]))

    def test_matches_story_body_match(self):
        """Pattern only in body_text (not title/summary) must still match —
        that's why the search includes body[:body_match_chars]."""
        story = {"patterns": [r"\bhantavirus\b"]}
        item = {"title": "Cruise ship outbreak",
                "summary": "details inside",
                "body_text": "The investigators confirmed it was hantavirus."}
        self.assertTrue(self.bb.matches_story(item, story["patterns"]))

    def test_matches_story_exclude_vetoes(self):
        story = {"patterns": [r"\biran\b"], "exclude": [r"\bhormuz\b"]}
        self.assertFalse(self.bb.matches_story(
            {"title": "Iran tankers in Hormuz", "summary": "", "body_text": ""},
            story["patterns"], story["exclude"]))
        self.assertTrue(self.bb.matches_story(
            {"title": "Iran nuclear deal", "summary": "", "body_text": ""},
            story["patterns"], story["exclude"]))

    def test_title_tokens_filters_stopwords(self):
        toks = self.bb._title_tokens("These are some words about something")
        self.assertNotIn("these", toks)  # stopword
        self.assertNotIn("are", toks)    # < 4 chars
        # "words" plural-stripped to "word" by meta.tokenize (Gap 5-2)
        self.assertIn("word", toks)
        self.assertIn("something", toks)

    def test_title_tokens_plural_stripped(self):
        """Closes Stage 0 Gap 0-3: _title_tokens shares meta.tokenize's
        normalisation, including plural-strip. Two titles differing only
        in pluralisation must produce identical token sets so the
        within-bucket novelty filter catches them.

        Note: the plural-strip rule is suffix-character matching, not
        real lemmatisation. "talks"/"talk" round-trip cleanly; pairs
        like "resumes"/"resume" don't (the rule strips "es" → "resum").
        We test the well-behaved pair.
        """
        a = self.bb._title_tokens("Hostage talks Cairo")
        b = self.bb._title_tokens("Hostage talk Cairo")
        self.assertEqual(a, b)

    def test_briefing_dedup_within_bucket(self):
        """Two near-identical titles in the same bucket should collapse
        to one corpus entry under the novelty Jaccard threshold."""
        snap = {"date": "2026-05-06", "countries": {
            "uk": {"label": "UK", "feeds": [
                {"name": "BBC", "lang": "en", "items": [
                    {"id": "1", "title": "UK strikes target Beirut buildings",
                     "link": "https://x.com/1",
                     "summary": "x" * 100, "body_text": "lebanon hezbollah israel " * 50},
                    {"id": "2", "title": "UK strikes target Beirut buildings today",
                     "link": "https://x.com/2",
                     "summary": "y" * 100, "body_text": "lebanon hezbollah israel " * 50},
                ]},
            ]},
        }}
        story = {"title": "Lebanon", "patterns": [r"\blebanon\b"], "exclude": []}
        b = self.bb.build_briefing_for_story(snap, "lebanon", story)
        # Both items match the story; Jaccard near 1 → second collapses.
        self.assertEqual(b["n_buckets"], 1)
        self.assertEqual(b["n_articles"], 1)
        self.assertEqual(len(b["corpus"]), 1)

    def test_briefing_signal_breakdown_matches_corpus(self):
        snap = {"date": "2026-05-06", "countries": {
            "uk": {"label": "UK", "feeds": [
                {"name": "F", "lang": "en", "items": [
                    {"id": "1", "title": "story headline",
                     "link": "https://x.com/1",
                     "summary": "story " * 30, "body_text": ""},
                ]},
            ]},
        }}
        story = {"title": "S", "patterns": [r"\bstory\b"], "exclude": []}
        b = self.bb.build_briefing_for_story(snap, "s", story)
        # signal_breakdown counts must equal corpus[].signal_level histogram
        from collections import Counter
        self.assertEqual(b["signal_breakdown"],
                         dict(Counter(c["signal_level"] for c in b["corpus"])))

    def test_briefing_passes_schema(self):
        """build_briefing output must validate against briefing.schema.json."""
        import meta as _meta
        snap = {"date": "2026-05-06", "countries": {
            "uk": {"label": "UK", "feeds": [
                {"name": "BBC", "lang": "en", "items": [
                    {"id": "1", "title": "Lebanon strike report",
                     "link": "https://bbc.example/1",
                     "summary": "details " * 30, "body_text": ""},
                ]},
            ]},
        }}
        story = {"title": "Lebanon", "patterns": [r"\blebanon\b"], "exclude": []}
        b = self.bb.build_briefing_for_story(snap, "lebanon", story)
        # Should not raise
        _meta.validate_schema(b, "briefing")

    def test_find_emerging_skips_canonical_pattern_titles(self):
        """A title that matches a canonical pattern (e.g. 'hormuz') must
        not contribute its tokens to the emerging-stories report."""
        snap = {"countries": {
            "uk": {"label": "UK", "feeds": [{"name": "F", "lang": "en", "items": [
                {"title": "Hormuz crisis deepens with new vessel attack"},
                {"title": "Hormuz crisis deepens with new vessel attack"},
                {"title": "Hormuz crisis deepens with new vessel attack"},
                {"title": "Hormuz crisis deepens with new vessel attack"},
            ]}]},
            "us": {"label": "US", "feeds": [{"name": "F", "lang": "en", "items": [
                {"title": "Hormuz crisis deepens with new vessel attack"},
            ]}]},
        }}
        emerging = self.bb.find_emerging_stories(snap, min_buckets=1)
        toks = {t for t, _ in emerging}
        self.assertNotIn("crisis", toks)  # filtered via canonical
        self.assertNotIn("deepens", toks)


class TestBuildMetrics(unittest.TestCase):
    """build_metrics.py: pairwise Jaccard, isolation, bucket-exclusive vocab."""

    def setUp(self):
        if "analytical.build_metrics" in sys.modules:
            importlib.reload(sys.modules["analytical.build_metrics"])
        from analytical import build_metrics
        import meta as _meta
        from collections import Counter as _Counter
        self.bm = build_metrics
        self.meta = _meta
        self.Counter = _Counter

    def test_normalize_token_strips_plurals(self):
        # Tokenization primitives now live in meta.py (the methodology pin).
        # "es" is tried before "s", so "rules" → "rule"
        self.assertEqual(self.meta.normalize_token("rules"), "rule")
        # "ies" is tried first; "cities" → strip "es" since stripping "ies"
        # would leave only 3 chars ("cit"). Light-touch normalization is the goal.
        self.assertEqual(self.meta.normalize_token("cities"), "citi")
        self.assertEqual(self.meta.normalize_token("Iran"), "iran")
        # Don't over-strip short tokens — "yes" stays as-is (len<=4)
        self.assertEqual(self.meta.normalize_token("yes"), "yes")

    def test_tokens_filters_stopwords_and_short(self):
        toks = self.bm.tokens_from_text("The quick brown fox said over the moon")
        # "the", "said", "over" are stopwords; "fox" is len=3, dropped.
        self.assertNotIn("the", toks)
        self.assertNotIn("said", toks)
        self.assertNotIn("over", toks)
        self.assertNotIn("fox", toks)
        self.assertIn("quick", toks)
        self.assertIn("brown", toks)
        self.assertIn("moon", toks)

    def test_jaccard_symmetric_and_bounded(self):
        a = self.Counter({"alpha": 2, "beta": 1, "gamma": 1})
        b = self.Counter({"beta": 1, "gamma": 1, "delta": 1})
        j = self.bm.jaccard(a, b)
        self.assertEqual(j, self.bm.jaccard(b, a))
        self.assertGreaterEqual(j, 0.0)
        self.assertLessEqual(j, 1.0)
        # 2 shared / 4 total = 0.5
        self.assertAlmostEqual(j, 0.5)

    def test_pairwise_jaccard_sorted_descending(self):
        vocabs = {
            "x": self.Counter({"alpha": 1, "beta": 1}),
            "y": self.Counter({"alpha": 1, "beta": 1}),  # identical to x
            "z": self.Counter({"gamma": 1}),  # disjoint
        }
        pairs = self.bm.pairwise_jaccard(vocabs)
        self.assertEqual(len(pairs), 3)
        self.assertEqual(pairs[0]["jaccard"], 1.0)  # x<>y
        self.assertEqual(pairs[-1]["jaccard"], 0.0)  # one of the disjoint pairs

    def test_bucket_exclusive_requires_df_one_and_min_count(self):
        vocabs = {
            "a": self.Counter({"shared": 5, "only_a": 4, "rare_a": 2}),
            "b": self.Counter({"shared": 3, "only_b": 3}),
        }
        excl = self.bm.bucket_exclusive_vocab(vocabs, min_count=3)
        a_terms = {e["term"] for e in excl["a"]}
        b_terms = {e["term"] for e in excl["b"]}
        self.assertIn("only_a", a_terms)        # df=1, count>=3
        self.assertNotIn("rare_a", a_terms)     # df=1 but count<3
        self.assertNotIn("shared", a_terms)     # df=2
        self.assertIn("only_b", b_terms)

    def test_isolation_mean_jaccard(self):
        vocabs = {
            "a": self.Counter({"x": 1, "y": 1}),       # identical to b
            "b": self.Counter({"x": 1, "y": 1}),
            "c": self.Counter({"z": 1}),                # disjoint from both
        }
        pairs = self.bm.pairwise_jaccard(vocabs)
        iso = self.bm.bucket_isolation(pairs, sorted(vocabs))
        # c is paired with a (0) and b (0) → mean 0; a and b each have one
        # 1.0 pair and one 0.0 pair → mean 0.5. So c is most isolated.
        self.assertEqual(iso[0]["bucket"], "c")
        self.assertEqual(iso[0]["mean_jaccard"], 0.0)

    def test_build_metrics_passes_schema(self):
        """Output must validate against metrics.schema.json. Guards the
        cross-stage hand-off: LLM analyze copies these numbers verbatim,
        validate_analysis compares them by field name."""
        briefing = {
            "date": "2026-05-06", "story_key": "x", "story_title": "X",
            "corpus": [
                {"bucket": "a", "feed": "fa", "lang": "en",
                 "title": "Alpha beta gamma", "link": "https://x/1",
                 "signal_level": "title", "signal_text": "alpha beta gamma"},
                {"bucket": "b", "feed": "fb", "lang": "en",
                 "title": "Alpha beta delta", "link": "https://x/2",
                 "signal_level": "title", "signal_text": "alpha beta delta"},
            ],
        }
        # build_metrics calls validate_schema internally; this just
        # asserts it doesn't raise on a well-formed briefing.
        m = self.bm.build_metrics(briefing)
        self.assertEqual(m["n_buckets"], 2)
        self.assertEqual(m["n_articles"], 2)

    def test_process_one_skips_briefing_without_corpus(self):
        """A malformed briefing must log to stderr and return None
        rather than raising SystemExit and aborting the whole run."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            bad = tdp / "2026-05-06_bad.json"
            bad.write_text(json.dumps({"date": "2026-05-06", "story_key": "bad"}))
            # No 'corpus' key. Should return None, not raise.
            result = self.bm.process_one(bad)
            self.assertIsNone(result)
            # No metrics sidecar should have been written.
            self.assertFalse((tdp / "2026-05-06_bad_metrics.json").exists())

    def test_build_metrics_against_real_briefing(self):
        path = ROOT / "briefings" / "2026-05-06_hormuz_iran.json"
        if not path.exists():
            self.skipTest("Hormuz briefing fixture not present")
        briefing = json.loads(path.read_text(encoding="utf-8"))
        m = self.bm.build_metrics(briefing)
        # Structural assertions (not numeric — let the data drift).
        self.assertEqual(m["story_key"], "hormuz_iran")
        self.assertGreaterEqual(m["n_buckets"], 20)
        self.assertEqual(
            len(m["pairwise_jaccard"]),
            m["n_buckets"] * (m["n_buckets"] - 1) // 2,
        )
        # Top pair must have higher score than bottom pair.
        self.assertGreaterEqual(
            m["pairwise_jaccard"][0]["jaccard"],
            m["pairwise_jaccard"][-1]["jaccard"],
        )
        # Isolation must be sorted ascending (most isolated first).
        iso = m["isolation"]
        for i in range(len(iso) - 1):
            self.assertLessEqual(iso[i]["mean_jaccard"], iso[i + 1]["mean_jaccard"])
        # Saudi Arabia's "sisi" / "egypt" exclusive vocab from the exemplar
        # should reproduce on this fixed corpus.
        saudi_terms = {e["term"] for e in m["bucket_exclusive_vocab"].get("saudi_arabia", [])}
        self.assertIn("sisi", saudi_terms)
        self.assertIn("egypt", saudi_terms)


class TestMethodologyPin(unittest.TestCase):
    """meta.py: the methodology pin — hashes, stamping, drift detection."""

    def test_pinned_inputs_match_declared_hashes(self):
        import meta
        # Should not raise on a clean repo.
        meta.assert_pinned(strict=True)

    def test_stamp_embeds_meta_version(self):
        import meta
        art = {"foo": 1}
        stamped = meta.stamp(art)
        self.assertIs(stamped, art)  # in-place
        self.assertEqual(stamped["meta_version"], meta.VERSION)

    def test_tokenize_uses_pinned_stopwords(self):
        import meta
        toks = meta.tokenize("The quick brown fox said over the moon")
        self.assertNotIn("the", toks)
        self.assertNotIn("said", toks)  # pinned stopword
        self.assertIn("quick", toks)
        self.assertIn("moon", toks)

    def test_canonical_stories_loads(self):
        import meta
        stories = meta.canonical_stories()
        self.assertIn("hormuz_iran", stories)
        self.assertIn("patterns", stories["hormuz_iran"])

    def test_baseline_pin_check_passes_on_clean_repo(self):
        # baseline_pin --check is the CI gate; must exit 0 when nothing has drifted.
        import subprocess
        r = subprocess.run(
            [sys.executable, "baseline_pin.py", "--check"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent),
        )
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)

    def test_drift_is_detected(self):
        import json, tempfile, shutil
        import meta as _meta
        # Snapshot the current pinned file, mutate it, expect drift.
        sw = Path(__file__).parent / "stopwords.txt"
        original = sw.read_bytes()
        try:
            sw.write_text(original.decode("utf-8") + "\nNEWWORD\n", encoding="utf-8")
            # Force re-import so meta picks up… actually meta.assert_pinned
            # re-reads from disk every call, so no reload needed.
            drift = _meta.assert_pinned(strict=False)
            self.assertIn("tokenizer.stopwords", drift)
        finally:
            sw.write_bytes(original)

    def test_pin_self_hash_ignores_metadata_fields(self):
        """Editing _doc / version / pinned_at / pin_reason must not change the
        self-hash — those are identity / commentary, not pinned values."""
        import meta as _meta
        d1 = dict(_meta.META)
        d2 = dict(_meta.META)
        d2["_doc"] = "different"
        d2["meta_version"] = "99.99.99"
        d2["pinned_at"] = "2099-01-01T00:00:00Z"
        d2["pin_reason"] = "different reason"
        self.assertEqual(_meta.pin_self_hash_of(d1), _meta.pin_self_hash_of(d2))

    def test_pin_self_hash_changes_on_threshold_edit(self):
        """Editing any pinned threshold inside meta_version.json (without
        bumping the version) must change the self-hash so assert_pinned()
        catches the drift in CI."""
        import copy
        import meta as _meta
        d1 = copy.deepcopy(_meta.META)
        d2 = copy.deepcopy(_meta.META)
        d2["health"]["stub_pct_min"] = 50  # moved from 80
        self.assertNotEqual(_meta.pin_self_hash_of(d1), _meta.pin_self_hash_of(d2))


class TestAnalysisSchemaAndRender(unittest.TestCase):
    """Phase 1: analysis.schema.json + render_analysis_md.py round-trip."""

    def setUp(self):
        import json as _json
        with open(Path(__file__).parent / "docs/api/schema/analysis.schema.json", encoding="utf-8") as f:
            self.schema = _json.load(f)
        self.minimal = {
            "meta_version": "1.1.0",
            "date": "2026-05-08",
            "story_key": "test_story",
            "story_title": "Test Story",
            "n_buckets": 6,
            "n_articles": 12,
            "tldr": "A test analysis with several complete sentences for fixture purposes. Six buckets carry two distinct frames. No paradox is detected in this corpus today. The vocabulary differences are linguistic rather than editorial. Bottom-line framing remains aligned across the cluster.",
            "frames": [
                {"label": "FRAME_A", "description": "First frame.",
                 "buckets": ["italy", "usa"],
                 "evidence": [{"bucket": "italy", "outlet": "ANSA",
                               "quote": "guerra accordo", "signal_text_idx": 0}]},
                {"label": "FRAME_B", "buckets": ["china", "japan"],
                 "evidence": [{"bucket": "china", "quote": "blockade", "signal_text_idx": 4}]},
            ],
            "isolation_top": [{"bucket": "italy", "mean_jaccard": 0.009}],
            "exclusive_vocab_highlights": [
                {"bucket": "italy", "terms": ["guerra"], "what_it_reveals": "war framing."}
            ],
            "paradox": None,
            "silences": [{"bucket": "egypt", "what_they_covered_instead": "Sisi."}],
            "single_outlet_findings": [
                {"outlet": "RT", "bucket": "russia", "finding": "Iran-win frame.", "signal_text_idx": 5}
            ],
            "bottom_line": "Two short sentences restating the headline finding here. The framing differs across buckets but the underlying event is shared.",
            "generated_at": "2026-05-08T14:00:00Z",
            "model": "claude-haiku-4-5-20251001",
        }

    def test_schema_validates_minimal_shape(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed in test env")
        jsonschema.validate(self.minimal, self.schema)

    def test_schema_rejects_missing_required(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed in test env")
        bad = dict(self.minimal)
        del bad["bottom_line"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_accepts_paradox(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed in test env")
        with_paradox = dict(self.minimal)
        with_paradox["paradox"] = {
            "a": {"bucket": "iran_state", "outlet": "PressTV",
                  "quote": "future tariff", "signal_text_idx": 1},
            "b": {"bucket": "iran_opposition", "outlet": "Iran International",
                  "quote": "farmers starving", "signal_text_idx": 2},
            "joint_conclusion": "Both treat the deal as accomplished from opposite sides.",
        }
        jsonschema.validate(with_paradox, self.schema)

    def test_render_produces_expected_sections(self):
        if "publication.render_analysis_md" in sys.modules:
            importlib.reload(sys.modules["publication.render_analysis_md"])
        from publication import render_analysis_md
        md = render_analysis_md.render(self.minimal)
        # Header + every section header should appear.
        self.assertIn("# Test Story", md)
        self.assertIn("**Date:** 2026-05-08", md)
        self.assertIn("## TL;DR", md)
        self.assertIn("## Frames (2)", md)
        self.assertIn("### FRAME_A", md)
        self.assertIn("## Most isolated buckets", md)
        self.assertIn("## Bucket-exclusive vocabulary", md)
        self.assertIn("## Paradox", md)
        self.assertIn("_No paradox in this corpus._", md)
        self.assertIn("## Silence as data", md)
        self.assertIn("## Single-outlet findings", md)
        self.assertIn("## Bottom line", md)
        self.assertIn("`meta_version 1.1.0`", md)
        # Verbatim quote with corpus citation.
        self.assertIn("guerra accordo", md)
        self.assertIn("(corpus[0])", md)

    def test_render_handles_paradox(self):
        if "publication.render_analysis_md" in sys.modules:
            importlib.reload(sys.modules["publication.render_analysis_md"])
        from publication import render_analysis_md
        with_paradox = dict(self.minimal)
        with_paradox["paradox"] = {
            "a": {"bucket": "iran_state", "outlet": "PressTV",
                  "quote": "future tariff", "signal_text_idx": 1},
            "b": {"bucket": "iran_opposition", "outlet": "Iran International",
                  "quote": "farmers starving", "signal_text_idx": 2},
            "joint_conclusion": "Both treat the deal as accomplished from opposite sides.",
        }
        md = render_analysis_md.render(with_paradox)
        self.assertNotIn("_No paradox in this corpus._", md)
        self.assertIn("Both treat the deal as accomplished", md)
        self.assertIn("future tariff", md)
        self.assertIn("farmers starving", md)


class TestTemplateRenderers(unittest.TestCase):
    """Phase 3: template-based thread + carousel renderers (no LLM)."""

    def setUp(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        self.jsonschema = jsonschema
        repo = Path(__file__).parent
        self.thread_schema = json.load(open(repo / "docs/api/schema/thread.schema.json"))
        self.carousel_schema = json.load(open(repo / "docs/api/schema/carousel.schema.json"))
        # Use the existing 2026-05-06_hormuz_iran briefing as a real corpus.
        self.briefing = json.load(open(repo / "briefings/2026-05-06_hormuz_iran.json"))
        self.analysis = {
            "meta_version": "1.2.0", "date": "2026-05-06",
            "story_key": "hormuz_iran", "story_title": "Strait of Hormuz / US-Iran deal",
            "n_buckets": 27, "n_articles": 41,
            "tldr": "Twenty-seven outlets ran the same wire copy in this corpus. Italian press used markedly different vocabulary, framing the deal as conflict rather than agreement. Vocabulary carries the framing here, as the bucket-exclusive terms confirm. The isolation metric flags Italy as the editorial outlier.",
            "frames": [
                {"label": "ECONOMIC_CONTAGION", "buckets": ["philippines", "japan"],
                 "evidence": [{"bucket": "asia_pacific_regional", "outlet": "Asia Times",
                               "quote": "shock inflation spike in April", "signal_text_idx": 1}]},
                {"label": "WAR_FRAMING", "buckets": ["italy"],
                 "evidence": [{"bucket": "italy", "outlet": "ANSA",
                               "quote": "guerra accordo", "signal_text_idx": 0}]}
            ],
            "isolation_top": [
                {"bucket": "italy", "mean_jaccard": 0.009, "note": "linguistic."}
            ],
            "exclusive_vocab_highlights": [
                {"bucket": "italy", "terms": ["guerra"], "what_it_reveals": "war framing."}
            ],
            "paradox": None,
            "silences": [{"bucket": "egypt", "what_they_covered_instead": "Sisi domestic emergency."}],
            "single_outlet_findings": [
                {"outlet": "RT", "bucket": "russia", "finding": "Iran-win frame.",
                 "signal_text_idx": 5}
            ],
            "bottom_line": "Headline converged across the corpus. Framing did not — Italian press kept its own vocabulary throughout.",
            "generated_at": "2026-05-08T15:00:00Z", "model": "haiku",
        }

    def test_thread_renders_to_valid_schema(self):
        if "publication.render_thread" in sys.modules:
            importlib.reload(sys.modules["publication.render_thread"])
        from publication import render_thread
        out = render_thread.render(self.analysis, self.briefing)
        self.jsonschema.validate(out, self.thread_schema)
        self.assertEqual(out["story_key"], "hormuz_iran")
        self.assertEqual(out["date"], "2026-05-06")
        self.assertGreaterEqual(len(out["tweets"]), 3)
        self.assertLessEqual(len(out["tweets"]), 12)
        # Hook should reference the isolation outlier (italy) since no paradox.
        self.assertIn("italy", out["hook"].lower())

    def test_thread_uses_paradox_hook_when_present(self):
        if "publication.render_thread" in sys.modules:
            importlib.reload(sys.modules["publication.render_thread"])
        from publication import render_thread
        with_p = dict(self.analysis)
        with_p["paradox"] = {
            "a": {"bucket": "iran_state", "outlet": "PressTV",
                  "quote": "establishing tariff", "signal_text_idx": 1},
            "b": {"bucket": "iran_opposition", "outlet": "Iran International",
                  "quote": "farmers starving", "signal_text_idx": 2},
            "joint_conclusion": "Both treat the deal as accomplished from opposite sides."
        }
        out = render_thread.render(with_p, self.briefing)
        self.jsonschema.validate(out, self.thread_schema)
        self.assertIn("PressTV", out["hook"])
        self.assertIn("Iran International", out["hook"])

    def test_carousel_renders_to_valid_schema(self):
        if "publication.render_carousel" in sys.modules:
            importlib.reload(sys.modules["publication.render_carousel"])
        from publication import render_carousel
        out = render_carousel.render(self.analysis, self.briefing)
        self.jsonschema.validate(out, self.carousel_schema)
        self.assertEqual(out["story_key"], "hormuz_iran")
        self.assertGreaterEqual(len(out["slides"]), 4)
        self.assertLessEqual(len(out["slides"]), 10)
        kinds = [s.get("kind") for s in out["slides"]]
        self.assertIn("frame", kinds)
        # First slide is the title.
        self.assertEqual(out["slides"][0]["kind"], "callout")

    def test_carousel_paradox_slide_when_present(self):
        if "publication.render_carousel" in sys.modules:
            importlib.reload(sys.modules["publication.render_carousel"])
        from publication import render_carousel
        with_p = dict(self.analysis)
        with_p["paradox"] = {
            "a": {"bucket": "x", "outlet": "X", "quote": "q1", "signal_text_idx": 0},
            "b": {"bucket": "y", "outlet": "Y", "quote": "q2", "signal_text_idx": 1},
            "joint_conclusion": "Both agree."
        }
        out = render_carousel.render(with_p, self.briefing)
        self.jsonschema.validate(out, self.carousel_schema)
        self.assertIn("paradox", [s.get("kind") for s in out["slides"]])

    def test_thread_meta_version_stamped(self):
        if "publication.render_thread" in sys.modules:
            importlib.reload(sys.modules["publication.render_thread"])
        from publication import render_thread
        import meta as _meta
        out = render_thread.render(self.analysis, self.briefing)
        self.assertEqual(out.get("meta_version"), _meta.VERSION)

    def test_carousel_meta_version_stamped(self):
        if "publication.render_carousel" in sys.modules:
            importlib.reload(sys.modules["publication.render_carousel"])
        from publication import render_carousel
        import meta as _meta
        out = render_carousel.render(self.analysis, self.briefing)
        self.assertEqual(out.get("meta_version"), _meta.VERSION)


class TestValidateAnalysis(unittest.TestCase):
    """Phase 4: validate_analysis.py — citation + number checks."""

    def setUp(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")
        repo = Path(__file__).parent
        self.briefing = json.load(open(repo / "briefings/2026-05-06_hormuz_iran.json"))
        self.metrics = json.load(open(repo / "briefings/2026-05-06_hormuz_iran_metrics.json"))
        self.first_corpus = self.briefing["corpus"][0]
        first_text = self.first_corpus["signal_text"]
        first_bucket = self.first_corpus["bucket"]
        # Construct a clean analysis whose evidence cites a real corpus entry.
        self.clean = {
            "meta_version": "1.3.0", "date": "2026-05-06",
            "story_key": "hormuz_iran", "story_title": "Strait of Hormuz / US-Iran deal",
            "n_buckets": self.metrics["n_buckets"],
            "n_articles": self.metrics["n_articles"],
            "tldr": "A clean analysis fixture with multiple complete sentences for the validate-analysis test suite. The corpus contains 41 articles across 27 buckets. The methodology pin captured here is 1.3.0. Frames cite real corpus indices so citation-grounding passes.",
            "frames": [
                {"label": "FRAME_A", "buckets": [first_bucket],
                 "evidence": [{
                     "bucket": first_bucket,
                     "outlet": self.first_corpus.get("feed", "Unknown"),
                     "quote": first_text[:60].strip(),
                     "signal_text_idx": 0,
                 }]},
                {"label": "FRAME_B", "buckets": ["other"],
                 "evidence": [{
                     "bucket": self.briefing["corpus"][1]["bucket"],
                     "quote": self.briefing["corpus"][1]["signal_text"][:50].strip(),
                     "signal_text_idx": 1,
                 }]}
            ],
            "isolation_top": [
                {"bucket": self.metrics["isolation"][0]["bucket"],
                 "mean_jaccard": self.metrics["isolation"][0]["mean_jaccard"]}
            ],
            "exclusive_vocab_highlights": [],
            "paradox": None, "silences": [],
            "single_outlet_findings": [],
            "bottom_line": "Two sentences restating the headline finding clearly. End of analysis.",
            "generated_at": "2026-05-08T15:00:00Z", "model": "haiku",
        }

    def test_clean_analysis_passes_all_checks(self):
        if "analytical.validate_analysis" in sys.modules:
            importlib.reload(sys.modules["analytical.validate_analysis"])
        from analytical import validate_analysis as v
        errs = (v.check_schema(self.clean)
                + v.check_citations(self.clean, self.briefing)
                + v.check_numbers(self.clean, self.metrics))
        self.assertEqual(errs, [], msg="clean analysis should produce 0 errors")

    def test_n_buckets_mismatch_caught(self):
        from analytical import validate_analysis as v
        bad = dict(self.clean)
        bad["n_buckets"] = 99
        errs = v.check_numbers(bad, self.metrics)
        self.assertTrue(any("n_buckets" in e for e in errs))

    def test_isolation_score_mismatch_caught(self):
        from analytical import validate_analysis as v
        bad = dict(self.clean)
        bad["isolation_top"] = [
            {"bucket": self.metrics["isolation"][0]["bucket"], "mean_jaccard": 0.999}
        ]
        errs = v.check_numbers(bad, self.metrics)
        self.assertTrue(any("mean_jaccard" in e for e in errs))

    def test_isolation_unknown_bucket_caught(self):
        from analytical import validate_analysis as v
        bad = dict(self.clean)
        bad["isolation_top"] = [{"bucket": "fake_bucket_xyz", "mean_jaccard": 0.5}]
        errs = v.check_numbers(bad, self.metrics)
        self.assertTrue(any("not in" in e and "fake_bucket_xyz" in e for e in errs))

    def test_exclusive_vocab_term_not_in_metrics_caught(self):
        from analytical import validate_analysis as v
        bad = dict(self.clean)
        bad["exclusive_vocab_highlights"] = [
            {"bucket": "italy", "terms": ["term_that_does_not_exist_in_metrics"]}
        ]
        errs = v.check_numbers(bad, self.metrics)
        self.assertTrue(any("term_that_does_not_exist_in_metrics" in e for e in errs))

    def test_quote_not_in_corpus_caught(self):
        from analytical import validate_analysis as v
        bad = json.loads(json.dumps(self.clean))
        bad["frames"][0]["evidence"][0]["quote"] = "this is not in any signal_text"
        errs = v.check_citations(bad, self.briefing)
        self.assertTrue(any("not found verbatim" in e for e in errs))

    def test_bucket_mismatch_with_corpus_caught(self):
        from analytical import validate_analysis as v
        bad = json.loads(json.dumps(self.clean))
        bad["frames"][0]["evidence"][0]["bucket"] = "wrong_bucket_label"
        errs = v.check_citations(bad, self.briefing)
        self.assertTrue(
            any("claims bucket 'wrong_bucket_label'" in e for e in errs)
        )

    def test_signal_text_idx_out_of_range_caught(self):
        from analytical import validate_analysis as v
        bad = json.loads(json.dumps(self.clean))
        bad["frames"][0]["evidence"][0]["signal_text_idx"] = 99999
        errs = v.check_citations(bad, self.briefing)
        self.assertTrue(any("out of range" in e for e in errs))

    def test_paradox_citation_validated(self):
        from analytical import validate_analysis as v
        # Add a valid paradox using two real corpus entries.
        ok = json.loads(json.dumps(self.clean))
        ok["paradox"] = {
            "a": {"bucket": self.briefing["corpus"][2]["bucket"],
                  "outlet": self.briefing["corpus"][2].get("feed", "X"),
                  "quote": self.briefing["corpus"][2]["signal_text"][:40].strip(),
                  "signal_text_idx": 2},
            "b": {"bucket": self.briefing["corpus"][3]["bucket"],
                  "outlet": self.briefing["corpus"][3].get("feed", "Y"),
                  "quote": self.briefing["corpus"][3]["signal_text"][:40].strip(),
                  "signal_text_idx": 3},
            "joint_conclusion": "Both opposing-bloc outlets converge on the same framing.",
        }
        errs = v.check_citations(ok, self.briefing)
        self.assertEqual(errs, [])

        # Now corrupt one side's bucket label.
        bad = json.loads(json.dumps(ok))
        bad["paradox"]["a"]["bucket"] = "wrong_paradox_bucket"
        errs = v.check_citations(bad, self.briefing)
        self.assertTrue(any("paradox.a" in e and "wrong_paradox_bucket" in e for e in errs))

    def test_quote_match_is_whitespace_normalised(self):
        """Gap 7-8: a quote that differs from corpus signal_text only by
        runs of whitespace (newline / multiple spaces / tabs) must still
        match. Both sides are normalised before substring check."""
        from analytical import validate_analysis as v
        # Construct a corpus entry whose signal_text has irregular
        # whitespace, and a quote that has different whitespace but the
        # same words.
        local_briefing = {"corpus": [{
            "bucket": "uk", "feed": "BBC", "lang": "en",
            "title": "x", "link": "https://x", "signal_level": "summary",
            "signal_text": "Tankers   in the\nStrait of   Hormuz reportedly stalled.",
        }]}
        analysis = {
            "frames": [{
                "label": "X", "buckets": ["uk"],
                "evidence": [{
                    "bucket": "uk",
                    "quote": "Tankers in the Strait of Hormuz reportedly stalled.",
                    "signal_text_idx": 0,
                }],
            }],
        }
        errs = v.check_citations(analysis, local_briefing)
        self.assertEqual(errs, [])


class TestRestampAnalyses(unittest.TestCase):
    """restamp_analyses.py: idempotent meta_version refresh + post-restamp
    schema validation (Gap 7-7)."""

    def setUp(self):
        if "analytical.restamp_analyses" in sys.modules:
            importlib.reload(sys.modules["analytical.restamp_analyses"])
        from analytical import restamp_analyses
        self.ra = restamp_analyses
        import meta as _meta
        self.meta = _meta

    def _minimal_analysis(self) -> dict:
        return {
            "meta_version": "1.0.0",
            "date": "2026-05-06",
            "story_key": "demo",
            "story_title": "Demo",
            "n_buckets": 5, "n_articles": 12,
            "tldr": ("Lead with the most surprising finding here today across all buckets. " * 4).strip(),
            "frames": [
                {"label": "F1", "buckets": ["a", "b"],
                 "evidence": [{"bucket": "a", "quote": "q1",
                               "signal_text_idx": 0}]},
                {"label": "F2", "buckets": ["c"],
                 "evidence": [{"bucket": "c", "quote": "q2",
                               "signal_text_idx": 1}]},
            ],
            "isolation_top": [{"bucket": "x", "mean_jaccard": 0.05}],
            "bottom_line": "Two sentences restating the headline finding here for fixture purposes. The underlying corpus matters more than the headline framing.",
            "generated_at": "2026-05-06T08:00:00Z",
        }

    def test_restamp_updates_meta_version_and_revalidates(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            p = tdp / "2026-05-06_demo.json"
            p.write_text(json.dumps(self._minimal_analysis()))
            changed = self.ra.restamp(p)
            self.assertTrue(changed)
            updated = json.loads(p.read_text())
            self.assertEqual(updated["meta_version"], self.meta.VERSION)

    def test_restamp_skips_when_already_current(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            p = tdp / "2026-05-06_demo.json"
            a = self._minimal_analysis()
            a["meta_version"] = self.meta.VERSION
            p.write_text(json.dumps(a))
            self.assertFalse(self.ra.restamp(p))

    def test_restamp_refuses_to_save_schema_invalid_file(self):
        """A file with shape drift (e.g. missing required field) should
        warn and skip rather than write a stamped-but-invalid artifact."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            p = tdp / "2026-05-06_broken.json"
            a = self._minimal_analysis()
            del a["bottom_line"]   # required field
            p.write_text(json.dumps(a))
            mtime_before = p.stat().st_mtime
            changed = self.ra.restamp(p)
            self.assertFalse(changed)
            # File untouched (mtime unchanged).
            self.assertEqual(p.stat().st_mtime, mtime_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
