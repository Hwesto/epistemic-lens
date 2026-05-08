"""analytical/translate.py — translate non-English corpus text to the English pivot.

For every briefing in `briefings/<date>_<story>.json`, add `signal_text_en` and
`title_en` per corpus entry. English-language articles pass through verbatim
(no API call). Non-English articles translate via the Anthropic API with
content-hash caching at `cache/translations/<sha256[:2]>/<sha256>.json`.

Idempotent. Re-running on a briefing whose corpus entries already have
`signal_text_en` skips them unless `--force` is set. Cache hits cost nothing,
so historical replays after the cache is warm are free.

The original `signal_text` is preserved verbatim. Citation grounding in
`analytical/validate_analysis.py` continues to operate on originals — only the
metric layer (`analytical/build_metrics.py`) reads the `_en` fields. This keeps
LLM-quoted evidence honest to the source language while making cross-bucket
lexical metrics commensurable on a single pivot vocabulary.

Usage:
  python -m analytical.translate                       # all today's briefings
  python -m analytical.translate briefings/<file>.json # specific briefing(s)
  python -m analytical.translate --date 2026-05-08     # all of one date
  python -m analytical.translate --force               # retranslate even if present
  python -m analytical.translate --dry-run             # report counts only

Env:
  ANTHROPIC_API_KEY   required for live translation. Without it, the script
                       runs cache-only — passes English through, marks
                       non-English entries `skipped_no_api`, exits 0 so the
                       workflow can proceed (build_metrics falls back to
                       originals when `signal_text_en` is missing).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"
CACHE_DIR = ROOT / "cache" / "translations"

TRANSLATION = meta.META.get("translation", {})
MODEL = TRANSLATION.get("model", "claude-sonnet-4-6")
PIVOT_LANG = TRANSLATION.get("pivot", "en")
MAX_INPUT_CHARS = int(TRANSLATION.get("max_input_chars", 6000))
MAX_OUTPUT_TOKENS = int(TRANSLATION.get("max_output_tokens", 4096))
PROMPT_TEMPLATE = TRANSLATION.get(
    "prompt",
    (
        "Translate the following news article body from {lang} to English. "
        "Preserve every named entity (people, places, organizations) verbatim — "
        "do not transliterate or anglicize names. Preserve quoted speech exactly, "
        "including the original quotation marks. Do not summarize. Do not "
        "abbreviate. Do not add commentary, headers, or explanatory notes. "
        "Output only the translation, nothing else.\n\n"
        "Article:\n{text}"
    ),
)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def content_key(lang: str, text: str, model: str = MODEL) -> str:
    """Cache key. Keyed on model+lang+text so a model bump invalidates cleanly."""
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(lang.encode("utf-8"))
    h.update(b"\x00")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def cache_path_for(key: str, base: Path = CACHE_DIR) -> Path:
    return base / key[:2] / f"{key}.json"


def load_cached(lang: str, text: str, base: Path = CACHE_DIR) -> dict | None:
    p = cache_path_for(content_key(lang, text), base)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def store_cached(
    lang: str, text: str, translation: str, base: Path = CACHE_DIR, model: str = MODEL
) -> Path:
    key = content_key(lang, text, model)
    p = cache_path_for(key, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "translation": translation,
                "source_lang": lang,
                "source_chars": len(text),
                "model": model,
                "cached_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "content_sha": key,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------
def get_client():
    """Return an anthropic.Anthropic client, or None if SDK or API key missing."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    return anthropic.Anthropic()


def translate_via_api(client, lang: str, text: str) -> str:
    """One round-trip translation. Caller handles caching."""
    truncated = text[:MAX_INPUT_CHARS] if len(text) > MAX_INPUT_CHARS else text
    prompt = PROMPT_TEMPLATE.format(lang=lang, text=truncated)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    parts: list[str] = []
    for block in msg.content:
        # SDK returns objects with `.type` and `.text`; tolerate dicts in tests.
        btype = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        btext = getattr(block, "text", None) or (
            block.get("text") if isinstance(block, dict) else None
        )
        if btype == "text" and btext:
            parts.append(btext)
    return "\n".join(parts).strip()


def translate_one(
    client, lang: str, text: str, *, base: Path = CACHE_DIR
) -> tuple[str, str]:
    """Returns (translation, source_tag).

    source_tag in {'passthrough', 'cached', 'api', 'skipped_no_api', 'api_failed'}.
    """
    if not text or not text.strip():
        return "", "passthrough"
    if not lang or lang == PIVOT_LANG:
        return text, "passthrough"
    cached = load_cached(lang, text, base)
    if cached and cached.get("translation"):
        return cached["translation"], "cached"
    if client is None:
        return "", "skipped_no_api"
    try:
        translation = translate_via_api(client, lang, text)
    except Exception:
        return "", "api_failed"
    if not translation:
        return "", "api_failed"
    store_cached(lang, text, translation, base=base)
    return translation, "api"


# ---------------------------------------------------------------------------
# Briefing-level orchestration
# ---------------------------------------------------------------------------
def translate_briefing(
    briefing_path: Path,
    client=None,
    *,
    force: bool = False,
    dry_run: bool = False,
    cache_base: Path = CACHE_DIR,
) -> dict:
    """Add `signal_text_en` and `title_en` per corpus entry. Writes back in place.

    Returns a status dict with per-source-tag counts. Skips entries that already
    carry `signal_text_en` unless `force`. In `dry_run` mode no writes happen
    and no API calls are made; the function reports what it would do.
    """
    briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
    corpus = briefing.get("corpus") or []
    counts: dict[str, int] = {
        "passthrough": 0,
        "cached": 0,
        "api": 0,
        "skipped_no_api": 0,
        "api_failed": 0,
        "already_present": 0,
    }
    for art in corpus:
        if not force and "signal_text_en" in art and "title_en" in art:
            counts["already_present"] += 1
            continue
        lang = (art.get("lang") or "en").lower()
        body = art.get("signal_text") or ""
        title = art.get("title") or ""
        if dry_run:
            tag = "passthrough" if (not lang or lang == PIVOT_LANG) else (
                "cached" if load_cached(lang, body, cache_base) else
                ("skipped_no_api" if client is None else "api")
            )
            counts[tag] = counts.get(tag, 0) + 1
            continue
        body_en, body_tag = translate_one(client, lang, body, base=cache_base)
        title_en, _ = translate_one(client, lang, title, base=cache_base)
        art["signal_text_en"] = body_en
        art["title_en"] = title_en
        art["translation_source"] = body_tag
        counts[body_tag] = counts.get(body_tag, 0) + 1

    briefing["translation_status"] = {
        "model": MODEL,
        "pivot": PIVOT_LANG,
        "counts": counts,
        "translated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    meta.stamp(briefing)
    if not dry_run:
        briefing_path.write_text(
            json.dumps(briefing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return counts


def briefings_for_date(date: str, dir_: Path = BRIEFINGS) -> list[Path]:
    return sorted(
        p
        for p in dir_.glob(f"{date}_*.json")
        if not p.stem.endswith("_metrics")
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Specific briefing files. Default: all briefings for --date.",
    )
    ap.add_argument(
        "--date",
        default=None,
        help="Date in YYYY-MM-DD. Default: today UTC.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Retranslate even when signal_text_en is already present.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts only; do not write briefings or call the API.",
    )
    ap.add_argument("--out-dir", type=Path, default=BRIEFINGS)
    args = ap.parse_args()

    targets: list[Path] = (
        list(args.files)
        if args.files
        else briefings_for_date(
            args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            args.out_dir,
        )
    )
    if not targets:
        print(f"No briefings found for {args.date or 'today'}")
        return 0

    client = None if args.dry_run else get_client()
    if client is None and not args.dry_run:
        print(
            "WARN: ANTHROPIC_API_KEY missing or anthropic SDK not installed. "
            "Running cache-only — non-English articles without a cache hit will "
            "be marked 'skipped_no_api' and build_metrics will fall back to the "
            "original signal_text for those entries.",
            file=sys.stderr,
        )

    grand: dict[str, int] = {}
    for t in targets:
        counts = translate_briefing(
            t, client=client, force=args.force, dry_run=args.dry_run
        )
        for k, v in counts.items():
            grand[k] = grand.get(k, 0) + v
        summary = " ".join(f"{k}={v}" for k, v in counts.items() if v)
        print(f"  + {t.name:<48} {summary}")

    print()
    print("Total:", " ".join(f"{k}={v}" for k, v in grand.items() if v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
