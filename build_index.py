#!/usr/bin/env python3
"""build_index.py — assemble the public API tree under api/.

Walks briefings/, analyses/, drafts/ for each known date and copies them
into a flat, predictable api/<date>/<story_key>/ layout that the frontend
consumes via GitHub Pages.

Outputs:

  api/latest.json
    { "date": "<YYYY-MM-DD>", "url": "/<DATE>/index.json", "n_stories": N }

  api/<DATE>/index.json
    { "date": "<DATE>", "stories": [ {key, title, n_buckets, n_articles,
      has{briefing,metrics,analysis,thread,carousel,long},
      artifacts{briefing, metrics, analysis, thread?, carousel?, long?},
      top_isolation_bucket?, paradox?} ] }

  api/<DATE>/<story_key>/{briefing.json, metrics.json, analysis.md,
                          thread.json, carousel.json, long.json}

  api/schema/{thread,carousel,long}.schema.json   (copied from docs/api/schema)

Idempotent: re-running on the same date overwrites. Source files in
briefings/, analyses/, drafts/ remain canonical; the api/ tree is a
publication bundle.

Usage:
  python build_index.py                  # all dates with any artifact
  python build_index.py --date YYYY-MM-DD  # one date only
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = Path(__file__).parent
BRIEFINGS = ROOT / "briefings"
ANALYSES = ROOT / "analyses"
DRAFTS = ROOT / "drafts"
SCHEMAS_SRC = ROOT / "docs" / "api" / "schema"
WEB_SRC = ROOT / "web"
API = ROOT / "api"

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+?)(?:_metrics|_thread|_carousel|_long)?$")


def discover() -> dict[str, dict[str, set[str]]]:
    """Walk source dirs, return {date: {story_key: {artifact_kinds}}}."""
    found: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for p in BRIEFINGS.glob("*.json"):
        m = DATE_RE.match(p.stem)
        if not m:
            continue
        date, key = m.group(1), m.group(2)
        kind = "metrics" if p.stem.endswith("_metrics") else "briefing"
        found[date][key].add(kind)

    for p in ANALYSES.glob("*.md"):
        m = DATE_RE.match(p.stem)
        if not m:
            continue
        date, key = m.group(1), m.group(2)
        found[date][key].add("analysis_md")

    for p in ANALYSES.glob("*.json"):
        m = DATE_RE.match(p.stem)
        if not m:
            continue
        date, key = m.group(1), m.group(2)
        found[date][key].add("analysis_json")

    if DRAFTS.exists():
        for p in DRAFTS.glob("*.json"):
            m = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)_(thread|carousel|long)$", p.stem)
            if not m:
                continue
            date, key, kind = m.group(1), m.group(2), m.group(3)
            found[date][key].add(kind)

    return found


def detect_paradox(analysis_md: str) -> bool:
    """Heuristic: the analysis declares a paradox section non-empty."""
    text = analysis_md.lower()
    if "no paradox in this corpus" in text:
        return False
    if "(none in this corpus)" in text and "paradox" in text:
        return False
    return "paradox" in text


def extract_title(briefing: dict, fallback_key: str) -> str:
    return briefing.get("story_title") or briefing.get("title") or fallback_key.replace("_", " ").title()


def build_one_date(date: str, stories: dict[str, set[str]]) -> dict | None:
    out_dir = API / date
    out_dir.mkdir(parents=True, exist_ok=True)
    story_entries = []

    for key in sorted(stories):
        kinds = stories[key]
        if "briefing" not in kinds:
            continue  # no briefing = skip; metrics/drafts/analysis without briefing is malformed

        briefing_src = BRIEFINGS / f"{date}_{key}.json"
        try:
            briefing = json.load(open(briefing_src, encoding="utf-8"))
        except Exception as e:
            print(f"  skip {key}: briefing unreadable ({e})", file=sys.stderr)
            continue

        n_buckets = briefing.get("n_buckets")
        n_articles = briefing.get("n_articles")
        if n_buckets is None and "corpus" in briefing:
            n_buckets = len({e.get("bucket") for e in briefing["corpus"]})
            n_articles = len(briefing["corpus"])

        story_dir = out_dir / key
        story_dir.mkdir(exist_ok=True)
        artifacts: dict[str, str] = {}
        has: dict[str, bool] = {k: False for k in
                                ("briefing", "metrics", "analysis", "analysis_json",
                                 "thread", "carousel", "long")}

        shutil.copy2(briefing_src, story_dir / "briefing.json")
        artifacts["briefing"] = f"/{date}/{key}/briefing.json"
        has["briefing"] = True

        metrics_src = BRIEFINGS / f"{date}_{key}_metrics.json"
        top_isolation = None
        if metrics_src.exists():
            shutil.copy2(metrics_src, story_dir / "metrics.json")
            artifacts["metrics"] = f"/{date}/{key}/metrics.json"
            has["metrics"] = True
            try:
                m = json.load(open(metrics_src, encoding="utf-8"))
                if m.get("isolation"):
                    top_isolation = m["isolation"][0]["bucket"]
            except Exception:
                pass

        paradox = None
        analysis_md_src = ANALYSES / f"{date}_{key}.md"
        if analysis_md_src.exists():
            shutil.copy2(analysis_md_src, story_dir / "analysis.md")
            artifacts["analysis"] = f"/{date}/{key}/analysis.md"
            has["analysis"] = True
            try:
                paradox = detect_paradox(analysis_md_src.read_text(encoding="utf-8"))
            except Exception:
                pass

        analysis_json_src = ANALYSES / f"{date}_{key}.json"
        if analysis_json_src.exists():
            shutil.copy2(analysis_json_src, story_dir / "analysis.json")
            artifacts["analysis_json"] = f"/{date}/{key}/analysis.json"
            has["analysis_json"] = True
            # JSON is the canonical source — read paradox flag directly if MD
            # wasn't present or didn't yield one.
            if paradox is None:
                try:
                    aj = json.load(open(analysis_json_src, encoding="utf-8"))
                    paradox = aj.get("paradox") is not None
                except Exception:
                    pass

        for fmt in ("thread", "carousel", "long"):
            src = DRAFTS / f"{date}_{key}_{fmt}.json"
            if src.exists():
                shutil.copy2(src, story_dir / f"{fmt}.json")
                artifacts[fmt] = f"/{date}/{key}/{fmt}.json"
                has[fmt] = True

        entry = {
            "key": key,
            "title": extract_title(briefing, key),
            "n_buckets": n_buckets,
            "n_articles": n_articles,
            "has": has,
            "artifacts": artifacts,
        }
        if top_isolation:
            entry["top_isolation_bucket"] = top_isolation
        if paradox is not None:
            entry["paradox"] = paradox
        story_entries.append(entry)

    if not story_entries:
        return None

    index = meta.stamp({
        "date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_stories": len(story_entries),
        "stories": story_entries,
    })
    (out_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return index


def copy_schemas() -> None:
    if not SCHEMAS_SRC.is_dir():
        return
    dst = API / "schema"
    dst.mkdir(parents=True, exist_ok=True)
    for p in SCHEMAS_SRC.glob("*.json"):
        shutil.copy2(p, dst / p.name)


def copy_web() -> None:
    """Copy web/ assets (index.html, styles.css, app.js) into api/.

    Pages serves api/ at the site root, so dropping web/* directly into
    api/ exposes them as the landing page. Idempotent.
    """
    if not WEB_SRC.is_dir():
        return
    API.mkdir(parents=True, exist_ok=True)
    for p in WEB_SRC.iterdir():
        if p.is_file():
            shutil.copy2(p, API / p.name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Build only this date (YYYY-MM-DD)")
    args = ap.parse_args()

    found = discover()
    # Ensure api/ always exists so actions/upload-pages-artifact never fails
    # on a "path doesn't exist" error, even on an empty pipeline day.
    API.mkdir(parents=True, exist_ok=True)
    if not found:
        # Empty-day fallback: keep api/latest.json present (pointing at nothing)
        # so downstream consumers don't 404 mid-day.
        (API / "latest.json").write_text(
            json.dumps(meta.stamp({
                "date": None,
                "n_stories": 0,
                "note": "no source artifacts found for this build",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }), indent=2),
            encoding="utf-8",
        )
        print("No source artifacts found.", file=sys.stderr)
        return 0

    dates = [args.date] if args.date else sorted(found)
    latest_built: str | None = None
    n_total = 0

    for date in dates:
        if date not in found:
            print(f"  no artifacts for {date}", file=sys.stderr)
            continue
        result = build_one_date(date, found[date])
        if result:
            latest_built = date
            n_total += result["n_stories"]
            print(f"  {date}: {result['n_stories']} stories")

    copy_schemas()
    copy_web()

    if latest_built:
        all_built = sorted(d for d in dates if (API / d / "index.json").exists())
        latest = all_built[-1] if all_built else latest_built
        latest_idx = json.load(open(API / latest / "index.json", encoding="utf-8"))
        (API / "latest.json").write_text(
            json.dumps(
                meta.stamp({
                    "date": latest,
                    "url": f"/{latest}/index.json",
                    "n_stories": latest_idx["n_stories"],
                    "generated_at": latest_idx["generated_at"],
                }),
                indent=2,
            ),
            encoding="utf-8",
        )

    print(f"\nBuilt {n_total} stories across {len(dates)} dates → api/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
