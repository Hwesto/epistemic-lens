"""tests.py — crucial regression tests for the epistemic-lens v10 pipeline.

The v9 suite (3,800+ lines, perception / calibration / canonical-story
heavy) retired with the v10 rebuild. This file keeps only tests that
exercise v10-current behaviour: outlet config, versioned article IDs,
salience ranking, cross-day lineage, briefing assembly, citation
validation, the signal-text fallback chain, and the JSON schemas.

Offline-only — no network, no embedding model. Heavier integration
checks (live ingest) live in tests_edge.py.

Run: python -m unittest tests.tests
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import core.meta as meta


class TestMeta(unittest.TestCase):
    """v10 outlet config — the flat outlet list replaces v9 buckets."""

    def test_outlets_load(self):
        outs = meta.outlets()
        self.assertGreater(len(outs), 100)
        for o in outs[:5]:
            self.assertIn("name", o)
            self.assertIn("country", o)
            self.assertIn("lang", o)

    def test_outlets_by_country_partitions_outlets(self):
        by_c = meta.outlets_by_country()
        self.assertGreater(len(by_c), 10)
        flat = [n for names in by_c.values() for n in names]
        self.assertEqual(len(flat), len(meta.outlets()))

    def test_outlet_by_name_lookup(self):
        idx = meta.outlet_by_name()
        first = meta.outlets()[0]
        self.assertEqual(idx[first["name"]]["country"], first["country"])

    def test_country_weight_default(self):
        # Unknown country → 1.0 default; must never raise.
        self.assertEqual(meta.country_weight("__no_such_country__"), 1.0)

    def test_canonical_stories_empty_in_v10(self):
        # v10 has no canonical set — stories emerge from clustering.
        self.assertEqual(meta.canonical_stories(), {})


class TestArticleId(unittest.TestCase):
    """Versioned article IDs key the embedding cache; a model or
    signal-text-version bump must invalidate every key loudly."""

    def setUp(self):
        from core.embed import article_id
        self.a = article_id

    def test_stable_across_runs(self):
        x = self.a.article_id("BBC", "https://x/1", "model-a", "v1")
        y = self.a.article_id("BBC", "https://x/1", "model-a", "v1")
        self.assertEqual(x, y)
        self.assertEqual(len(x), 12)

    def test_version_keyed(self):
        base = self.a.article_id("BBC", "https://x/1", "model-a", "v1")
        self.assertNotEqual(
            base, self.a.article_id("BBC", "https://x/1", "model-b", "v1"))
        self.assertNotEqual(
            base, self.a.article_id("BBC", "https://x/1", "model-a", "v2"))

    def test_signal_excerpt_fallback_chain(self):
        # body >= 100 chars → title + body
        long_body = {"title": "T", "body_text": "B" * 200}
        self.assertTrue(
            self.a.signal_excerpt_for_embedding(long_body).startswith("T\n"))
        # short body, summary >= 60 → title + summary
        with_summary = {"title": "T", "body_text": "x", "summary": "S" * 80}
        self.assertIn("S" * 80,
                      self.a.signal_excerpt_for_embedding(with_summary))
        # nothing usable → title only
        self.assertEqual(
            self.a.signal_excerpt_for_embedding({"title": "OnlyTitle"}),
            "OnlyTitle")

    def test_model_input_prefix(self):
        self.assertEqual(
            self.a.model_input_prefix("intfloat/multilingual-e5-large"),
            "passage: ")
        self.assertEqual(
            self.a.model_input_prefix("sentence-transformers/LaBSE"), "")


class TestSalience(unittest.TestCase):
    """Cluster salience ranking — the formula that picks the day's top N."""

    def setUp(self):
        from core.cluster import salience
        self.s = salience

    def test_monotonic_in_article_count(self):
        small = {"n_articles": 5, "n_countries": 3, "n_langs": 1}
        big = {"n_articles": 50, "n_countries": 3, "n_langs": 1}
        self.assertLess(self.s.score_cluster(small, 10),
                        self.s.score_cluster(big, 10))

    def test_multilingual_bonus(self):
        mono = {"n_articles": 10, "n_countries": 5, "n_langs": 1}
        multi = {"n_articles": 10, "n_countries": 5, "n_langs": 3}
        self.assertAlmostEqual(self.s.score_cluster(multi, 10),
                               1.5 * self.s.score_cluster(mono, 10))

    def test_country_spread_capped_at_one(self):
        # n_countries above the day's total still caps the spread factor.
        c = {"n_articles": 10, "n_countries": 20, "n_langs": 1}
        self.assertEqual(self.s.score_cluster(c, 5), 10.0)


class TestLineage(unittest.TestCase):
    """Cross-day cluster lineage via member-article-ID Jaccard overlap.
    The lineage_id is the stable cross-day story identity."""

    def setUp(self):
        from core.cluster import lineage
        self.L = lineage
        self.tmp = tempfile.mkdtemp()
        self.snaps = Path(self.tmp) / "snapshots"
        self.snaps.mkdir()
        self._orig = lineage.SNAPSHOTS
        lineage.SNAPSHOTS = self.snaps

    def tearDown(self):
        self.L.SNAPSHOTS = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_day(self, date, clusters):
        (self.snaps / f"{date}_clusters.json").write_text(
            json.dumps({"date": date, "clusters": clusters}))

    def test_jaccard(self):
        self.assertEqual(self.L._jaccard(set(), set()), 0.0)
        self.assertEqual(self.L._jaccard({"a"}, {"a"}), 1.0)
        self.assertAlmostEqual(
            self.L._jaccard({"a", "b", "c"}, {"b", "c", "d"}), 0.5)

    def test_lineage_id_stable(self):
        a = self.L._lineage_id("2026-05-12", 7)
        self.assertEqual(a, self.L._lineage_id("2026-05-12", 7))
        self.assertNotEqual(a, self.L._lineage_id("2026-05-12", 8))
        self.assertTrue(a.startswith("L"))

    def test_single_day_yields_no_lineage(self):
        self._write_day("2026-05-12",
                        [{"cluster_id": 0, "member_article_ids": ["a", "b"]}])
        self.assertEqual(self.L.build_lineages(7, "2026-05-12", 0.30), [])

    def test_two_day_overlap_links_into_lineage(self):
        # 3 of 7 members shared → Jaccard 0.43, above the 0.30 default.
        self._write_day("2026-05-11", [{
            "cluster_id": 0,
            "member_article_ids": ["a", "b", "c", "d", "e"],
            "country_distribution": {"usa": 2, "uk": 3},
            "top_tokens": ["summit"]}])
        self._write_day("2026-05-12", [{
            "cluster_id": 5,
            "member_article_ids": ["a", "b", "c", "f", "g"],
            "country_distribution": {"usa": 2, "france": 3},
            "top_tokens": ["summit"]}])
        out = self.L.build_lineages(7, "2026-05-12", 0.30)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["day_count"], 2)
        # Union of country distributions across both days.
        self.assertEqual(out[0]["n_countries_union"], 3)

    def test_below_threshold_does_not_link(self):
        # 1 of 7 members shared → Jaccard 0.14, below 0.30.
        self._write_day("2026-05-11", [{
            "cluster_id": 0, "member_article_ids": ["a", "b", "c", "d"]}])
        self._write_day("2026-05-12", [{
            "cluster_id": 1, "member_article_ids": ["a", "x", "y", "z"]}])
        self.assertEqual(self.L.build_lineages(7, "2026-05-12", 0.30), [])


class TestQualifying(unittest.TestCase):
    """qualifying.list_qualifying — the analyze-matrix gate (n_outlets>=3)."""

    def setUp(self):
        from core.briefing import qualifying
        self.q = qualifying
        self.tmp = tempfile.mkdtemp()
        self.bdir = Path(self.tmp)
        self._orig = qualifying.BRIEFINGS
        qualifying.BRIEFINGS = self.bdir

    def tearDown(self):
        self.q.BRIEFINGS = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, doc):
        (self.bdir / name).write_text(json.dumps(doc))

    def test_gate_filters_by_n_outlets(self):
        self._write("2026-05-20_La1.json", {"n_outlets": 5})
        self._write("2026-05-20_Lb2.json", {"n_outlets": 2})   # below gate
        self._write("2026-05-20_Lc3.json", {"n_outlets": 3})   # exact
        ids = self.q.list_qualifying("2026-05-20", min_outlets=3)
        self.assertEqual(sorted(ids), ["La1", "Lc3"])

    def test_sibling_artefacts_excluded(self):
        self._write("2026-05-20_La1.json", {"n_outlets": 5})
        self._write("2026-05-20_La1_metrics.json", {"n_outlets": 9})
        self._write("2026-05-20_La1_headline.json", {"n_outlets": 9})
        self.assertEqual(
            self.q.list_qualifying("2026-05-20", min_outlets=3), ["La1"])


class TestBriefingBuild(unittest.TestCase):
    """build_briefing_for_cluster — corpus entries are outlet-keyed (v10)."""

    def test_corpus_is_outlet_and_country_keyed(self):
        from core.briefing import build
        from core.embed import article_id as aid

        model = meta.PERCEPTION.get("embedding_model") or ""
        sig = meta.PERCEPTION.get("signal_text_version", "v1")
        body = "This is a sufficiently long article body for signal text. " * 12

        feeds_spec = [
            ("BBC News", "https://bbc/1", "Leaders meet for a summit"),
            ("Le Monde", "https://lemonde/1", "Les dirigeants au sommet"),
        ]
        feeds, member_ids = [], []
        for name, link, title in feeds_spec:
            member_ids.append(aid.article_id(name, link, model, sig))
            feeds.append({
                "name": name, "lang": "en",
                "items": [{"title": title, "link": link, "body_text": body}],
            })
        snap = {"date": "2026-05-20",
                "countries": {"usa": {"label": "USA", "feeds": feeds}}}
        cluster = {"cluster_id": 3, "member_article_ids": member_ids,
                   "salience_score": 12.0, "top_tokens": ["summit"]}

        briefing = build.build_briefing_for_cluster(cluster, snap, "Ltest01")
        self.assertEqual(briefing["lineage_id"], "Ltest01")
        self.assertEqual(briefing["n_outlets"], 2)
        self.assertGreater(len(briefing["corpus"]), 0)
        for entry in briefing["corpus"]:
            self.assertIn("outlet", entry)
            self.assertIn("country", entry)
            self.assertEqual(entry["country"], "usa")
            self.assertIn(entry["outlet"], {"BBC News", "Le Monde"})


class TestValidateCitations(unittest.TestCase):
    """validate.check_citations — citation grounding on outlet-keyed corpora."""

    def setUp(self):
        from core.analyze import validate
        self.v = validate

    def test_valid_citation_passes(self):
        briefing = {"corpus": [
            {"outlet": "BBC", "signal_text": "The summit ended in disagreement."}]}
        analysis = {"frames": [{"evidence": [
            {"signal_text_idx": 0, "outlet": "BBC", "quote": "summit ended"}]}]}
        self.assertEqual(self.v.check_citations(analysis, briefing), [])

    def test_out_of_range_idx_flagged(self):
        briefing = {"corpus": [{"outlet": "BBC", "signal_text": "x"}]}
        analysis = {"frames": [{"evidence": [{"signal_text_idx": 9}]}]}
        errs = self.v.check_citations(analysis, briefing)
        self.assertTrue(any("out of range" in e for e in errs))

    def test_fabricated_quote_flagged(self):
        briefing = {"corpus": [{"outlet": "BBC", "signal_text": "Real text here."}]}
        analysis = {"frames": [{"evidence": [
            {"signal_text_idx": 0, "outlet": "BBC", "quote": "fabricated line"}]}]}
        errs = self.v.check_citations(analysis, briefing)
        self.assertTrue(any("not found verbatim" in e for e in errs))

    def test_outlet_autofilled_from_corpus(self):
        briefing = {"corpus": [{"outlet": "BBC", "signal_text": "summit ended"}]}
        analysis = {"frames": [{"evidence": [
            {"signal_text_idx": 0, "quote": "summit"}]}]}  # outlet omitted
        self.v.check_citations(analysis, briefing)
        self.assertEqual(
            analysis["frames"][0]["evidence"][0]["outlet"], "BBC")


class TestSignalText(unittest.TestCase):
    """The body → summary → title fallback chain feeding every text metric."""

    def setUp(self):
        from core.ingest.extract_bodies import signal_text
        self.signal_text = signal_text

    def test_body_preferred(self):
        level, _ = self.signal_text({"title": "T", "body_text": "B" * 2000})
        self.assertEqual(level, "body")

    def test_summary_fallback(self):
        level, _ = self.signal_text(
            {"title": "T", "body_text": "", "summary": "S" * 500})
        self.assertEqual(level, "summary")

    def test_title_fallback(self):
        level, _ = self.signal_text(
            {"title": "Just a title", "body_text": "", "summary": ""})
        self.assertEqual(level, "title")

    def test_empty(self):
        level, text = self.signal_text({})
        self.assertEqual(level, "empty")
        self.assertEqual(text, "")


class TestSchemas(unittest.TestCase):
    """The v10 JSON schemas must be present and themselves valid."""

    def test_core_schemas_present_and_parse(self):
        for name in ("analysis", "briefing"):
            p = meta.SCHEMAS_DIR / f"{name}.schema.json"
            self.assertTrue(p.exists(), f"{name}.schema.json missing")
            doc = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn("$schema", doc)

    def test_schemas_are_valid_json_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        for name in ("analysis", "briefing"):
            schema = json.loads(
                (meta.SCHEMAS_DIR / f"{name}.schema.json").read_text(
                    encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)


class TestCronModulesImport(unittest.TestCase):
    """Every module the daily / weekly cron invokes must import cleanly."""

    CRON_MODULES = [
        "core.ingest.pull_feeds", "core.ingest.extract_bodies",
        "core.ingest.dedup", "core.ingest.coverage_matrix",
        "core.ingest.health", "core.ingest.rollup",
        "core.embed.encode", "core.embed.article_id",
        "core.cluster.cluster_daily", "core.cluster.salience",
        "core.cluster.lineage",
        "core.briefing.build", "core.briefing.qualifying",
        "core.briefing.coverage_warnings",
        "core.metrics.cross_bucket", "core.metrics.within_language_llr",
        "core.metrics.within_language_pmi",
        "core.analyze.validate", "core.analyze.restamp",
        "core.analyze.divergence",
        "core.compare.longitudinal", "core.compare.robustness",
        "core.compare.lag", "core.compare.wire_baseline",
        "core.compare.tilt", "core.compare.source_aggregation",
        "publish.render.analysis_md", "publish.render.sources_md",
        "publish.api.build_index",
    ]

    def test_all_cron_modules_import(self):
        import importlib
        for name in self.CRON_MODULES:
            with self.subTest(module=name):
                importlib.import_module(name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
