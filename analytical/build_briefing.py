"""build_briefing.py — assemble per-story framing-comparison briefings.

For a given snapshot, identify the top cross-bucket stories and produce
briefing JSON files containing one signal-text excerpt per bucket. Falls
back to summary-only or title-only when body extraction failed (using
extract_full_text.signal_text()).

Output: briefings/<date>_<slug>.json — feed for video script generation.

Usage:
  python build_briefing.py                    # all auto-detected top stories
  python build_briefing.py --story hormuz     # one keyword cluster
  python build_briefing.py --max-stories 3    # cap how many briefings to write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import meta
from pipeline.extract_full_text import signal_text

ROOT = meta.REPO_ROOT
SNAPS = ROOT / "snapshots"
FRESH = ROOT / "fresh_pull"
BRIEFINGS = ROOT / "briefings"
BRIEFINGS.mkdir(exist_ok=True)


# Canonical "story groups" — loaded from canonical_stories.json so the patterns
# are pinned by meta_version. The token detector below also surfaces emerging
# stories not in this list.
CANONICAL_STORIES = meta.canonical_stories()

_NOVELTY_JACCARD = float(meta.BRIEFING["novelty_jaccard"])
_SIGNAL_RANK: dict[str, int] = {k: int(v) for k, v in meta.BRIEFING["signal_rank"].items()}


def matches_story(item: dict, patterns, exclude=None) -> bool:
    txt = (item.get("title", "") + " " + item.get("summary", "") +
           " " + item.get("body_text", "")[:1500]).lower()
    for ex in (exclude or []):
        if re.search(ex, txt):
            return False
    return any(re.search(p, txt, re.I) for p in patterns)


def _title_tokens(s: str) -> set[str]:
    """Tokens for within-bucket near-duplicate detection. Uses the
    methodology-pinned stopword set so the filter is identical to what
    metrics use elsewhere. The 4-letter floor matches meta.tokenize().
    """
    stop = meta.stopwords()
    return {t for t in re.findall(r"[a-z]{4,}", s.lower()) if t not in stop}


def build_briefing_for_story(snap: dict, story_key: str, story_def: dict,
                             per_bucket_max: int = 2,
                             novelty_threshold: float = _NOVELTY_JACCARD) -> dict:
    """For one story definition, collect signal-text per bucket.

    Per bucket, keeps up to `per_bucket_max` articles that have meaningfully
    different titles (Jaccard token overlap < 1-novelty_threshold).
    Default: 2 per bucket — captures distinct framings (e.g. UK BBC's neutral
    obit + The Independent's "Trump took shot at CNN" angle on Ted Turner).
    """
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for ck, cv in snap.get("countries", {}).items():
        for f in cv.get("feeds", []):
            for it in f.get("items", []):
                if not matches_story(it, story_def["patterns"], story_def.get("exclude")):
                    continue
                level, text = signal_text(it)
                if level == "empty":
                    continue
                by_bucket[ck].append({
                    "feed": f["name"],
                    "lang": f.get("lang", "en"),
                    "title": it.get("title", "")[:240],
                    "link": it.get("link", "")[:300],
                    "signal_level": level,
                    "signal_text": text,
                    "extraction_status": it.get("extraction_status"),
                    "via_wayback": it.get("extraction_via_wayback", False),
                })

    corpus = []
    for ck in sorted(by_bucket):
        # Highest signal first, longer text wins ties. Rank pinned in
        # meta_version.json under briefing.signal_rank.
        arts = sorted(by_bucket[ck],
                      key=lambda a: (-_SIGNAL_RANK.get(a["signal_level"], 0),
                                     -len(a["signal_text"])))
        kept_for_bucket: list[dict] = []
        kept_token_sets: list[set] = []
        for a in arts:
            if len(kept_for_bucket) >= per_bucket_max:
                break
            tokens = _title_tokens(a["title"])
            # Skip if too similar to an already-kept title in this bucket
            too_similar = False
            for prev in kept_token_sets:
                if not tokens or not prev:
                    continue
                jaccard = len(tokens & prev) / max(1, len(tokens | prev))
                if jaccard >= (1 - novelty_threshold):
                    too_similar = True
                    break
            if too_similar:
                continue
            kept_for_bucket.append(a)
            kept_token_sets.append(tokens)
        for a in kept_for_bucket:
            corpus.append({"bucket": ck, **a})

    return meta.stamp({
        "date": snap.get("date"),
        "story_key": story_key,
        "story_title": story_def["title"],
        "n_buckets": len(by_bucket),
        "n_articles_total": sum(len(v) for v in by_bucket.values()),
        "signal_breakdown": dict(Counter(a["signal_level"] for a in corpus)),
        "corpus": corpus,
    })


def find_emerging_stories(snap: dict, min_buckets: int = 5,
                          ignore_canonical: bool = True) -> list[tuple[str, set]]:
    """Token-frequency detection of unrecognised cross-bucket stories.

    Filter set is the pinned stopwords plus a small inline allowlist of
    "already-tracked" terms (the heads of canonical stories) so we don't
    surface tokens we already cover via canonical_stories.json. The
    inline set is intentionally narrow — broader noise belongs in
    stopwords.txt.
    """
    # Canonical-story-head terms that survive the title filter would
    # otherwise dominate emerging-story output. Comment line spelling
    # matches the canonical_stories.json keys for grep-ability.
    DOMAIN_NOISE = {"trump", "iran", "said"}
    stop = meta.stopwords() | DOMAIN_NOISE

    canon_pat = re.compile(
        "|".join(p for s in CANONICAL_STORIES.values() for p in s["patterns"]),
        re.I,
    ) if ignore_canonical else None

    token_buckets = defaultdict(set)
    for ck, cv in snap.get("countries", {}).items():
        for f in cv.get("feeds", []):
            for it in f.get("items", []):
                title = it.get("title", "")
                if canon_pat and canon_pat.search(title):
                    continue
                seen = set()
                for tok in re.findall(r"[A-Za-z]{5,}", title.lower()):
                    if tok not in stop:
                        seen.add(tok)
                for tok in seen:
                    token_buckets[tok].add(ck)
    emerging = [(t, b) for t, b in token_buckets.items() if len(b) >= min_buckets]
    emerging.sort(key=lambda x: -len(x[1]))
    return emerging[:10]


def latest_snapshot_path(snap_dir: Path | None = None) -> Path | None:
    snap_dir = snap_dir or SNAPS
    cands = sorted(p for p in snap_dir.glob("[0-9]*.json")
                   if not p.stem.endswith(("_convergence", "_similarity",
                                           "_prompt", "_dedup", "_health")))
    return cands[-1] if cands else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, default=None,
                    help="Path to snapshot file. Default: latest in snapshots/ or fresh_pull/")
    ap.add_argument("--story", default="",
                    help="Build only this canonical story key (e.g. 'hormuz_iran')")
    ap.add_argument("--max-stories", type=int, default=5,
                    help="Cap on how many briefings to write per run")
    ap.add_argument("--min-buckets", type=int, default=4,
                    help="Skip stories with fewer than N buckets covering them")
    ap.add_argument("--out-dir", type=Path, default=BRIEFINGS)
    args = ap.parse_args()

    snap_path = args.snapshot
    if snap_path is None:
        # Prefer fresh_pull if present (smoke-test artifact)
        snap_path = latest_snapshot_path(FRESH) or latest_snapshot_path(SNAPS)
    if snap_path is None or not snap_path.exists():
        sys.exit("No snapshot found")
    print(f"Building briefings from {snap_path}", flush=True)
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    args.out_dir.mkdir(exist_ok=True)

    n_written = 0
    keys = [args.story] if args.story else list(CANONICAL_STORIES)
    for key in keys:
        if key not in CANONICAL_STORIES:
            print(f"  skip: unknown story key '{key}'")
            continue
        story_def = CANONICAL_STORIES[key]
        b = build_briefing_for_story(snap, key, story_def)
        if b["n_buckets"] < args.min_buckets:
            print(f"  - {key:<24} {b['n_buckets']} buckets — under threshold, skipped")
            continue
        out_path = args.out_dir / f"{snap['date']}_{key}.json"
        out_path.write_text(json.dumps(b, indent=2, ensure_ascii=False))
        sb = b["signal_breakdown"]
        print(f"  + {key:<24} {b['n_buckets']:>2} buckets  "
              f"signal: {sb.get('body',0)} body / {sb.get('summary',0)} summ / "
              f"{sb.get('title',0)} title  -> {out_path.name}")
        n_written += 1
        if n_written >= args.max_stories:
            break

    print(f"\n{n_written} briefings written to {args.out_dir}/")

    # Emerging-stories report (just informational)
    emerging = find_emerging_stories(snap, min_buckets=4)
    if emerging:
        print("\nEmerging stories not in canonical list (>=4 buckets):")
        for tok, buckets in emerging[:8]:
            print(f"  {tok:<18} {len(buckets):>2} buckets")


if __name__ == "__main__":
    main()
