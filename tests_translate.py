"""Unit tests for analytical.translate.

Mocks the Anthropic SDK client; never calls the API. Covers:
  - English passthrough (no API call, signal_text_en == signal_text)
  - Non-English translation via mocked API
  - Content-hash cache hit on repeat calls
  - Idempotency (already_present skip; --force overrides)
  - Empty / missing text handled
  - No API key + cache miss → marked skipped_no_api, exit ok
  - Cache key is stable across runs and changes when model/lang/text changes

Run: python3 -m unittest tests_translate.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from analytical import translate as T  # noqa: E402


def _mock_client(translation_text: str = "[EN] translated body"):
    """Return a MagicMock shaped like anthropic.Anthropic()."""
    block = MagicMock()
    block.type = "text"
    block.text = translation_text
    msg = MagicMock()
    msg.content = [block]
    client = MagicMock()
    client.messages.create.return_value = msg
    return client


def _briefing(corpus_entries: list[dict]) -> dict:
    return {
        "date": "2026-05-08",
        "story_key": "test_story",
        "story_title": "Test",
        "n_buckets": len({c.get("bucket") for c in corpus_entries}),
        "n_articles_total": len(corpus_entries),
        "corpus": corpus_entries,
    }


class TestCacheKey(unittest.TestCase):
    def test_same_input_same_key(self):
        a = T.content_key("it", "ciao mondo")
        b = T.content_key("it", "ciao mondo")
        self.assertEqual(a, b)

    def test_different_lang_different_key(self):
        a = T.content_key("it", "amico")
        b = T.content_key("es", "amico")
        self.assertNotEqual(a, b)

    def test_different_text_different_key(self):
        a = T.content_key("it", "guerra")
        b = T.content_key("it", "pace")
        self.assertNotEqual(a, b)

    def test_different_model_different_key(self):
        a = T.content_key("it", "guerra", model="claude-sonnet-4-6")
        b = T.content_key("it", "guerra", model="claude-sonnet-4-7")
        self.assertNotEqual(a, b)


class TestPassthrough(unittest.TestCase):
    def test_english_passthrough_no_api_call(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            client = _mock_client()
            translation, tag = T.translate_one(
                client, "en", "Original English text.", base=base
            )
            self.assertEqual(tag, "passthrough")
            self.assertEqual(translation, "Original English text.")
            client.messages.create.assert_not_called()

    def test_empty_passthrough(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            client = _mock_client()
            translation, tag = T.translate_one(client, "it", "", base=base)
            self.assertEqual(tag, "passthrough")
            self.assertEqual(translation, "")
            client.messages.create.assert_not_called()

    def test_whitespace_only_passthrough(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            client = _mock_client()
            translation, tag = T.translate_one(client, "ru", "   \n\t  ", base=base)
            self.assertEqual(tag, "passthrough")


class TestApiAndCache(unittest.TestCase):
    def test_api_call_then_cache_hit(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            client = _mock_client("English translation")
            t1, tag1 = T.translate_one(client, "it", "guerra in oriente", base=base)
            self.assertEqual(tag1, "api")
            self.assertEqual(t1, "English translation")
            self.assertEqual(client.messages.create.call_count, 1)

            t2, tag2 = T.translate_one(client, "it", "guerra in oriente", base=base)
            self.assertEqual(tag2, "cached")
            self.assertEqual(t2, "English translation")
            self.assertEqual(
                client.messages.create.call_count,
                1,
                "second call must hit cache, not API",
            )

    def test_cache_miss_no_client_marks_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            translation, tag = T.translate_one(
                None, "ru", "русский текст", base=base
            )
            self.assertEqual(tag, "skipped_no_api")
            self.assertEqual(translation, "")

    def test_api_failure_marks_failed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            client = MagicMock()
            client.messages.create.side_effect = RuntimeError("network down")
            translation, tag = T.translate_one(
                client, "ja", "テスト", base=base
            )
            self.assertEqual(tag, "api_failed")
            self.assertEqual(translation, "")


class TestBriefingOrchestration(unittest.TestCase):
    def _write_briefing(self, td: Path, corpus: list[dict]) -> Path:
        p = td / "2026-05-08_test.json"
        p.write_text(json.dumps(_briefing(corpus)), encoding="utf-8")
        return p

    def test_mixed_corpus_english_and_italian(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cache_base = td_path / "cache"
            briefing_path = self._write_briefing(
                td_path,
                [
                    {
                        "bucket": "usa",
                        "lang": "en",
                        "title": "Hormuz closure",
                        "signal_text": "Crude prices spiked on Tuesday.",
                    },
                    {
                        "bucket": "italy",
                        "lang": "it",
                        "title": "Hormuz chiuso",
                        "signal_text": "I prezzi del greggio sono saliti martedi.",
                    },
                ],
            )
            client = _mock_client("Crude prices rose on Tuesday.")
            counts = T.translate_briefing(
                briefing_path, client=client, cache_base=cache_base
            )
            self.assertEqual(counts.get("passthrough", 0), 1)
            self.assertEqual(counts.get("api", 0), 1)

            after = json.loads(briefing_path.read_text(encoding="utf-8"))
            usa, italy = after["corpus"]
            self.assertEqual(usa["signal_text_en"], usa["signal_text"])
            self.assertEqual(usa["title_en"], usa["title"])
            self.assertEqual(italy["signal_text_en"], "Crude prices rose on Tuesday.")
            self.assertEqual(italy["translation_source"], "api")
            self.assertIn("translation_status", after)
            self.assertEqual(after["translation_status"]["pivot"], "en")

    def test_idempotent_skips_already_translated(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cache_base = td_path / "cache"
            briefing_path = self._write_briefing(
                td_path,
                [
                    {
                        "bucket": "italy",
                        "lang": "it",
                        "title": "ciao",
                        "signal_text": "ciao mondo",
                        "title_en": "hello",
                        "signal_text_en": "hello world",
                    }
                ],
            )
            client = _mock_client("SHOULD_NOT_BE_USED")
            counts = T.translate_briefing(
                briefing_path, client=client, cache_base=cache_base
            )
            self.assertEqual(counts.get("already_present"), 1)
            client.messages.create.assert_not_called()

            after = json.loads(briefing_path.read_text(encoding="utf-8"))
            self.assertEqual(after["corpus"][0]["signal_text_en"], "hello world")

    def test_force_retranslates(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cache_base = td_path / "cache"
            briefing_path = self._write_briefing(
                td_path,
                [
                    {
                        "bucket": "italy",
                        "lang": "it",
                        "title": "ciao",
                        "signal_text": "ciao mondo",
                        "title_en": "old translation",
                        "signal_text_en": "old translation",
                    }
                ],
            )
            client = _mock_client("fresh translation")
            counts = T.translate_briefing(
                briefing_path,
                client=client,
                force=True,
                cache_base=cache_base,
            )
            self.assertEqual(counts.get("api", 0), 1)
            after = json.loads(briefing_path.read_text(encoding="utf-8"))
            self.assertEqual(
                after["corpus"][0]["signal_text_en"], "fresh translation"
            )

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cache_base = td_path / "cache"
            briefing_path = self._write_briefing(
                td_path,
                [
                    {
                        "bucket": "italy",
                        "lang": "it",
                        "title": "ciao",
                        "signal_text": "ciao mondo",
                    }
                ],
            )
            before = briefing_path.read_text(encoding="utf-8")
            counts = T.translate_briefing(
                briefing_path,
                client=None,
                dry_run=True,
                cache_base=cache_base,
            )
            after = briefing_path.read_text(encoding="utf-8")
            self.assertEqual(before, after, "dry-run must not write")
            self.assertGreaterEqual(sum(counts.values()), 1)

    def test_no_client_logs_skipped_for_non_english(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cache_base = td_path / "cache"
            briefing_path = self._write_briefing(
                td_path,
                [
                    {
                        "bucket": "russia",
                        "lang": "ru",
                        "title": "Title",
                        "signal_text": "Russian body text",
                    }
                ],
            )
            counts = T.translate_briefing(
                briefing_path, client=None, cache_base=cache_base
            )
            self.assertEqual(counts.get("skipped_no_api"), 1)
            after = json.loads(briefing_path.read_text(encoding="utf-8"))
            self.assertEqual(after["corpus"][0]["signal_text_en"], "")
            self.assertEqual(after["corpus"][0]["translation_source"], "skipped_no_api")


if __name__ == "__main__":
    unittest.main()
