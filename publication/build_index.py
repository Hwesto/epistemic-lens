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

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"
ANALYSES = ROOT / "analyses"
DRAFTS = ROOT / "drafts"
COVERAGE = ROOT / "coverage"
TRAJECTORY = ROOT / "trajectory"
LAG = ROOT / "lag"
SOURCES = ROOT / "sources"
BASELINE = ROOT / "baseline"
TILT = ROOT / "tilt"
ROBUSTNESS = ROOT / "robustness"
SCHEMAS_SRC = ROOT / "docs" / "api" / "schema"
WEB_SRC = ROOT / "web"
API = ROOT / "api"

DATE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})_(.+?)"
    r"(?:_metrics|_thread|_carousel|_long"
    r"|_within_lang_llr|_within_lang_pmi"
    r"|_headline|_divergence)?$"
)
# Suffixes that flag a sibling artefact, not a primary story key. Used by
# discover() to skip them when enumerating stories.
SIBLING_SUFFIXES = (
    "_within_lang_llr", "_within_lang_pmi",
    "_headline", "_divergence",
    "_metrics",  # already covered by DATE_RE but listed here for clarity
)


def discover() -> dict[str, dict[str, set[str]]]:
    """Walk source dirs, return {date: {story_key: {artifact_kinds}}}."""
    found: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for p in BRIEFINGS.glob("*.json"):
        # Phase 2 sibling artefacts (within_lang_*, headline, divergence)
        # are copied per-story in build_one_date; not used as primary
        # discovery keys.
        if any(p.stem.endswith(suf) for suf in
               ("_within_lang_llr", "_within_lang_pmi",
                "_headline", "_divergence")):
            continue
        m = DATE_RE.match(p.stem)
        if not m:
            continue
        date, key = m.group(1), m.group(2)
        kind = "metrics" if p.stem.endswith("_metrics") else "briefing"
        found[date][key].add(kind)

    for p in ANALYSES.glob("*.md"):
        if any(p.stem.endswith(suf) for suf in ("_headline", "_divergence")):
            continue
        m = DATE_RE.match(p.stem)
        if not m:
            continue
        date, key = m.group(1), m.group(2)
        found[date][key].add("analysis_md")

    for p in ANALYSES.glob("*.json"):
        if any(p.stem.endswith(suf) for suf in ("_headline", "_divergence")):
            continue
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
                                 "thread", "carousel", "long",
                                 "within_lang_llr", "within_lang_pmi",
                                 "divergence", "headline", "sources")}

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

        # Phase 2 + Phase 3a sibling artefacts. Each is optional; the
        # per-story API entry advertises only what's actually present.
        for kind, src_dir, src_suffix, dst_name, has_key in [
            ("within_lang_llr",  BRIEFINGS, "_within_lang_llr",  "within_lang_llr.json",  "within_lang_llr"),
            ("within_lang_pmi",  BRIEFINGS, "_within_lang_pmi",  "within_lang_pmi.json",  "within_lang_pmi"),
            ("divergence",       ANALYSES,  "_divergence",       "divergence.json",       "divergence"),
            ("headline",         ANALYSES,  "_headline",         "headline.json",         "headline"),
            ("sources",          SOURCES,   "",                  "sources.json",          "sources"),
        ]:
            src = src_dir / f"{date}_{key}{src_suffix}.json"
            if src.exists():
                shutil.copy2(src, story_dir / dst_name)
                artifacts[kind] = f"/{date}/{key}/{dst_name}"
                has[has_key] = True

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


def copy_coverage() -> dict[str, str]:
    """Copy every `coverage/<DATE>.json` into `api/coverage/`. Phase 1.
    Returns {date: api_path} for inclusion in latest.json."""
    out: dict[str, str] = {}
    if not COVERAGE.is_dir():
        return out
    dst = API / "coverage"
    dst.mkdir(parents=True, exist_ok=True)
    for p in COVERAGE.glob("*.json"):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})$", p.stem)
        if not m:
            continue
        shutil.copy2(p, dst / p.name)
        out[m.group(1)] = f"/coverage/{p.name}"
    # Index of all available coverage dates
    if out:
        idx = meta.stamp({
            "_doc": "Index of available daily coverage matrices.",
            "n_dates": len(out),
            "dates": sorted(out.keys()),
            "paths": dict(sorted(out.items())),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        (dst / "index.json").write_text(
            json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return out


def copy_sources_aggregate() -> dict[str, str]:
    """Copy `sources/aggregate/<DATE>.json` (Phase 3a daily rollup) into
    `api/sources/aggregate/`. Returns {date: api_path}."""
    out: dict[str, str] = {}
    src_dir = SOURCES / "aggregate"
    if not src_dir.is_dir():
        return out
    dst = API / "sources" / "aggregate"
    dst.mkdir(parents=True, exist_ok=True)
    for p in src_dir.glob("*.json"):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})$", p.stem)
        if not m:
            continue
        shutil.copy2(p, dst / p.name)
        out[m.group(1)] = f"/sources/aggregate/{p.name}"
    if out:
        idx = meta.stamp({
            "_doc": "Index of daily source-attribution aggregates.",
            "n_dates": len(out),
            "dates": sorted(out.keys()),
            "paths": dict(sorted(out.items())),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        (dst / "index.json").write_text(
            json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return out


def copy_baseline() -> str | None:
    """Copy `baseline/wire_bigrams.json` (Phase 4e) into `api/baseline/`."""
    src = BASELINE / "wire_bigrams.json"
    if not src.exists():
        return None
    dst_dir = API / "baseline"
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst_dir / src.name)
    return f"/baseline/{src.name}"


def copy_tilt() -> dict[str, str]:
    """Copy `tilt/<bucket>__<outlet>.json` (Phase 4f) into `api/tilt/`."""
    out: dict[str, str] = {}
    if not TILT.is_dir():
        return out
    dst = API / "tilt"
    dst.mkdir(parents=True, exist_ok=True)
    for p in TILT.glob("*.json"):
        if p.stem == "index":
            continue
        shutil.copy2(p, dst / p.name)
        out[p.stem] = f"/tilt/{p.name}"
    if out:
        idx = meta.stamp({
            "_doc": "Index of per-outlet tilt-vs-wire-baseline files (Phase 4f).",
            "n_outlets": len(out),
            "outlet_keys": sorted(out.keys()),
            "paths": dict(sorted(out.items())),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        (dst / "index.json").write_text(
            json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return out


def copy_robustness() -> dict[str, str]:
    """Copy `robustness/<story>.json` (Phase 4h) into `api/robustness/`."""
    out: dict[str, str] = {}
    if not ROBUSTNESS.is_dir():
        return out
    dst = API / "robustness"
    dst.mkdir(parents=True, exist_ok=True)
    for p in ROBUSTNESS.glob("*.json"):
        if p.stem == "index":
            continue
        shutil.copy2(p, dst / p.name)
        out[p.stem] = f"/robustness/{p.name}"
    if out:
        idx = meta.stamp({
            "_doc": "Index of per-story stability indices (Phase 4h).",
            "n_stories": len(out),
            "story_keys": sorted(out.keys()),
            "paths": dict(sorted(out.items())),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        (dst / "index.json").write_text(
            json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return out


def copy_lag() -> dict[str, str]:
    """Copy `lag/<bucket_a>__<bucket_b>.json` (CCF outputs, Phase 2) into
    `api/lag/`. Returns {pair_key: api_path}."""
    out: dict[str, str] = {}
    if not LAG.is_dir():
        return out
    dst = API / "lag"
    dst.mkdir(parents=True, exist_ok=True)
    for p in LAG.glob("*.json"):
        if p.stem == "index":
            continue
        shutil.copy2(p, dst / p.name)
        out[p.stem] = f"/lag/{p.name}"
    if out:
        idx = meta.stamp({
            "_doc": "Index of curated outlet-pair CCF lag analyses (weekly).",
            "n_pairs": len(out),
            "pair_keys": sorted(out.keys()),
            "paths": dict(sorted(out.items())),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        (dst / "index.json").write_text(
            json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return out


def copy_trajectories() -> dict[str, str]:
    """Copy every `trajectory/<story>.json` into `api/trajectory/`. Phase 1.
    Returns {story_key: api_path} for inclusion in latest.json."""
    out: dict[str, str] = {}
    if not TRAJECTORY.is_dir():
        return out
    dst = API / "trajectory"
    dst.mkdir(parents=True, exist_ok=True)
    for p in TRAJECTORY.glob("*.json"):
        if p.stem == "index":
            continue
        shutil.copy2(p, dst / p.name)
        out[p.stem] = f"/trajectory/{p.name}"
    if out:
        idx = meta.stamp({
            "_doc": "Index of per-story longitudinal trajectories.",
            "n_stories": len(out),
            "story_keys": sorted(out.keys()),
            "paths": dict(sorted(out.items())),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        (dst / "index.json").write_text(
            json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return out


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
    coverage_paths = copy_coverage()
    trajectory_paths = copy_trajectories()
    lag_paths = copy_lag()
    sources_aggregate_paths = copy_sources_aggregate()
    baseline_path = copy_baseline()
    tilt_paths = copy_tilt()
    robustness_paths = copy_robustness()

    if latest_built:
        all_built = sorted(d for d in dates if (API / d / "index.json").exists())
        latest = all_built[-1] if all_built else latest_built
        latest_idx = json.load(open(API / latest / "index.json", encoding="utf-8"))
        latest_payload = {
            "date": latest,
            "url": f"/{latest}/index.json",
            "n_stories": latest_idx["n_stories"],
            "generated_at": latest_idx["generated_at"],
        }
        # Phase 1: surface trajectory + coverage paths so the frontend can
        # reach them from latest.json without re-walking the api/ tree.
        if trajectory_paths:
            latest_payload["trajectory_paths"] = trajectory_paths
            latest_payload["trajectory_index"] = "/trajectory/index.json"
        if latest in coverage_paths:
            latest_payload["coverage_path"] = coverage_paths[latest]
        if coverage_paths:
            latest_payload["coverage_index"] = "/coverage/index.json"
        if lag_paths:
            latest_payload["lag_index"] = "/lag/index.json"
        if latest in sources_aggregate_paths:
            latest_payload["sources_aggregate_path"] = sources_aggregate_paths[latest]
        if sources_aggregate_paths:
            latest_payload["sources_aggregate_index"] = "/sources/aggregate/index.json"
        if baseline_path:
            latest_payload["wire_baseline_path"] = baseline_path
        if tilt_paths:
            latest_payload["tilt_index"] = "/tilt/index.json"
        if robustness_paths:
            latest_payload["robustness_index"] = "/robustness/index.json"
        (API / "latest.json").write_text(
            json.dumps(meta.stamp(latest_payload), indent=2),
            encoding="utf-8",
        )

    print(f"\nBuilt {n_total} stories across {len(dates)} dates → api/")
    if coverage_paths:
        print(f"  + {len(coverage_paths)} coverage matrices → api/coverage/")
    if trajectory_paths:
        print(f"  + {len(trajectory_paths)} trajectories → api/trajectory/")
    if lag_paths:
        print(f"  + {len(lag_paths)} lag pairs → api/lag/")
    if sources_aggregate_paths:
        print(f"  + {len(sources_aggregate_paths)} source-aggregate days → api/sources/aggregate/")
    if baseline_path:
        print(f"  + wire baseline → api{baseline_path}")
    if tilt_paths:
        print(f"  + {len(tilt_paths)} tilt files → api/tilt/")
    if robustness_paths:
        print(f"  + {len(robustness_paths)} robustness files → api/robustness/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
