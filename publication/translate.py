"""Build-time translation for non-English phrases on the home page.

WORDS bigrams, HEADLINES titles, and paradox quotes from non-EN buckets get
English translations rendered underneath. Translations are cached on disk
at `archive/translations.json` so we only query the API once per phrase.

Graceful degradation: if `deep-translator` is missing or the API is
unreachable, `translate()` returns "" and the caller renders without a
translation line — no exception bubbles up.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import meta


_CACHE_PATH = meta.REPO_ROOT / "archive" / "translations.json"
_cache_lock = threading.Lock()
_cache: dict[str, str] | None = None
_translator = None  # lazily constructed
_translator_failed = False

# MyMemory wants full locale codes (it-IT, not it). Map ISO-639-1 → preferred.
_ISO_TO_LOCALE = {
    "es": "es-ES", "pt": "pt-PT", "it": "it-IT", "de": "de-DE",
    "fr": "fr-FR", "ja": "ja-JP", "ko": "ko-KR", "zh": "zh-CN",
    "ru": "ru-RU", "ar": "ar-SA", "tr": "tr-TR", "nl": "nl-NL",
    "pl": "pl-PL", "id": "id-ID", "hi": "hi-IN", "th": "th-TH",
    "vi": "vi-VN", "uk": "uk-UA", "he": "he-IL", "fa": "fa-IR",
    "el": "el-GR", "cs": "cs-CZ", "sv": "sv-SE", "fi": "fi-FI",
    "no": "nb-NO", "nb": "nb-NO", "da": "da-DK", "hu": "hu-HU",
    "ro": "ro-RO", "bg": "bg-BG", "hr": "hr-HR", "sr": "sr-Latn-RS",
    "sk": "sk-SK", "sl": "sl-SI", "et": "et-EE", "lv": "lv-LV",
    "lt": "lt-LT", "ms": "ms-MY", "fil": "fil-PH", "tl": "tl-PH",
    "bn": "bn-IN", "ta": "ta-IN", "te": "te-IN", "ur": "ur-PK",
}


def _load_cache() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    if _CACHE_PATH.exists():
        try:
            _cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _cache = {}
    else:
        _cache = {}
    return _cache


def _save_cache() -> None:
    if _cache is None:
        return
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False, sort_keys=True,
                                       indent=2), encoding="utf-8")


def _get_translator():
    """Return a translator callable `tr(text, src) -> str`, or None."""
    global _translator, _translator_failed
    if _translator is not None:
        return _translator
    if _translator_failed:
        return None
    try:
        from deep_translator import MyMemoryTranslator
    except ImportError:
        _translator_failed = True
        return None

    def _call(text: str, src: str) -> str:
        locale = _ISO_TO_LOCALE.get(src, src)
        try:
            return MyMemoryTranslator(source=locale, target="en-US").translate(text)
        except Exception:
            return ""

    _translator = _call
    return _translator


def translate(text: str, src_lang: str) -> str:
    """Return English translation of `text` from `src_lang`, or "" on failure.

    `src_lang` is an ISO-639-1 code ("it", "pt", "ja", ...). If src_lang is
    "en" or empty, returns "" (no-op). Cached on disk by (src_lang, text).
    """
    text = (text or "").strip()
    if not text or not src_lang or src_lang.lower().startswith("en"):
        return ""
    src = src_lang.lower().split("-")[0]
    key = f"{src}|{text}"
    with _cache_lock:
        cache = _load_cache()
        if key in cache:
            return cache[key]
    tr = _get_translator()
    if tr is None:
        return ""
    out = tr(text, src) or ""
    out = out.strip()
    # Reject pass-through (some APIs return original on unsupported pair)
    if out.lower() == text.lower():
        out = ""
    with _cache_lock:
        cache = _load_cache()
        cache[key] = out
        _save_cache()
    return out
