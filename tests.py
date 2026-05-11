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

import meta
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
# Dedup tests
# ============================================================================
class TestDedup(unittest.TestCase):
    def setUp(self):
        if "pipeline.dedup" in sys.modules:
            importlib.reload(sys.modules["pipeline.dedup"])
        from pipeline import dedup
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

    def test_cross_day_dedup_marks_repeat_url(self):
        """Item with a canonical URL already in state gets cross_day_duplicate=True."""
        # Pre-seeded state: this URL was first seen 3 days ago
        state = {
            "window_days": 30,
            "url_first_seen": {"https://example.com/article": "2026-05-06"},
            "title_first_seen": {},
        }
        snap = {
            "date": "2026-05-09",
            "countries": {
                "usa": {"feeds": [
                    {"name": "F", "items": [
                        {"id": "x", "link": "https://example.com/article",
                         "title": "Today only", "summary": "S"},
                    ]},
                ]},
            },
        }
        self.dedup.dedup_snapshot(snap, cross_day_state=state)
        item = snap["countries"]["usa"]["feeds"][0]["items"][0]
        self.assertTrue(item.get("cross_day_duplicate"))
        self.assertEqual(item.get("cross_day_first_seen"), "2026-05-06")

    def test_cross_day_state_prunes_outside_window(self):
        """Entries older than window_days are dropped when prune is called."""
        state = {
            "window_days": 30,
            "url_first_seen": {
                "https://old.example/article": "2026-01-01",
                "https://recent.example/article": "2026-05-06",
            },
            "title_first_seen": {},
        }
        n = self.dedup.prune_cross_day_state(state, today="2026-05-09")
        self.assertEqual(n, 1)
        self.assertNotIn("https://old.example/article", state["url_first_seen"])
        self.assertIn("https://recent.example/article", state["url_first_seen"])

    def test_cross_day_state_preserves_first_seen_on_revisit(self):
        """update_cross_day_state must NOT overwrite an existing first_seen."""
        state = {
            "window_days": 30,
            "url_first_seen": {"https://example.com/x": "2026-05-01"},
            "title_first_seen": {},
        }
        self.dedup.update_cross_day_state(
            state,
            canonical_urls={"https://example.com/x"},
            normalised_titles=set(),
            today="2026-05-09",
        )
        # First-seen stays at the original date
        self.assertEqual(state["url_first_seen"]["https://example.com/x"], "2026-05-01")


class TestCoverageMatrix(unittest.TestCase):
    """Phase 1 deterministic per-(story, feed) coverage product."""

    def setUp(self):
        if "pipeline.coverage_matrix" in sys.modules:
            importlib.reload(sys.modules["pipeline.coverage_matrix"])
        from pipeline import coverage_matrix
        self.cm = coverage_matrix

    def test_matrix_records_matching_feeds_only(self):
        snap = {
            "date": "2026-05-09",
            "countries": {
                "usa": {"feeds": [
                    {"name": "Outlet A", "section": "news", "items": [
                        {"id": "1", "title": "Strait of Hormuz crisis deepens",
                         "summary": "Iran navy", "body_text": "", "link": "https://a/1",
                         "body_chars": 1500},
                        {"id": "2", "title": "Unrelated stock-market story",
                         "summary": "", "body_text": "", "link": "https://a/2"},
                    ]},
                    {"name": "Outlet B", "section": "wire", "items": [
                        {"id": "3", "title": "Cooking recipes",
                         "summary": "", "body_text": "", "link": "https://b/3"},
                    ]},
                ]},
            },
        }
        stories = {
            "hormuz_iran": {"patterns": [r"\bhormuz\b"], "exclude": [], "tier": "long_running",
                             "title": "Hormuz"},
            "ai_regulation": {"patterns": [r"\bai (?:act|regulation)\b"], "exclude": [],
                                "tier": "long_running", "title": "AI"},
        }
        m = self.cm.build_coverage_matrix(snap, stories)
        # hormuz_iran has 1 matching feed (Outlet A)
        self.assertEqual(len(m["coverage"]["hormuz_iran"]), 1)
        self.assertEqual(m["coverage"]["hormuz_iran"][0]["feed_name"], "Outlet A")
        self.assertEqual(m["coverage"]["hormuz_iran"][0]["section"], "news")
        self.assertEqual(m["coverage"]["hormuz_iran"][0]["first_match_rank"], 1)
        # ai_regulation: zero matching feeds
        self.assertEqual(len(m["coverage"]["ai_regulation"]), 0)
        # Summary numbers
        self.assertEqual(m["summary"]["hormuz_iran"]["n_feeds_covered"], 1)
        self.assertEqual(m["summary"]["hormuz_iran"]["n_buckets_covered"], 1)
        self.assertEqual(m["summary"]["ai_regulation"]["n_feeds_covered"], 0)

    def test_longitudinal_aggregator_basic(self):
        """build_trajectory groups frames across dates and computes per-day share."""
        if "analytical.longitudinal" in sys.modules:
            importlib.reload(sys.modules["analytical.longitudinal"])
        from analytical import longitudinal as lg
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # Two days of analyses for one story.
            day1 = {
                "date": "2026-05-07", "story_key": "S",
                "story_title": "Story", "meta_version": "7.0.0",
                "n_articles": 10,
                "frames": [
                    {"frame_id": "F1", "buckets": ["a", "b"]},
                    {"frame_id": "F2", "buckets": ["c"]},
                ],
            }
            day2 = {
                "date": "2026-05-08", "story_key": "S",
                "story_title": "Story", "meta_version": "7.0.1",
                "n_articles": 12,
                "frames": [
                    {"frame_id": "F1", "buckets": ["a"]},
                    {"frame_id": "F2", "buckets": ["b", "c"]},
                ],
            }
            (tdp / "2026-05-07_S.json").write_text(json.dumps(day1))
            (tdp / "2026-05-08_S.json").write_text(json.dumps(day2))
            grouped = lg.collect_analyses(analyses_dir=tdp)
            self.assertIn("S", grouped)
            traj = lg.build_trajectory(grouped["S"])
            self.assertEqual(traj["story_key"], "S")
            self.assertEqual(traj["n_days_with_analysis"], 2)
            # Two distinct meta_version segments (7.0.0 → 7.0.1)
            self.assertEqual(len(traj["meta_version_segments"]), 2)
            # Bucket set { a,b,c } same both days → same signature → 1 segment
            self.assertEqual(len(traj["bucket_set_signatures"]), 1)
            # Per-frame trajectory has both days
            self.assertIn("F1", traj["frame_trajectories"])
            self.assertEqual(len(traj["frame_trajectories"]["F1"]), 2)
            # Day 1 F1 covered 2/3 buckets = 0.667; Day 2 F1 covered 1/3 = 0.333
            shares = [d["share"] for d in traj["frame_trajectories"]["F1"]]
            self.assertAlmostEqual(shares[0], 0.667, places=2)
            self.assertAlmostEqual(shares[1], 0.333, places=2)

    def test_longitudinal_handles_pre_7_0_0_label_field(self):
        """Pre-7.0.0 analyses use `label` not `frame_id` — both must group together."""
        if "analytical.longitudinal" in sys.modules:
            importlib.reload(sys.modules["analytical.longitudinal"])
        from analytical import longitudinal as lg
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "2026-05-07_S.json").write_text(json.dumps({
                "date": "2026-05-07", "story_key": "S",
                "meta_version": "1.4.1",
                "frames": [{"label": "ECON", "buckets": ["a"]}],
            }))
            (tdp / "2026-05-08_S.json").write_text(json.dumps({
                "date": "2026-05-08", "story_key": "S",
                "meta_version": "7.0.0",
                "frames": [{"frame_id": "ECON", "buckets": ["a", "b"]}],
            }))
            grouped = lg.collect_analyses(analyses_dir=tdp)
            traj = lg.build_trajectory(grouped["S"])
            # Same key "ECON" used across both schemas → single trajectory
            self.assertEqual(len(traj["frame_trajectories"]["ECON"]), 2)

    def test_matrix_excludes_via_exclude_patterns(self):
        snap = {
            "date": "2026-05-09",
            "countries": {
                "usa": {"feeds": [
                    {"name": "F", "section": "news", "items": [
                        {"id": "1", "title": "Hormuz also gaza updates",
                         "summary": "", "body_text": "", "link": "https://x/1"},
                    ]},
                ]},
            },
        }
        # Story with `\bhormuz\b` exclude — matching item should NOT be counted
        stories = {
            "israel_palestine": {"patterns": [r"\bgaza\b"],
                                  "exclude": [r"\bhormuz\b"],
                                  "tier": "long_running", "title": "I/P"},
        }
        m = self.cm.build_coverage_matrix(snap, stories)
        self.assertEqual(len(m["coverage"]["israel_palestine"]), 0)


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

    def test_infer_section_url_pattern_overrides_feed(self):
        """URL pattern /opinion/, /editorial/ etc. tags item as opinion
        even if the feed defaults to news."""
        cases = [
            ("https://example.com/news/headline", "news", "news"),
            ("https://example.com/opinion/take-on-x", "news", "opinion"),
            ("https://example.com/editorial/board-says", "news", "opinion"),
            ("https://example.com/op-ed/contributor", "news", "opinion"),
            ("https://example.com/blog/observer", "news", "opinion"),
            ("https://example.com/columnist/somebody", "news", "opinion"),
            ("https://example.com/leader/today", "news", "opinion"),
            # Feed-level wire passes through when URL has no pattern
            ("https://reuters.com/article/12345", "wire", "wire"),
            # Empty URL falls back to feed_section
            ("", "news", "news"),
            # Case-insensitive match on path
            ("https://example.com/Opinion/Foo", "news", "opinion"),
        ]
        for url, feed_section, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(self.eft.infer_section(url, feed_section), expected)


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


class TestBuildMetrics(unittest.TestCase):
    """build_metrics.py: LaBSE pairwise similarity, isolation, bucket-exclusive vocab."""

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

    def test_build_metrics_against_real_briefing(self):
        path = ROOT / "briefings" / "2026-05-06_hormuz_iran.json"
        if not path.exists():
            self.skipTest("Hormuz briefing fixture not present")
        briefing = json.loads(path.read_text(encoding="utf-8"))
        m = self.bm.build_metrics(briefing)
        # Structural assertions (not numeric — let the data drift).
        self.assertEqual(m["story_key"], "hormuz_iran")
        self.assertGreaterEqual(m["n_buckets"], 1)
        # Primary similarity is LaBSE cosine. If sentence-transformers
        # isn't installed in the test env, build_metrics returns empty
        # pairs/isolation with embedding_status.skipped=True; skip the
        # numeric assertions in that case.
        if m["n_buckets"] >= 2 and not m.get("embedding_status", {}).get("skipped"):
            expected_pairs = m["n_buckets"] * (m["n_buckets"] - 1) // 2
            self.assertEqual(len(m["pairwise_similarity"]), expected_pairs)
            self.assertGreaterEqual(
                m["pairwise_similarity"][0]["score"],
                m["pairwise_similarity"][-1]["score"],
            )
            iso = m["isolation"]
            for i in range(len(iso) - 1):
                self.assertLessEqual(
                    iso[i]["mean_similarity"], iso[i + 1]["mean_similarity"]
                )
        # Saudi Arabia's "sisi" / "egypt" exclusive vocab from the exemplar
        # should reproduce on this fixed corpus.
        saudi_terms = {e["term"] for e in m["bucket_exclusive_vocab"].get("saudi_arabia", [])}
        self.assertIn("sisi", saudi_terms)
        self.assertIn("egypt", saudi_terms)


class TestPhase2Modules(unittest.TestCase):
    """Phase 2: within-language LLR + log-odds bigrams + headline-body
    divergence + cross-outlet lag + replay + rollup."""

    def test_within_language_llr_basic(self):
        if "analytical.within_language_llr" in sys.modules:
            importlib.reload(sys.modules["analytical.within_language_llr"])
        from analytical import within_language_llr as wll
        # Two English buckets: A heavily uses "blockade", B heavily uses "summit"
        briefing = {
            "corpus": [
                {"bucket": "A", "lang": "en",
                 "title": "naval blockade tightens", "signal_text":
                 "blockade " * 50 + "tanker " * 20},
                {"bucket": "B", "lang": "en",
                 "title": "summit talks continue", "signal_text":
                 "summit " * 50 + "talks " * 20},
                {"bucket": "C", "lang": "en",
                 "title": "neutral coverage",
                 "signal_text": "story update " * 30},
            ]
        }
        out = wll.within_language_llr(briefing, min_term_count=10)
        # Both A and B should have distinctive terms
        self.assertIn("A", out["by_bucket"])
        self.assertIn("B", out["by_bucket"])
        # A's distinctive terms should include "blockade"; B's "summit"
        a_terms = {t["term"] for t in out["by_bucket"]["A"]["distinctive_terms"]}
        b_terms = {t["term"] for t in out["by_bucket"]["B"]["distinctive_terms"]}
        self.assertIn("blockade", a_terms)
        self.assertIn("summit", b_terms)

    def test_within_language_llr_skips_singleton_lang(self):
        from analytical import within_language_llr as wll
        # Only one bucket in language → no cohort → bucket excluded from output
        briefing = {
            "corpus": [
                {"bucket": "A", "lang": "fr", "title": "x", "signal_text": "z " * 50}
            ]
        }
        out = wll.within_language_llr(briefing)
        self.assertEqual(out["by_bucket"], {})

    def test_within_language_llr_excludes_opinion_items(self):
        from analytical import within_language_llr as wll
        briefing = {
            "corpus": [
                {"bucket": "A", "lang": "en", "section": "opinion",
                 "title": "OP", "signal_text": "manifesto " * 50},
                {"bucket": "B", "lang": "en", "section": "news",
                 "title": "N", "signal_text": "story " * 50},
                {"bucket": "C", "lang": "en", "section": "news",
                 "title": "M", "signal_text": "report " * 50},
            ]
        }
        out = wll.within_language_llr(briefing, min_term_count=5)
        # A is opinion → not in output
        self.assertNotIn("A", out["by_bucket"])

    def test_within_language_pmi_basic(self):
        if "analytical.within_language_pmi" in sys.modules:
            importlib.reload(sys.modules["analytical.within_language_pmi"])
        from analytical import within_language_pmi as wpmi
        briefing = {
            "corpus": [
                {"bucket": "A", "lang": "en", "title": "x",
                 "signal_text": "supply shock crisis " * 30},
                {"bucket": "B", "lang": "en", "title": "y",
                 "signal_text": "summit talks regional " * 30},
            ]
        }
        out = wpmi.within_language_pmi(briefing, min_count=5)
        self.assertIn("A", out["by_bucket"])
        a_bigrams = {tuple(a["bigram"]) for a in out["by_bucket"]["A"]["associations"]}
        self.assertIn(("supply", "shock"), a_bigrams)

    def test_headline_body_divergence_skips_no_headline(self):
        if "analytical.headline_body_divergence" in sys.modules:
            importlib.reload(sys.modules["analytical.headline_body_divergence"])
        from analytical import headline_body_divergence as hbd
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            body_path = tdp / "2026-05-09_x.json"
            body_path.write_text(json.dumps({
                "story_key": "x", "date": "2026-05-09", "frames": [
                    {"frame_id": "F1", "buckets": ["a"], "evidence": []}
                ]
            }))
            r = hbd.process_one(body_path, out_dir=tdp)
            self.assertTrue(r.get("skipped"))
            self.assertEqual(r["reason"], "no_headline_pass_yet")

    def test_headline_body_divergence_basic(self):
        from analytical import headline_body_divergence as hbd
        body = {
            "story_key": "x",
            "frames": [
                {"frame_id": "F1", "buckets": ["a", "b"],
                 "evidence": [{"bucket": "a"}, {"bucket": "b"}]},
                {"frame_id": "F2", "buckets": ["c"],
                 "evidence": [{"bucket": "c"}]},
            ]
        }
        # Headline: a stays in F1; b SHIFTS to F2; c stays in F2.
        headline = {
            "story_key": "x",
            "frames": [
                {"frame_id": "F1", "buckets": ["a"],
                 "evidence": [{"bucket": "a"}]},
                {"frame_id": "F2", "buckets": ["b", "c"],
                 "evidence": [{"bucket": "b"}, {"bucket": "c"}]},
            ]
        }
        d = hbd.divergence(body, headline)
        self.assertEqual(d["n_buckets_compared"], 3)
        self.assertEqual(d["n_bucket_agreements"], 2)
        # b is the diverging bucket
        diverging_buckets = {b["bucket"] for b in d["highest_diverging_buckets"]}
        self.assertEqual(diverging_buckets, {"b"})

    def test_cross_outlet_lag_insufficient_history(self):
        if "analytical.cross_outlet_lag" in sys.modules:
            importlib.reload(sys.modules["analytical.cross_outlet_lag"])
        from analytical import cross_outlet_lag as col
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # Only 5 days of coverage → insufficient
            for i in range(5):
                d = f"2026-05-{i+1:02d}"
                (tdp / f"{d}.json").write_text(json.dumps({
                    "date": d, "coverage": {}, "summary": {}
                }))
            history = col.load_coverage_history(window_days=30,
                                                 today="2026-05-30",
                                                 cov_dir=tdp)
            self.assertEqual(len(history), 5)
            # Main path skips when n < min_days; we test the load directly here.

    def test_cross_outlet_lag_pearson_at_lag(self):
        from analytical import cross_outlet_lag as col
        # Perfectly lagged: B = A shifted right by 2
        a = [1, 0, 0, 1, 0, 0, 1, 0, 0, 1]
        b = [0, 0, 1, 0, 0, 1, 0, 0, 1, 0]
        # A leads B by 2 → high correlation at lag=2
        r2 = col.pearson_at_lag(a, b, lag=2)
        r0 = col.pearson_at_lag(a, b, lag=0)
        self.assertIsNotNone(r2)
        self.assertGreater(r2, 0.5)
        # At lag=0 they should be uncorrelated or anticorrelated
        self.assertLess(r0 if r0 is not None else 0, r2)

    def test_replay_steps_format(self):
        # Simply verify the STEPS table is well-formed (each cmd is list[str])
        sys.path.insert(0, str(ROOT))
        if "replay" in sys.modules:
            importlib.reload(sys.modules["replay"])
        import replay
        for name, cmd in replay.STEPS:
            self.assertIsInstance(name, str)
            self.assertIsInstance(cmd, list)
            self.assertTrue(all(isinstance(c, str) for c in cmd))

    def test_rollup_finds_old_files(self):
        if "pipeline.rollup" in sys.modules:
            importlib.reload(sys.modules["pipeline.rollup"])
        from pipeline import rollup
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            snaps = tdp / "snapshots"; snaps.mkdir()
            briefs = tdp / "briefings"; briefs.mkdir()
            # Make 4 files: 2 old (>90 days), 2 fresh
            for d in ["2025-01-01", "2025-02-15"]:
                (snaps / f"{d}.json").write_text("{}")
                (briefs / f"{d}_x.json").write_text("{}")
            for d in ["2026-04-15", "2026-05-08"]:
                (snaps / f"{d}.json").write_text("{}")
                (briefs / f"{d}_x.json").write_text("{}")
            cands = rollup.find_candidates(window_days=90, today="2026-05-09",
                                            snaps_dir=snaps, briefings_dir=briefs)
            # Only 2025-* should be flagged (>90d before 2026-05-09)
            self.assertIn("2025-01", cands["snapshots"])
            self.assertIn("2025-02", cands["snapshots"])
            self.assertNotIn("2026-04", cands["snapshots"])
            self.assertNotIn("2026-05", cands["snapshots"])

    def test_x_poster_skipped_no_token(self):
        if "distribution.x_poster" in sys.modules:
            importlib.reload(sys.modules["distribution.x_poster"])
        from distribution import x_poster
        # No tokens in env → secrets check fails → would_post is False
        for k in x_poster.REQUIRED_SECRETS:
            self.assertFalse(os.environ.get(k))  # confirm clean env

    def test_x_poster_payloads_with_thread_link(self):
        from distribution import x_poster
        thread = {
            "story_key": "test",
            "date": "2026-05-08",
            "tweets": [{"text": "First"}, {"text": "Second"}, {"text": ""}],
        }
        ps = x_poster.build_payloads(thread, public_url_base="https://x.test")
        # Empty tweet excluded; first tweet gets link appended
        self.assertEqual(len(ps), 2)
        self.assertIn("https://x.test/2026-05-08/test/", ps[0]["text"])
        self.assertEqual(ps[1]["text"], "Second")


class TestPhase3SourceAttribution(unittest.TestCase):
    """Phase 3a-3c: source/quote attribution + aggregation + validator."""

    def _briefing(self):
        return {
            "date": "2026-05-09",
            "story_key": "test",
            "corpus": [
                {"bucket": "usa", "feed": "Outlet A", "lang": "en",
                 "title": "...", "signal_text":
                 'Trump said: "We will continue the blockade." Officials warn.'},
                {"bucket": "iran_state", "feed": "Outlet B", "lang": "en",
                 "title": "...", "signal_text":
                 'A spokesperson claimed: "Sanctions will fail."'},
            ]
        }

    def _sources_doc(self):
        return {
            "story_key": "test",
            "date": "2026-05-09",
            "sources": [
                {"speaker_name": "Trump", "role_or_affiliation": "US President",
                 "speaker_type": "official",
                 "speaker_affiliation_bucket": "state",
                 "speaker_affiliation_kind": "US Executive Branch",
                 "exact_quote": 'We will continue the blockade.',
                 "attributive_verb": "said",
                 "stance_toward_target": "for",
                 "signal_text_idx": 0,
                 "bucket": "usa", "outlet": "Outlet A"},
                {"speaker_name": None, "role_or_affiliation": "spokesperson",
                 "speaker_type": "spokesperson",
                 "speaker_affiliation_bucket": "state",
                 "speaker_affiliation_kind": "Iran Foreign Ministry",
                 "exact_quote": 'Sanctions will fail.',
                 "attributive_verb": "claimed",
                 "stance_toward_target": "against",
                 "signal_text_idx": 1,
                 "bucket": "iran_state", "outlet": "Outlet B"},
            ]
        }

    def test_source_attribution_validate_clean(self):
        if "analytical.source_attribution" in sys.modules:
            importlib.reload(sys.modules["analytical.source_attribution"])
        from analytical import source_attribution as sa
        errs = sa.validate_sources(self._sources_doc(), self._briefing())
        self.assertEqual(errs, [])

    def test_source_attribution_validate_catches_fabricated_quote(self):
        from analytical import source_attribution as sa
        bad = json.loads(json.dumps(self._sources_doc()))
        bad["sources"][0]["exact_quote"] = "this is not in the article"
        errs = sa.validate_sources(bad, self._briefing())
        self.assertTrue(any("not found verbatim" in e for e in errs),
                        msg=f"expected verbatim error, got: {errs}")

    def test_source_attribution_validate_catches_bad_speaker_type(self):
        from analytical import source_attribution as sa
        bad = json.loads(json.dumps(self._sources_doc()))
        bad["sources"][0]["speaker_type"] = "bogus"
        errs = sa.validate_sources(bad, self._briefing())
        self.assertTrue(any("speaker_type" in e for e in errs))

    def test_source_attribution_validate_catches_bad_stance(self):
        from analytical import source_attribution as sa
        bad = json.loads(json.dumps(self._sources_doc()))
        bad["sources"][0]["stance_toward_target"] = "bogus"
        errs = sa.validate_sources(bad, self._briefing())
        self.assertTrue(any("stance_toward_target" in e for e in errs))

    def test_source_attribution_list_pending(self):
        from analytical import source_attribution as sa
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td)
            briefing = self._briefing()
            # Nothing cached yet → all pending
            pending = sa.list_pending(briefing, cache_dir=cache)
            self.assertEqual(len(pending), 2)
            # Mark first as cached
            sha0 = sa.article_sha(briefing["corpus"][0])
            sa.update_cache(sha0, "test", n_quotes=1, cache_dir=cache)
            pending = sa.list_pending(briefing, cache_dir=cache)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["bucket"], "iran_state")

    def test_source_aggregation_basic(self):
        if "analytical.source_aggregation" in sys.modules:
            importlib.reload(sys.modules["analytical.source_aggregation"])
        from analytical import source_aggregation as sag
        sources_with_story = [
            {**s, "story_key": "test"}
            for s in self._sources_doc()["sources"]
        ]
        agg = sag.aggregate(sources_with_story)
        # Per-outlet: Outlet A has 1 quote from Trump
        self.assertEqual(agg["by_outlet"]["Outlet A"]["n_quotes"], 1)
        self.assertEqual(agg["by_outlet"]["Outlet A"]["top_speakers"][0][0], "Trump")
        # Per-region: usa is americas; iran_state is middle_east
        self.assertIn("americas", agg["by_region"])
        self.assertIn("middle_east", agg["by_region"])
        # Stance mix in americas: 1 "for"
        self.assertEqual(agg["by_region"]["americas"]["stance_mix"]["for"], 1)
        self.assertEqual(agg["by_region"]["middle_east"]["stance_mix"]["against"], 1)

    def test_source_aggregation_region_for(self):
        from analytical import source_aggregation as sag
        self.assertEqual(sag.region_for("usa"), "americas")
        self.assertEqual(sag.region_for("germany"), "europe")
        self.assertEqual(sag.region_for("iran_state"), "middle_east")
        self.assertEqual(sag.region_for("china"), "asia_pacific")
        self.assertEqual(sag.region_for("south_africa"), "africa")
        self.assertEqual(sag.region_for("wire_services"), "wire")
        self.assertEqual(sag.region_for("unknown_bucket"), "other")

    def test_validator_quote_grounding_sources(self):
        if "analytical.validate_analysis" in sys.modules:
            importlib.reload(sys.modules["analytical.validate_analysis"])
        from analytical import validate_analysis as va
        # Clean
        errs = va.check_quote_grounding_sources(self._sources_doc(), self._briefing())
        self.assertEqual(errs, [])
        # Fabricated
        bad = json.loads(json.dumps(self._sources_doc()))
        bad["sources"][0]["exact_quote"] = "not in any article"
        errs = va.check_quote_grounding_sources(bad, self._briefing())
        self.assertTrue(any("not found verbatim" in e for e in errs))


class TestPhase4Modules(unittest.TestCase):
    """Phase 4e/4f/4h: wire baseline + tilt index + robustness check.
    Plus Phase 3i bucket-feed-set hash."""

    def test_bucket_feed_set_hash_stable(self):
        # Same bucket should give the same hash on repeat calls.
        if "meta" in sys.modules:
            importlib.reload(sys.modules["meta"])
        import meta as m
        h1 = m.bucket_feed_set_hash("wire_services")
        h2 = m.bucket_feed_set_hash("wire_services")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)  # truncated sha256

    def test_bucket_feed_set_hash_differs_per_bucket(self):
        import meta as m
        h_wire = m.bucket_feed_set_hash("wire_services")
        h_uk = m.bucket_feed_set_hash("uk")
        self.assertNotEqual(h_wire, h_uk)

    def test_wire_baseline_skips_insufficient_history(self):
        if "analytical.wire_baseline" in sys.modules:
            importlib.reload(sys.modules["analytical.wire_baseline"])
        from analytical import wire_baseline as wb
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            articles = wb.collect_wire_articles(window_days=30,
                                                  today="2026-05-09",
                                                  briefings_dir=tdp)
            self.assertEqual(articles, [])

    def test_wire_baseline_collects_wire_articles(self):
        from analytical import wire_baseline as wb
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "2026-05-08_x.json").write_text(json.dumps({
                "corpus": [
                    {"bucket": "wire_services", "title": "x",
                     "signal_text": "wire copy here"},
                    {"bucket": "uk", "title": "y",
                     "signal_text": "non-wire"},
                ]
            }))
            arts = wb.collect_wire_articles(window_days=30,
                                              today="2026-05-09",
                                              briefings_dir=tdp)
            self.assertEqual(len(arts), 1)
            self.assertEqual(arts[0]["bucket"], "wire_services")

    def test_wire_baseline_build_bigrams(self):
        from analytical import wire_baseline as wb
        articles = [
            {"title": "a", "signal_text": "supply shock crisis " * 5},
        ]
        bigrams = wb.build_bigrams(articles)
        self.assertGreater(bigrams[("supply", "shock")], 0)

    def test_tilt_index_log_odds_consistent(self):
        if "analytical.tilt_index" in sys.modules:
            importlib.reload(sys.modules["analytical.tilt_index"])
        from analytical import tilt_index as ti
        from collections import Counter
        outlet = Counter({("a", "b"): 10, ("c", "d"): 1})
        wire = Counter({("a", "b"): 1, ("e", "f"): 5})
        result = ti.compute_outlet_tilt(outlet, wire, min_count=1, top_k=10)
        # ('a','b') should be positive-tilt (10× more in outlet than wire).
        pos_bigrams = {tuple(p["bigram"]) for p in result["positive_tilt"]}
        self.assertIn(("a", "b"), pos_bigrams)
        # ('e','f') should be negative-tilt (in wire, not outlet).
        neg_bigrams = {tuple(p["bigram"]) for p in result["negative_tilt"]}
        self.assertIn(("e", "f"), neg_bigrams)

    def test_tilt_index_parse_baseline_bigrams(self):
        from analytical import tilt_index as ti
        baseline = {"bigrams": {"a|b": 5, "c|d": 3, "no_pipe": 1}}
        cnt = ti.parse_baseline_bigrams(baseline)
        self.assertEqual(cnt[("a", "b")], 5)
        self.assertEqual(cnt[("c", "d")], 3)
        self.assertNotIn("no_pipe", cnt)

    def test_robustness_jaccard(self):
        if "analytical.robustness_check" in sys.modules:
            importlib.reload(sys.modules["analytical.robustness_check"])
        from analytical import robustness_check as rc
        self.assertEqual(rc.jaccard({"a", "b"}, {"a", "b"}), 1.0)
        self.assertAlmostEqual(rc.jaccard({"a", "b", "c"}, {"a", "b", "d"}), 2 / 4)
        self.assertEqual(rc.jaccard({"a"}, {"b"}), 0.0)
        self.assertIsNone(rc.jaccard(set(), set()))

    def test_robustness_compute(self):
        from analytical import robustness_check as rc
        traj = {
            "frame_trajectories": {
                "F1": [{"date": "2026-05-07"}, {"date": "2026-05-08"}],
                "F2": [{"date": "2026-05-07"}],  # F2 disappeared on 5/8
                "F3": [{"date": "2026-05-08"}],  # F3 new on 5/8
            }
        }
        result = rc.compute_robustness(traj, threshold=0.5)
        self.assertFalse(result.get("skipped"))
        # Day1: {F1, F2}; Day2: {F1, F3}. Jaccard = 1/3 ≈ 0.333
        self.assertAlmostEqual(result["stability"], 1 / 3, places=2)
        self.assertTrue(result["low_stability"])  # below 0.5

    def test_robustness_skips_one_day(self):
        from analytical import robustness_check as rc
        traj = {
            "frame_trajectories": {
                "F1": [{"date": "2026-05-07"}],
            }
        }
        result = rc.compute_robustness(traj)
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result["reason"], "insufficient_history")


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
            "tldr": "A test analysis with three sentences. Six buckets carry two distinct frames. No paradox detected in this corpus.",
            "frames": [
                {"frame_id": "ECONOMIC", "sub_frame": "energy contagion",
                 "buckets": ["italy", "usa"],
                 "evidence": [{"bucket": "italy", "outlet": "ANSA",
                               "quote": "guerra accordo", "signal_text_idx": 0}]},
                {"frame_id": "SECURITY_DEFENSE",
                 "buckets": ["china", "japan"],
                 "evidence": [{"bucket": "china", "quote": "blockade", "signal_text_idx": 4}]},
            ],
            "isolation_top": [{"bucket": "italy", "mean_similarity": 0.18}],
            "exclusive_vocab_highlights": [
                {"bucket": "italy", "terms": ["guerra"], "what_it_reveals": "war framing."}
            ],
            "paradox": None,
            "silences": [{"bucket": "egypt", "what_they_covered_instead": "Sisi."}],
            "single_outlet_findings": [
                {"outlet": "RT", "bucket": "russia", "finding": "Iran-win frame.", "signal_text_idx": 5}
            ],
            "bottom_line": "Two short sentences restating the headline. End.",
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
        self.assertIn("### ECONOMIC — energy contagion", md)
        self.assertIn("### SECURITY_DEFENSE", md)
        self.assertIn("## Most divergent buckets", md)
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
            "tldr": "Twenty-seven outlets ran the same wire. Italy used different words. Vocabulary carries the framing.",
            "frames": [
                {"frame_id": "ECONOMIC", "sub_frame": "energy-price contagion",
                 "label": "ECONOMIC_CONTAGION", "buckets": ["philippines", "japan"],
                 "evidence": [{"bucket": "asia_pacific_regional", "outlet": "Asia Times",
                               "quote": "shock inflation spike in April", "signal_text_idx": 1}]},
                {"frame_id": "SECURITY_DEFENSE", "sub_frame": "war framing",
                 "label": "WAR_FRAMING", "buckets": ["italy"],
                 "evidence": [{"bucket": "italy", "outlet": "ANSA",
                               "quote": "guerra accordo", "signal_text_idx": 0}]}
            ],
            "isolation_top": [
                {"bucket": "italy", "mean_similarity": 0.18, "note": "linguistic."}
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
            "bottom_line": "Headline converged. Framing did not.",
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
            "tldr": "A clean analysis with multiple complete sentences. The corpus has 41 articles. The pin is 1.3.0.",
            "frames": [
                {"frame_id": "ECONOMIC",
                 "buckets": [first_bucket],
                 "evidence": [{
                     "bucket": first_bucket,
                     "outlet": self.first_corpus.get("feed", "Unknown"),
                     "quote": first_text[:60].strip(),
                     "signal_text_idx": 0,
                 }]},
                {"frame_id": "SECURITY_DEFENSE",
                 "buckets": ["other"],
                 "evidence": [{
                     "bucket": self.briefing["corpus"][1]["bucket"],
                     "quote": self.briefing["corpus"][1]["signal_text"][:50].strip(),
                     "signal_text_idx": 1,
                 }]}
            ],
            "isolation_top": [
                {"bucket": self.metrics["isolation"][0]["bucket"],
                 "mean_similarity": self.metrics["isolation"][0]["mean_similarity"]}
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
            {"bucket": self.metrics["isolation"][0]["bucket"], "mean_similarity": 0.999}
        ]
        errs = v.check_numbers(bad, self.metrics)
        self.assertTrue(any("mean_similarity" in e for e in errs))

    def test_isolation_unknown_bucket_caught(self):
        from analytical import validate_analysis as v
        bad = dict(self.clean)
        bad["isolation_top"] = [{"bucket": "fake_bucket_xyz", "mean_similarity": 0.5}]
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


class TestFeedRotCheck(unittest.TestCase):
    """pipeline/feed_rot_check.py: weekly rot detection (audit Gap 15-1 + 15-2).

    Cherry-picked from audit commit 82fc704. The decline + growth cases
    are regression guards against re-introducing the sign-inversion bug
    that flagged GROWING feeds as declining.
    """

    def setUp(self):
        if "pipeline.feed_rot_check" in sys.modules:
            importlib.reload(sys.modules["pipeline.feed_rot_check"])
        from pipeline import feed_rot_check
        self.frc = feed_rot_check

    def _write_window(self, td: Path, days: list[dict]) -> None:
        """days = list of {date, errors, stub_feeds, feeds} dicts from
        OLDEST to NEWEST. Writes both <date>_health.json and <date>.json
        for each day."""
        snaps = td / "snapshots"
        snaps.mkdir(parents=True, exist_ok=True)
        for d in days:
            date = d["date"]
            (snaps / f"{date}_health.json").write_text(json.dumps({
                "date": date,
                "errors": d.get("errors", []),
                "stub_feeds": d.get("stub_feeds", []),
            }))
            (snaps / f"{date}.json").write_text(json.dumps({
                "countries": {
                    "wire": {
                        "feeds": [
                            {"name": fn, "item_count": ic}
                            for fn, ic in d.get("feeds", {}).items()
                        ]
                    }
                }
            }))

    def _run(self, td: Path, n_days: int, today_iso: str = "2026-05-09") -> str:
        import datetime as _dt
        review = td / "review"
        review.mkdir(parents=True, exist_ok=True)
        fixed_today = _dt.date.fromisoformat(today_iso)

        class FixedDateTime(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return _dt.datetime.combine(fixed_today, _dt.time(0), tzinfo=tz)

        with patch.multiple(self.frc, SNAPS=td / "snapshots", REVIEW=review), \
             patch.object(self.frc, "datetime", FixedDateTime):
            self.frc.main(n_days=n_days)
        return (review / f"rot_report_{today_iso}.md").read_text(encoding="utf-8")

    def test_decline_detection_flags_actually_declining_feeds(self):
        """Regression for audit Gap 15-1: a feed dropping 100 → 20 over
        7 days MUST be flagged."""
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            base_date = "2026-05-09"
            import datetime as _dt
            today = _dt.date.fromisoformat(base_date)
            days = []
            counts = [100, 90, 80, 60, 40, 30, 20]
            for i, c in enumerate(counts):
                d = (today - _dt.timedelta(days=6 - i)).isoformat()
                days.append({"date": d, "feeds": {"DeclineFeed": c}})
            self._write_window(td, days)
            report = self._run(td, n_days=7, today_iso=base_date)
            self.assertIn("DeclineFeed", report,
                          "actually-declining feed must be in the rot report")
            self.assertIn("100 -> 20", report,
                          "report should show chronological oldest → today")

    def test_decline_detection_ignores_growing_feeds(self):
        """Regression for audit Gap 15-1: a feed growing 20 → 100 must
        NOT be flagged. The original bug flagged this as 'declining'."""
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            base_date = "2026-05-09"
            import datetime as _dt
            today = _dt.date.fromisoformat(base_date)
            days = []
            counts = [20, 30, 40, 60, 80, 90, 100]
            for i, c in enumerate(counts):
                d = (today - _dt.timedelta(days=6 - i)).isoformat()
                days.append({"date": d, "feeds": {"GrowingFeed": c}})
            self._write_window(td, days)
            report = self._run(td, n_days=7, today_iso=base_date)
            self.assertNotIn("GrowingFeed", report,
                             "growing feed must NOT be flagged as declining")

    def test_persistent_error_streak_flagged(self):
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            base_date = "2026-05-09"
            import datetime as _dt
            today = _dt.date.fromisoformat(base_date)
            days = []
            for i in range(7):
                d = (today - _dt.timedelta(days=6 - i)).isoformat()
                errors = ([{"bucket": "wire", "feed": "BrokenFeed"}]
                          if i < 5 else [])
                days.append({"date": d, "errors": errors})
            self._write_window(td, days)
            report = self._run(td, n_days=7, today_iso=base_date)
            self.assertIn("BrokenFeed", report)
            self.assertIn("errored 5/7 days", report)

    def test_report_carries_meta_version(self):
        """Audit Gap 15-3: report must declare the methodology pin."""
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            base_date = "2026-05-09"
            import datetime as _dt
            today = _dt.date.fromisoformat(base_date)
            d = (today - _dt.timedelta(days=1)).isoformat()
            self._write_window(td, [{"date": d, "feeds": {"X": 1}}])
            report = self._run(td, n_days=7, today_iso=base_date)
            import meta as _meta
            self.assertIn(f"meta_version {_meta.VERSION}", report)


class TestSchemaCorpus(unittest.TestCase):
    """PR 1: every schema in docs/api/schema/ must itself be a valid
    JSON Schema Draft 2020-12 document, and every pipeline-written
    artifact schema must require meta_version. Cherry-picked from the
    audit branch's Stage 14 work and adapted to v8's artifact list."""

    def setUp(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")
        self.jsonschema = jsonschema
        self.schema_dir = Path(__file__).parent / "docs/api/schema"

    def test_every_schema_is_valid_draft_2020_12(self):
        validator_cls = self.jsonschema.Draft202012Validator
        for p in sorted(self.schema_dir.glob("*.schema.json")):
            with self.subTest(schema=p.name):
                schema = json.loads(p.read_text(encoding="utf-8"))
                validator_cls.check_schema(schema)
                self.assertEqual(
                    schema.get("$schema"),
                    "https://json-schema.org/draft/2020-12/schema",
                    f"{p.name} must declare draft 2020-12",
                )

    def test_artifact_schemas_require_meta_version(self):
        """Every pipeline-written artifact schema (i.e. not pure configs
        like feeds / canonical_stories) must require meta_version in its
        top-level required[]."""
        artifact_schemas = (
            "analysis", "briefing", "metrics", "health",
            "thread", "carousel", "long",
            "index", "latest", "video_script",
        )
        for name in artifact_schemas:
            path = self.schema_dir / f"{name}.schema.json"
            if not path.exists():
                continue
            with self.subTest(schema=name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                if "oneOf" in schema:
                    for branch in schema["oneOf"]:
                        self.assertIn(
                            "meta_version", branch.get("required", []),
                            f"{name}.oneOf branch missing meta_version")
                else:
                    self.assertIn(
                        "meta_version", schema.get("required", []),
                        f"{name} must require meta_version")


class TestCoverageMatrix4State(unittest.TestCase):
    """PR 2: pipeline/coverage_matrix.py classifies non-covering buckets
    as silent / errored / dark when joined with daily_health output."""

    def setUp(self):
        from pipeline import coverage_matrix as cm
        self.cm = cm

    def test_classify_non_coverage_distinguishes_three_states(self):
        snapshot = {
            "countries": {
                "italy": {"feeds": [
                    {"name": "ANSA", "items": [{"title": "x"}]},
                ]},
                "germany": {"feeds": [
                    {"name": "Tagesschau", "items": []},
                    {"name": "FAZ", "items": []},
                ]},
                "spain": {"feeds": [
                    {"name": "El Pais", "items": []},
                ]},
            }
        }
        health = {
            "errors": [
                {"bucket": "germany", "feed": "Tagesschau", "http": 503},
                {"bucket": "germany", "feed": "FAZ", "http": 500},
            ]
        }
        # Italy was the only bucket that "covered" the story.
        states = self.cm._classify_non_coverage(
            snapshot, health, buckets_covered={"italy"})
        # italy is excluded (it's covered); germany has all feeds errored
        # and zero items → errored; spain has feeds but zero items and no
        # errors → dark.
        self.assertNotIn("italy", states)
        self.assertEqual(states.get("germany"), "errored")
        self.assertEqual(states.get("spain"), "dark")

    def test_silent_state_when_feeds_have_items_but_none_match(self):
        snapshot = {
            "countries": {
                "italy": {"feeds": [
                    {"name": "ANSA", "items": [{"title": "x"}]},
                ]},
                "france": {"feeds": [
                    {"name": "Le Monde", "items": [
                        {"title": "unrelated story"},
                        {"title": "another"},
                    ]},
                ]},
            }
        }
        health = {"errors": []}
        states = self.cm._classify_non_coverage(
            snapshot, health, buckets_covered={"italy"})
        self.assertEqual(states.get("france"), "silent")

    def test_no_health_yields_no_non_coverage(self):
        snapshot = {"countries": {"italy": {"feeds": []}}}
        # build_coverage_matrix without health should NOT include
        # non_coverage in the output.
        canon = {"x": {"title": "X", "patterns": ["x"]}}
        out = self.cm.build_coverage_matrix(snapshot, stories=canon, health=None)
        self.assertNotIn("non_coverage", out)

    def test_coverage_matrix_passes_its_own_schema(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")
        # Build a minimal valid matrix with non_coverage and verify it
        # round-trips through the new coverage.schema.json.
        snapshot = {
            "date": "2026-05-11",
            "countries": {
                "italy": {"feeds": [
                    {"name": "ANSA", "section": "news", "lang": "it",
                     "items": [{"title": "hormuz crisis"}]},
                ]},
                "germany": {"feeds": [
                    {"name": "Tagesschau", "section": "news", "lang": "de",
                     "items": []},
                ]},
            },
        }
        health = {"errors": [
            {"bucket": "germany", "feed": "Tagesschau", "http": 503}
        ]}
        canon = {"hormuz": {"title": "Hormuz", "tier": "long_running",
                            "patterns": ["hormuz"]}}
        out = self.cm.build_coverage_matrix(snapshot, stories=canon, health=health)
        out["meta_version"] = "test"
        meta.validate_schema(out, "coverage")


class TestSourceAttributionAffiliation(unittest.TestCase):
    """PR 3: source-attribution validator enforces the new
    speaker_affiliation_bucket + speaker_affiliation_kind fields, and
    source_aggregation rolls up the affiliation distribution per outlet
    / bucket / region."""

    def setUp(self):
        from analytical import source_attribution as sa
        from analytical import source_aggregation as sg
        self.sa = sa
        self.sg = sg

    def _valid_source(self, **overrides) -> dict:
        base = {
            "speaker_name": "Trump",
            "role_or_affiliation": "US President",
            "speaker_type": "official",
            "speaker_affiliation_bucket": "state",
            "speaker_affiliation_kind": "US Executive Branch",
            "exact_quote": "We will respond.",
            "attributive_verb": "said",
            "stance_toward_target": "for",
            "signal_text_idx": 0,
            "bucket": "usa",
            "outlet": "Reuters",
        }
        base.update(overrides)
        return base

    def test_validator_requires_new_affiliation_fields(self):
        s = self._valid_source()
        s.pop("speaker_affiliation_bucket")
        briefing = {"corpus": [{"bucket": "usa", "signal_text": "We will respond."}]}
        doc = {"sources": [s]}
        errors = self.sa.validate_sources(doc, briefing)
        self.assertTrue(any("speaker_affiliation_bucket" in e for e in errors),
                        f"missing affiliation_bucket should error; got {errors}")

    def test_validator_rejects_unknown_affiliation_bucket(self):
        s = self._valid_source(speaker_affiliation_bucket="militia")
        briefing = {"corpus": [{"bucket": "usa", "signal_text": "We will respond."}]}
        doc = {"sources": [s]}
        errors = self.sa.validate_sources(doc, briefing)
        self.assertTrue(any("speaker_affiliation_bucket" in e for e in errors))

    def test_aggregation_emits_affiliation_mix(self):
        sources = [
            self._valid_source(speaker_affiliation_bucket="state"),
            self._valid_source(speaker_affiliation_bucket="state"),
            self._valid_source(speaker_affiliation_bucket="academic",
                               outlet="The Atlantic"),
            self._valid_source(speaker_affiliation_bucket="civilian",
                               speaker_affiliation_kind=None),
        ]
        agg = self.sg.aggregate(sources)
        # by_outlet for "Reuters" should show state:2, civilian:1
        reuters = agg["by_outlet"].get("Reuters")
        self.assertIsNotNone(reuters)
        self.assertEqual(reuters["affiliation_mix"].get("state"), 2)
        self.assertEqual(reuters["affiliation_mix"].get("civilian"), 1)
        # The Atlantic is a separate outlet → only academic:1
        atlantic = agg["by_outlet"].get("The Atlantic")
        self.assertEqual(atlantic["affiliation_mix"].get("academic"), 1)

    def test_doc_passes_sources_schema(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")
        doc = {
            "meta_version": "test",
            "story_key": "hormuz",
            "date": "2026-05-11",
            "story_title": "Hormuz",
            "n_articles_processed": 1,
            "sources": [self._valid_source()],
        }
        meta.validate_schema(doc, "sources")


class TestLongitudinalDrivers(unittest.TestCase):
    """PR 5: longitudinal.py attaches article-level `drivers` to
    frame_trajectories entries where day-over-day |Δshare| > 0.10."""

    def setUp(self):
        if "analytical.longitudinal" in sys.modules:
            importlib.reload(sys.modules["analytical.longitudinal"])
        from analytical import longitudinal as lt
        self.lt = lt
        self.tmp = tempfile.TemporaryDirectory()
        self.td = Path(self.tmp.name)
        (self.td / "analyses").mkdir()
        (self.td / "briefings").mkdir()
        # Patch the module's paths.
        self.lt.ANALYSES = self.td / "analyses"
        self.lt.BRIEFINGS = self.td / "briefings"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, date: str, story: str, frames: list, corpus: list):
        ap = self.td / "analyses" / f"{date}_{story}.json"
        bp = self.td / "briefings" / f"{date}_{story}.json"
        ap.write_text(json.dumps({
            "story_key": story, "story_title": "X",
            "date": date, "n_articles": len(corpus),
            "frames": frames, "meta_version": "test",
        }), encoding="utf-8")
        bp.write_text(json.dumps({
            "corpus": corpus,
        }), encoding="utf-8")
        return ap

    def test_drivers_attached_above_threshold(self):
        # Day 1: 2 frames. Frame "A" has 1/3 buckets carrying. Day 2: A has
        # 3/3 buckets carrying. |Δshare| = 0.667 > 0.10 → drivers attached.
        for date, frames in [
            ("2026-05-08", [
                {"label": "A", "buckets": ["italy"],
                 "evidence": [{"bucket": "italy", "signal_text_idx": 0,
                               "outlet": "ANSA"}]},
                {"label": "B", "buckets": ["italy", "germany", "spain"],
                 "evidence": []},
            ]),
            ("2026-05-09", [
                {"label": "A", "buckets": ["italy", "germany", "spain"],
                 "evidence": [
                     {"bucket": "italy", "signal_text_idx": 0, "outlet": "ANSA"},
                     {"bucket": "germany", "signal_text_idx": 1,
                      "outlet": "Tagesschau"},
                     {"bucket": "spain", "signal_text_idx": 2, "outlet": "El Pais"},
                 ]},
                {"label": "B", "buckets": ["italy", "germany", "spain"],
                 "evidence": []},
            ]),
        ]:
            self._write(date, "hormuz", frames=frames,
                corpus=[
                    {"link": f"https://italy/{date}.html", "bucket": "italy",
                     "feed": "ANSA"},
                    {"link": f"https://germany/{date}.html", "bucket": "germany",
                     "feed": "Tagesschau"},
                    {"link": f"https://spain/{date}.html", "bucket": "spain",
                     "feed": "El Pais"},
                ])
        paths = sorted((self.td / "analyses").glob("*_hormuz.json"))
        traj = self.lt.build_trajectory(paths)
        a_entries = traj["frame_trajectories"]["A"]
        self.assertEqual(len(a_entries), 2)
        # Day 1: no drivers (no prior day to compare against)
        self.assertNotIn("drivers", a_entries[0])
        # Day 2: drivers attached (|Δshare| = 0.667 > 0.10)
        self.assertIn("drivers", a_entries[1])
        self.assertIn("delta_share", a_entries[1])
        self.assertGreater(a_entries[1]["delta_share"], 0.10)
        urls = {d["url"] for d in a_entries[1]["drivers"]}
        self.assertIn("https://italy/2026-05-09.html", urls)
        self.assertIn("https://germany/2026-05-09.html", urls)

    def test_drivers_omitted_below_threshold(self):
        # Day 1: share 0.333 (1/3 buckets). Day 2: share 0.333 (1/3). Δ = 0.
        # No drivers, no delta_share.
        for date in ("2026-05-08", "2026-05-09"):
            self._write(date, "hormuz",
                frames=[
                    {"label": "A", "buckets": ["italy"],
                     "evidence": [{"bucket": "italy", "signal_text_idx": 0,
                                   "outlet": "ANSA"}]},
                    {"label": "B", "buckets": ["italy", "germany", "spain"],
                     "evidence": []},
                ],
                corpus=[
                    {"link": f"https://italy/{date}.html", "bucket": "italy",
                     "feed": "ANSA"},
                ])
        paths = sorted((self.td / "analyses").glob("*_hormuz.json"))
        traj = self.lt.build_trajectory(paths)
        a_entries = traj["frame_trajectories"]["A"]
        for e in a_entries:
            self.assertNotIn("drivers", e)
            self.assertNotIn("delta_share", e)

    def test_trajectory_passes_its_own_schema(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")
        self._write("2026-05-08", "hormuz",
            frames=[{"label": "A", "buckets": ["italy"], "evidence": []}],
            corpus=[{"link": "https://italy/x.html", "bucket": "italy",
                     "feed": "ANSA"}])
        paths = sorted((self.td / "analyses").glob("*_hormuz.json"))
        traj = self.lt.build_trajectory(paths)
        traj["meta_version"] = "test"
        meta.validate_schema(traj, "trajectory")


class TestDistributionApprovalGate(unittest.TestCase):
    """PR 6: distribution.stage + distribution.publish replace the
    auto-fire posters with a pending → approved/rejected flow."""

    def setUp(self):
        from distribution import stage as st
        from distribution import publish as pb
        self.st = st
        self.pb = pb
        self.tmp = tempfile.TemporaryDirectory()
        td = Path(self.tmp.name)
        # Point all module path constants at the tempdir
        (td / "drafts").mkdir()
        (td / "videos").mkdir()
        self.st.ROOT = td
        self.st.DRAFTS = td / "drafts"
        self.st.VIDEOS = td / "videos"
        self.st.PENDING_BASE = td / "distribution" / "pending"
        # PLATFORMS is a dict literal with bound paths; rebind to td
        self.st.PLATFORMS["youtube_shorts"]["media_dir"] = td / "videos"
        self.pb.ROOT = td
        self.pb.DIST = td / "distribution"
        self.pb.PENDING = td / "distribution" / "pending"
        self.pb.APPROVED = td / "distribution" / "approved"
        self.pb.REJECTED = td / "distribution" / "rejected"
        self.td = td

    def tearDown(self):
        self.tmp.cleanup()

    def _write_draft(self, name: str, payload: dict) -> None:
        (self.td / "drafts" / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_stage_creates_pending_envelope_per_platform(self):
        # Thread draft → x envelope; long draft → youtube_shorts envelope.
        self._write_draft("2026-05-11_hormuz_iran_thread.json",
                          {"meta_version": meta.VERSION, "story_key": "hormuz_iran",
                           "date": "2026-05-11", "hook": "x", "tweets": [],
                           "title": "x"})
        self._write_draft("2026-05-11_hormuz_iran_long.json",
                          {"meta_version": meta.VERSION, "story_key": "hormuz_iran",
                           "date": "2026-05-11", "title": "x",
                           "body_md": "x" * 2600, "sources": []})
        written = self.st.stage_for_date("2026-05-11")
        names = sorted(p.name for p in written)
        self.assertIn("hormuz_iran_x.json", names)
        self.assertIn("hormuz_iran_youtube_shorts.json", names)

    def test_envelope_passes_its_own_schema(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")
        self._write_draft("2026-05-11_hormuz_iran_thread.json",
                          {"meta_version": meta.VERSION, "story_key": "hormuz_iran",
                           "date": "2026-05-11", "hook": "x", "tweets": [],
                           "title": "x"})
        self.st.stage_for_date("2026-05-11")
        env_path = self.td / "distribution" / "pending" / "2026-05-11" / "hormuz_iran_x.json"
        env = json.loads(env_path.read_text(encoding="utf-8"))
        meta.validate_schema(env, "distribution_pending")

    def test_approve_moves_envelope_to_approved_dir(self):
        self._write_draft("2026-05-11_hormuz_iran_thread.json",
                          {"meta_version": meta.VERSION, "story_key": "hormuz_iran",
                           "date": "2026-05-11", "hook": "x", "tweets": [],
                           "title": "x"})
        self.st.stage_for_date("2026-05-11")
        rc = self.pb.cmd_approve("2026-05-11_hormuz_iran_x")
        self.assertEqual(rc, 0)
        approved = self.td / "distribution" / "approved" / "2026-05-11" / "hormuz_iran_x.json"
        self.assertTrue(approved.exists(), "approved envelope must exist")
        # And the pending dir entry must be gone
        pending = self.td / "distribution" / "pending" / "2026-05-11" / "hormuz_iran_x.json"
        self.assertFalse(pending.exists(), "pending envelope must be moved")
        env = json.loads(approved.read_text(encoding="utf-8"))
        self.assertEqual(env["stage_status"], "approved")
        self.assertIsNotNone(env["approved_at"])

    def test_approve_unknown_id_returns_nonzero(self):
        rc = self.pb.cmd_approve("nope")
        self.assertEqual(rc, 1)

    def test_stage_idempotent_for_already_approved_envelope(self):
        self._write_draft("2026-05-11_hormuz_iran_thread.json",
                          {"meta_version": meta.VERSION, "story_key": "hormuz_iran",
                           "date": "2026-05-11", "hook": "x", "tweets": [],
                           "title": "x"})
        self.st.stage_for_date("2026-05-11")
        self.pb.cmd_approve("2026-05-11_hormuz_iran_x")
        # Re-staging should NOT recreate a pending envelope after approval
        written = self.st.stage_for_date("2026-05-11")
        pending = self.td / "distribution" / "pending" / "2026-05-11" / "hormuz_iran_x.json"
        self.assertFalse(pending.exists(),
                         "re-staging must not overwrite approved decisions")


class TestTiltIndexTwoAnchors(unittest.TestCase):
    """PR 7: tilt_index emits log-odds against TWO anchors (wire and
    cross-bucket-mean) instead of one. The two anchors triangulate so
    consumers don't read 'tilt vs wire' as 'tilt vs neutral.'"""

    def setUp(self):
        from analytical import tilt_index as ti
        self.ti = ti

    def _articles_with_bigrams(self, bigrams_per_article: list[list[tuple]]) -> list[dict]:
        # Build synthetic articles whose tokenizable signal_text yields
        # the given bigrams. Use 4+-char alpha tokens (matches the
        # tokenizer regex \p{L}{4,}).
        out = []
        for bigrams in bigrams_per_article:
            words = []
            for a, b in bigrams:
                words += [a, b]
            out.append({"signal_text": " ".join(words),
                        "title": "x", "lang": "en"})
        return out

    def test_build_bucket_mean_baseline_excludes_wire(self):
        outlets = {
            ("wire_services", "Reuters"): self._articles_with_bigrams(
                [[("alpha", "beta"), ("beta", "gamma")]]),
            ("italy", "ANSA"): self._articles_with_bigrams(
                [[("delta", "epsilon"), ("epsilon", "zeta")]]),
            ("germany", "FAZ"): self._articles_with_bigrams(
                [[("delta", "epsilon"), ("eta", "theta")]]),
        }
        bm = self.ti.build_bucket_mean_baseline(outlets)
        # Wire's (alpha, beta) and (beta, gamma) must NOT be in bucket_mean.
        self.assertEqual(bm[("alpha", "beta")], 0)
        self.assertEqual(bm[("beta", "gamma")], 0)
        # Italy + Germany overlap on (delta, epsilon) → count 2.
        self.assertEqual(bm[("delta", "epsilon")], 2)
        self.assertEqual(bm[("epsilon", "zeta")], 1)

    def test_compute_outlet_tilt_emits_baseline_neutral_fields(self):
        from collections import Counter
        outlet = Counter({("alpha", "beta"): 10, ("gamma", "delta"): 8})
        baseline = Counter({("alpha", "beta"): 1, ("epsilon", "zeta"): 5})
        out = self.ti.compute_outlet_tilt(outlet, baseline, min_count=1, top_k=10)
        # Field names must be the renamed, anchor-neutral ones — not
        # 'count_in_wire'.
        self.assertIn("n_baseline_bigrams", out)
        for row in out["positive_tilt"] + out["negative_tilt"]:
            self.assertIn("count_in_baseline", row)
            self.assertIn("rate_in_baseline", row)
            self.assertNotIn("count_in_wire", row)


class TestClusterDiagnostic(unittest.TestCase):
    """PR 8: pipeline/cluster_diagnostic._cluster_both runs HDBSCAN and
    DBSCAN over the same distance matrix and reports cluster counts,
    silhouette / persistence, and pairwise agreement. Run for a week
    post-merge to validate the HDBSCAN swap; revert if numbers don't
    support it."""

    def setUp(self):
        try:
            import numpy as np
            import sklearn  # noqa
            import hdbscan  # noqa
        except ImportError:
            self.skipTest("numpy / sklearn / hdbscan required")
        from pipeline import cluster_diagnostic as cd
        self.cd = cd

    def _synthetic_distance_matrix(self):
        """Three obvious clusters of three points each: every algorithm
        should find roughly the same structure."""
        import numpy as np
        # 9 points, 3 clusters of 3.
        coords = np.array([
            [0.0, 0.0], [0.05, 0.0], [0.0, 0.05],
            [10.0, 10.0], [10.05, 10.0], [10.0, 10.05],
            [-5.0, 5.0], [-5.05, 5.0], [-5.0, 5.05],
        ])
        from sklearn.metrics.pairwise import euclidean_distances
        dist = euclidean_distances(coords)
        dist = dist / dist.max()  # normalize to [0,1] for cosine-like behavior
        return dist

    def test_cluster_both_returns_expected_keys(self):
        dist = self._synthetic_distance_matrix()
        result = self.cd._cluster_both(dist, min_cluster_size=2,
                                        eps=0.1, min_samples=2)
        self.assertIn("hdbscan", result)
        self.assertIn("dbscan", result)
        self.assertIn("pair_agreement", result)
        self.assertIn("n_clusters", result["hdbscan"])
        self.assertIn("n_clusters", result["dbscan"])
        self.assertIn("n_noise", result["hdbscan"])
        self.assertIn("n_noise", result["dbscan"])
        self.assertIn("pct_disagree", result["pair_agreement"])

    def test_cluster_both_finds_three_clusters_on_separable_data(self):
        dist = self._synthetic_distance_matrix()
        result = self.cd._cluster_both(dist, min_cluster_size=2,
                                        eps=0.1, min_samples=2)
        # Both algorithms should agree on 3 clusters for this data.
        self.assertEqual(result["hdbscan"]["n_clusters"], 3)
        self.assertEqual(result["dbscan"]["n_clusters"], 3)
        # And pairwise disagreement should be 0% (full agreement).
        self.assertEqual(result["pair_agreement"]["pct_disagree"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
