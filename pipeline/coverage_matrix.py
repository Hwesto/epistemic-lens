"""coverage_matrix.py — deterministic per-(story, feed) coverage product.

For each canonical story (from `canonical_stories.json`) and each feed (from
`feeds.json`), record whether that feed carried at least one item matching
the story's patterns today, plus prominence + body-extraction quality.

Pure deterministic: no LLM, no translation, no embedding. The "headline
product" the audit identified — the simplest possible answer to "who
covered what today" with full audit trail.

Output: `coverage/<DATE>.json` with the schema:

    {
      "date": "YYYY-MM-DD",
      "meta_version": "...",
      "n_feeds_total": 235,
      "n_stories_total": 15,
      "stories": [{"key": "hormuz_iran", "tier": "long_running", ...}],
      "feeds": [{"name", "bucket", "section", "lang"}],
      "coverage": {
        "hormuz_iran": [
          {
            "feed_name", "bucket", "section",
            "n_matching", "first_match_rank",
            "first_match_body_chars", "first_match_age_hours",
            "first_match_url", "first_match_title"
          },
          ...
        ],
        ...
      },
      "summary": {
        "<story_key>": {
          "n_feeds_covered": int,
          "n_buckets_covered": int,
          "coverage_pct_news": float,    # excludes wire+opinion sections
          "median_age_hours": float
        }
      }
    }

Phase 1. Reads dedup'd snapshots so cross-day duplicates are visible to
consumers. New cron entry sits between `dedup` and `build_briefing`.

Usage:
  python -m pipeline.coverage_matrix
  python -m pipeline.coverage_matrix --date 2026-05-08
  python -m pipeline.coverage_matrix --snapshot path/to/snap.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
SNAPS = ROOT / "snapshots"
COVERAGE_DIR = ROOT / "coverage"


def _matches(item: dict, patterns, exclude=None) -> bool:
    """Same matcher used by analytical.build_briefing — kept here so coverage
    matrix and briefing builder cannot drift."""
    txt = (item.get("title", "") + " " + item.get("summary", "") +
           " " + item.get("body_text", "")[:1500]).lower()
    for ex in (exclude or []):
        if re.search(ex, txt):
            return False
    return any(re.search(p, txt, re.I) for p in patterns)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s2)
    except (TypeError, ValueError):
        return None


def _age_hours(item: dict, snapshot_dt: datetime) -> float | None:
    pub = (_parse_iso(item.get("published_iso")) or
           _parse_iso(item.get("published")) or
           _parse_iso(item.get("ingested_at")))
    if not pub:
        return None
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    delta = snapshot_dt - pub
    return round(delta.total_seconds() / 3600.0, 1)


def _classify_non_coverage(snapshot: dict, health: dict | None,
                           buckets_covered: set[str]) -> dict[str, str]:
    """For each bucket NOT in `buckets_covered`, classify as silent /
    errored / dark. Bucket states:
      - silent  : feeds returned items today, none matched this story
      - errored : every feed in the bucket appears in health.errors[]
      - dark    : bucket has no feeds with items in today's snapshot
    """
    feeds_by_bucket: dict[str, list[str]] = defaultdict(list)
    items_by_bucket: dict[str, int] = defaultdict(int)
    for bucket_key, bucket in snapshot.get("countries", {}).items():
        for f in bucket.get("feeds", []):
            feeds_by_bucket[bucket_key].append(f.get("name", "?"))
            items_by_bucket[bucket_key] += len(f.get("items", []) or [])

    errored_feeds_by_bucket: dict[str, set[str]] = defaultdict(set)
    if health:
        for e in health.get("errors", []) or []:
            b = e.get("bucket")
            n = e.get("feed")
            if b and n:
                errored_feeds_by_bucket[b].add(n)

    out: dict[str, str] = {}
    all_buckets = set(feeds_by_bucket.keys()) | set(errored_feeds_by_bucket.keys())
    for b in all_buckets:
        if b in buckets_covered:
            continue
        feeds = feeds_by_bucket.get(b, [])
        n_total = len(feeds)
        n_errored = len(errored_feeds_by_bucket.get(b, set()))
        n_items = items_by_bucket.get(b, 0)
        if n_total == 0:
            out[b] = "dark"
        elif n_items == 0 and n_errored >= n_total:
            out[b] = "errored"
        elif n_items == 0:
            out[b] = "dark"
        else:
            out[b] = "silent"
    return out


def build_coverage_matrix(snapshot: dict,
                           stories: dict | None = None,
                           health: dict | None = None) -> dict:
    """Build the full coverage matrix from a (typically dedup'd) snapshot.

    If `health` (the same date's `<DATE>_health.json`) is supplied, the
    output gains a `non_coverage` field: per-(story, bucket) classification
    of why a non-covered bucket isn't covered (silent / errored / dark).
    """
    if stories is None:
        stories = meta.canonical_stories()

    snap_date = snapshot.get("date") or datetime.now(timezone.utc).date().isoformat()
    snap_dt = _parse_iso(snapshot.get("ingest_completed_at")) \
              or _parse_iso(snapshot.get("ingest_started_at")) \
              or datetime.fromisoformat(snap_date + "T12:00:00+00:00")

    # Build feed-level metadata index
    feeds_meta: list[dict] = []
    for bucket_key, bucket in snapshot.get("countries", {}).items():
        for f in bucket.get("feeds", []):
            feeds_meta.append({
                "name": f.get("name", "?"),
                "bucket": bucket_key,
                "section": f.get("section", "news"),
                "lang": f.get("lang", "en"),
            })

    # Per-story coverage
    coverage: dict[str, list[dict]] = {}
    summary: dict[str, dict] = {}
    non_coverage: dict[str, dict[str, str]] = {}
    for story_key, story_def in stories.items():
        rows: list[dict] = []
        buckets_covered: set[str] = set()
        feeds_covered_by_section: dict[str, int] = defaultdict(int)
        ages: list[float] = []

        for bucket_key, bucket in snapshot.get("countries", {}).items():
            for f in bucket.get("feeds", []):
                items = f.get("items", []) or []
                matching = [
                    (rank, it) for rank, it in enumerate(items, start=1)
                    if _matches(it, story_def.get("patterns") or [],
                                story_def.get("exclude"))
                ]
                if not matching:
                    continue
                first_rank, first_item = matching[0]
                age = _age_hours(first_item, snap_dt)
                row = {
                    "feed_name": f.get("name", "?"),
                    "bucket": bucket_key,
                    "section": f.get("section", "news"),
                    "n_matching": len(matching),
                    "first_match_rank": first_rank,
                    "first_match_body_chars": int(first_item.get("body_chars") or 0),
                    "first_match_extraction_status": first_item.get("extraction_status"),
                    "first_match_url": (first_item.get("link") or "")[:300],
                    "first_match_title": (first_item.get("title") or "")[:200],
                }
                if age is not None:
                    row["first_match_age_hours"] = age
                    ages.append(age)
                rows.append(row)
                buckets_covered.add(bucket_key)
                feeds_covered_by_section[row["section"]] += 1

        coverage[story_key] = rows
        non_coverage[story_key] = _classify_non_coverage(
            snapshot, health, buckets_covered)

        # Summary stats per story
        n_feeds_news = sum(
            1 for f in feeds_meta if f["section"] == "news"
        ) or 1
        summary[story_key] = {
            "n_feeds_covered": len(rows),
            "n_feeds_covered_by_section": dict(feeds_covered_by_section),
            "n_buckets_covered": len(buckets_covered),
            "coverage_pct_news": round(
                100.0 * feeds_covered_by_section.get("news", 0) / n_feeds_news, 1
            ),
            "median_age_hours": (
                round(sorted(ages)[len(ages) // 2], 1) if ages else None
            ),
            "tier": story_def.get("tier"),
        }

    out = {
        "date": snap_date,
        "n_feeds_total": len(feeds_meta),
        "n_stories_total": len(stories),
        "stories": [
            {"key": k, "title": v.get("title"), "tier": v.get("tier")}
            for k, v in stories.items()
        ],
        "feeds": feeds_meta,
        "coverage": coverage,
        "summary": summary,
    }
    if health is not None:
        out["non_coverage"] = non_coverage
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD; default: latest snapshot in snapshots/.")
    ap.add_argument("--snapshot", default=None,
                    help="Path to snapshot.json; overrides --date.")
    ap.add_argument("--out-dir", default=str(COVERAGE_DIR),
                    help="Output directory (default: coverage/).")
    args = ap.parse_args()

    if args.snapshot:
        snap_path = Path(args.snapshot)
    elif args.date:
        snap_path = SNAPS / f"{args.date}.json"
        if not snap_path.exists():
            print(f"No snapshot at {snap_path}", file=sys.stderr)
            return 1
    else:
        cands = sorted(p for p in SNAPS.glob("[0-9]*.json")
                       if not p.stem.endswith(("_convergence", "_similarity",
                                               "_prompt", "_dedup", "_health",
                                               "_pull_report", "_baseline")))
        if not cands:
            print("No snapshot found.", file=sys.stderr)
            return 1
        snap_path = cands[-1]

    print(f"Coverage matrix from {snap_path}")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    health = None
    health_path = snap_path.parent / f"{snap.get('date') or snap_path.stem}_health.json"
    if health_path.exists():
        try:
            health = json.loads(health_path.read_text(encoding="utf-8"))
            print(f"  joining with {health_path.name} for non_coverage")
        except (json.JSONDecodeError, OSError) as e:
            print(f"FAIL: {health_path}: {e}", file=sys.stderr)
    matrix = build_coverage_matrix(snap, health=health)
    matrix = meta.stamp(matrix)
    try:
        meta.validate_schema(matrix, "coverage")
    except ValueError as e:
        print(f"FAIL: coverage matrix failed schema: {e}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{matrix['date']}.json"
    out_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    n_with_coverage = sum(1 for k, rows in matrix["coverage"].items() if rows)
    print(f"  {n_with_coverage}/{len(matrix['stories'])} stories had coverage today")
    for k, s in matrix["summary"].items():
        if s["n_feeds_covered"] > 0:
            print(f"    {k:35s} feeds={s['n_feeds_covered']:>3d}  "
                  f"buckets={s['n_buckets_covered']:>3d}  "
                  f"news_pct={s['coverage_pct_news']}%")
    print(f"  wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
