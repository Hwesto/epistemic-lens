"""source_attribution.py — helper for the source-attribution Claude pass.

The actual quote extraction runs as a Claude Code Action step in the cron
(see `.claude/prompts/source_attribution.md`); this module is the helper
side: schema validation of the agent's output, quote-grounding check
against `briefings/<DATE>_<story>.json`, listing of pending articles
(those whose `signal_text` SHA isn't yet in the cache), and dry-run
preview.

Output (written by the agent, validated by this module):
  sources/<DATE>_<story_key>.json
    {
      "story_key", "date", "story_title", "n_articles_processed",
      "sources": [{
        "speaker_name", "role_or_affiliation", "speaker_type",
        "exact_quote", "attributive_verb", "stance_toward_target",
        "signal_text_idx", "bucket", "outlet"
      }]
    }

Cache (write-through; agent maintains via the prompt's commit step):
  sources/cache/<sha>.json
    {"sha": "...", "n_quotes": 0, "first_extracted_at": "...", "story_key": "..."}

Usage:
  python -m analytical.source_attribution --validate sources/<file>.json
  python -m analytical.source_attribution --list-pending --date 2026-05-08
  python -m analytical.source_attribution --validate-all --date 2026-05-08
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"
SOURCES = ROOT / "sources"
CACHE = SOURCES / "cache"

VALID_SPEAKER_TYPES = {
    "official", "civilian", "expert", "journalist", "spokesperson", "unknown"
}
VALID_STANCES = {"for", "against", "neutral", "unclear"}


def article_sha(article: dict) -> str:
    """SHA-256 of the article's signal_text. Used as cache key."""
    text = (article.get("signal_text") or "").encode("utf-8")
    return hashlib.sha256(text).hexdigest()[:32]


def cache_path(sha: str, cache_dir: Path = CACHE) -> Path:
    return cache_dir / f"{sha}.json"


def is_cached(sha: str, cache_dir: Path = CACHE) -> bool:
    return cache_path(sha, cache_dir).exists()


def update_cache(sha: str, story_key: str, n_quotes: int,
                 cache_dir: Path = CACHE) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "sha": sha,
        "story_key": story_key,
        "n_quotes": n_quotes,
        "first_extracted_at": datetime.now(timezone.utc).isoformat(),
        "meta_version_at_extract": meta.VERSION,
    }
    cache_path(sha, cache_dir).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def list_pending(briefing: dict, cache_dir: Path = CACHE) -> list[dict]:
    """Articles in the briefing whose signal_text SHA isn't yet cached."""
    pending = []
    for i, art in enumerate(briefing.get("corpus") or []):
        sha = article_sha(art)
        if not is_cached(sha, cache_dir):
            pending.append({
                "signal_text_idx": i,
                "bucket": art.get("bucket"),
                "outlet": art.get("feed"),
                "lang": art.get("lang"),
                "title": (art.get("title") or "")[:100],
                "sha": sha,
            })
    return pending


def validate_sources(sources_doc: dict, briefing: dict) -> list[str]:
    """Return list of human-readable validation errors. Empty = clean.

    Checks:
      1. Each source entry has all required fields.
      2. speaker_type / stance enums match.
      3. signal_text_idx resolves to an article in the briefing.
      4. exact_quote is verbatim in corpus[idx].signal_text.
      5. bucket field matches corpus[idx].bucket.
    """
    errors: list[str] = []
    sources = sources_doc.get("sources") or []
    corpus = briefing.get("corpus") or []
    n_articles = len(corpus)

    required_fields = {
        "speaker_name", "role_or_affiliation", "speaker_type",
        "exact_quote", "attributive_verb", "stance_toward_target",
        "signal_text_idx", "bucket", "outlet",
    }
    for ii, s in enumerate(sources):
        missing = required_fields - set(s.keys())
        if missing:
            errors.append(f"sources[{ii}]: missing fields {sorted(missing)}")
            continue
        if s["speaker_type"] not in VALID_SPEAKER_TYPES:
            errors.append(
                f"sources[{ii}]: speaker_type {s['speaker_type']!r} "
                f"not in {sorted(VALID_SPEAKER_TYPES)}"
            )
        if s["stance_toward_target"] not in VALID_STANCES:
            errors.append(
                f"sources[{ii}]: stance_toward_target "
                f"{s['stance_toward_target']!r} not in {sorted(VALID_STANCES)}"
            )
        idx = s.get("signal_text_idx")
        if not isinstance(idx, int) or idx < 0 or idx >= n_articles:
            errors.append(f"sources[{ii}]: signal_text_idx {idx} out of range")
            continue
        article = corpus[idx]
        # Quote grounding
        quote = (s.get("exact_quote") or "").strip()
        text = article.get("signal_text") or ""
        if quote and quote not in text:
            errors.append(
                f"sources[{ii}]: quote not found verbatim in "
                f"corpus[{idx}].signal_text — {quote[:60]!r}"
            )
        # Bucket cross-check
        if s.get("bucket") != article.get("bucket"):
            errors.append(
                f"sources[{ii}]: bucket {s['bucket']!r} != "
                f"corpus[{idx}].bucket {article.get('bucket')!r}"
            )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--validate", default=None,
                   help="Validate one sources/<file>.json against its briefing.")
    g.add_argument("--validate-all", action="store_true",
                   help="Validate every sources/<DATE>_*.json for --date.")
    g.add_argument("--list-pending", action="store_true",
                   help="Per-briefing, list articles needing extraction.")
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD; default: today UTC.")
    args = ap.parse_args()

    date = args.date or datetime.now(timezone.utc).date().isoformat()

    if args.validate:
        sources_path = Path(args.validate)
        sources_doc = json.loads(sources_path.read_text(encoding="utf-8"))
        story_key = sources_doc.get("story_key")
        d = sources_doc.get("date") or date
        briefing_path = BRIEFINGS / f"{d}_{story_key}.json"
        if not briefing_path.exists():
            print(f"error: briefing missing at {briefing_path}", file=sys.stderr)
            return 1
        briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
        errors = validate_sources(sources_doc, briefing)
        if errors:
            for e in errors:
                print(f"  ✗ {e}")
            return 1
        n = len(sources_doc.get("sources") or [])
        print(f"  ✓ {sources_path.name}: {n} sources, all grounded")
        return 0

    if args.validate_all:
        targets = sorted(SOURCES.glob(f"{date}_*.json"))
        if not targets:
            print(f"No sources files for {date}.")
            return 0
        any_failed = 0
        for sp in targets:
            sd = json.loads(sp.read_text(encoding="utf-8"))
            story_key = sd.get("story_key")
            briefing_path = BRIEFINGS / f"{date}_{story_key}.json"
            if not briefing_path.exists():
                print(f"  ✗ {sp.name}: briefing missing")
                any_failed = 1
                continue
            briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
            errors = validate_sources(sd, briefing)
            if errors:
                print(f"  ✗ {sp.name}: {len(errors)} errors")
                for e in errors[:3]:
                    print(f"      - {e}")
                any_failed = 1
            else:
                print(f"  ✓ {sp.name}: {len(sd.get('sources') or [])} sources, all grounded")
        return 1 if any_failed else 0

    if args.list_pending:
        targets = sorted(p for p in BRIEFINGS.glob(f"{date}_*.json")
                         if not p.stem.endswith(("_metrics", "_within_lang_llr",
                                                 "_within_lang_pmi", "_headline")))
        if not targets:
            print(f"No briefings for {date}.")
            return 0
        for bp in targets:
            briefing = json.loads(bp.read_text(encoding="utf-8"))
            pending = list_pending(briefing)
            n_total = len(briefing.get("corpus") or [])
            print(f"  {bp.stem:50s} {len(pending)}/{n_total} pending extraction")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
