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


# ---------------------------------------------------------------------------
# Card-archetype picker (PR A+ / meta-v8.7.0)
#
# pick_per_story_card_kind(signals) → archetype assigned per story
# compute_finding_synthesis(signals, kind) → headline-finding sentence the renderer uses verbatim
# pick_todays_card(stories, recent_history) → daily hero card
# ---------------------------------------------------------------------------

from functools import lru_cache


@lru_cache(maxsize=1)
def _card_picker_cfg() -> dict:
    return json.loads(meta.CARD_PICKER_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _today_picker_cfg() -> dict:
    return json.loads(meta.TODAY_PICKER_PATH.read_text(encoding="utf-8"))


def _safe_load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect_story_signals(date: str, key: str, briefing: dict) -> dict:
    """Load every on-disk artifact the cascade evaluates.

    Returns a dict the picker / synthesis helpers consume. Each section
    is None when its underlying file is absent — pickers must handle
    missing sections without raising. This is the gracefully-degrades
    surface for day-1 stories (no trajectory, no tilt, etc.).
    """
    out: dict = {"date": date, "story_key": key, "briefing": briefing}
    out["analysis"] = _safe_load(ANALYSES / f"{date}_{key}.json")
    out["trajectory"] = _safe_load(TRAJECTORY / f"{key}.json")
    out["coverage"] = _safe_load(COVERAGE / f"{date}.json")
    out["sources"] = _safe_load(SOURCES / f"{date}_{key}.json")
    out["within_lang_llr"] = _safe_load(BRIEFINGS / f"{date}_{key}_within_lang_llr.json")

    # Tilt is per-(bucket, outlet). Collect all tilt files for buckets
    # present in this story's briefing corpus.
    story_buckets = {e.get("bucket") for e in (briefing.get("corpus") or [])
                      if e.get("bucket")}
    tilt_files: list[dict] = []
    if TILT.is_dir():
        for bucket in story_buckets:
            for p in TILT.glob(f"{bucket}__*.json"):
                t = _safe_load(p)
                if t:
                    tilt_files.append(t)
    out["tilt_files"] = tilt_files
    return out


def _precondition_matches(precond: dict, signals: dict) -> bool:
    """Evaluate a card_picker.json precondition against a signals dict."""
    t = precond.get("type")
    if t == "fallback":
        return True

    if t == "field_present":
        # E.g. "analysis.paradox" must be non-null + .joint_conclusion min length
        path = precond.get("path", "")
        val = _walk_path(signals, path)
        if val in (None, "", {}, []):
            return False
        sub = precond.get("and")
        if sub:
            return _precondition_matches(sub, signals)
        return True

    if t == "min_length":
        val = _walk_path(signals, precond.get("path", ""))
        return isinstance(val, str) and len(val) >= int(precond.get("min", 0))

    if t == "max_abs_delta_share":
        traj = signals.get("trajectory") or {}
        frame_trajectories = traj.get("frame_trajectories") or {}
        lookback = int(precond.get("lookback_days", 7))
        threshold = float(precond.get("min", 0.20))
        # Walk recent entries per frame; check |delta_share|.
        best = 0.0
        for entries in frame_trajectories.values():
            recent = (entries or [])[-lookback:]
            for e in recent:
                d = e.get("delta_share")
                if d is None:
                    continue
                if abs(d) > best:
                    best = abs(d)
        return best >= threshold

    if t == "count_in_state":
        coverage = signals.get("coverage") or {}
        non_cov = coverage.get("non_coverage") or {}
        target_state = precond.get("state")
        # non_coverage shape: {story_key: {bucket: {state: ..., coverage_pct_news: ...}}}
        story = signals.get("story_key")
        per_bucket = (non_cov.get(story) or {})
        count = 0
        for bucket_info in per_bucket.values():
            if not isinstance(bucket_info, dict):
                continue
            if bucket_info.get("state") != target_state:
                continue
            extra = precond.get("additional_bucket_filter")
            if extra and extra.get("field") == "coverage_pct_news_lt":
                pct = bucket_info.get("coverage_pct_news")
                if pct is None or pct >= extra.get("value", 100):
                    continue
            count += 1
        return count >= int(precond.get("min_count", 0))

    if t == "max_z_score":
        threshold = float(precond.get("min", 0.0))
        for tilt in signals.get("tilt_files") or []:
            wire = ((tilt.get("anchors") or {}).get("wire") or {})
            pos = wire.get("positive_tilt") or []
            if pos and float(pos[0].get("z_score", 0)) >= threshold:
                return True
        return False

    if t == "sources_diversity":
        sd = (signals.get("sources") or {}).get("sources") or []
        if len(sd) < int(precond.get("min_total", 0)):
            return False
        if len({s.get("bucket") for s in sd}) < int(precond.get("min_distinct_buckets", 0)):
            return False
        affil_buckets = {s.get("speaker_affiliation_bucket") for s in sd
                          if s.get("speaker_affiliation_bucket")}
        if len(affil_buckets) < int(precond.get("min_distinct_speaker_affiliation_buckets", 0)):
            return False
        return True

    if t == "max_llr":
        threshold = float(precond.get("min", 0.0))
        llr = (signals.get("within_lang_llr") or {}).get("by_bucket") or {}
        for bucket_data in llr.values():
            terms = bucket_data.get("distinctive_terms") or []
            if terms and float(terms[0].get("llr", 0)) >= threshold:
                return True
        return False

    return False  # unknown type — fail closed


def _walk_path(obj: dict, dotted: str):
    """Walk an 'analysis.paradox.joint_conclusion'-style path. Returns
    None on any missing step."""
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def pick_per_story_card_kind(signals: dict) -> str:
    """Walk card_picker.json's cascade; first match wins. The last entry
    is always a fallback so a kind is always returned."""
    cfg = _card_picker_cfg()
    for entry in cfg.get("cascade") or []:
        if _precondition_matches(entry.get("precondition") or {}, signals):
            return entry["kind"]
    return "word"  # belt-and-suspenders; cascade always ends in fallback


def compute_finding_synthesis(signals: dict, card_kind: str) -> str:
    """Produce the archetype-specific headline-finding string. The
    renderer uses this verbatim — no further editing in the frontend."""
    a = signals.get("analysis") or {}
    if card_kind == "paradox":
        p = a.get("paradox") or {}
        return (p.get("joint_conclusion") or "").strip() or "Opposing-bloc convergence detected."
    if card_kind == "shift":
        traj = (signals.get("trajectory") or {}).get("frame_trajectories") or {}
        best = (None, 0.0, None)  # (frame_id, abs_delta, signed_delta)
        for fid, entries in traj.items():
            recent = (entries or [])[-7:]
            for e in recent:
                d = e.get("delta_share")
                if d is None:
                    continue
                if abs(d) > best[1]:
                    best = (fid, abs(d), d)
        fid, _, signed = best
        if fid:
            direction = "up" if signed and signed > 0 else "down"
            return f"{fid} share moved {direction} {abs(signed) * 100:.0f}pp in the last week."
        return "Frame share moved sharply across the bucket cohort."
    if card_kind == "silence":
        coverage = signals.get("coverage") or {}
        non_cov = (coverage.get("non_coverage") or {}).get(signals.get("story_key")) or {}
        silent = [b for b, info in non_cov.items()
                   if isinstance(info, dict) and info.get("state") == "silent"]
        n = len(silent)
        if n >= 1:
            sample = ", ".join(silent[:3])
            tail = f" and {n - 3} more" if n > 3 else ""
            return f"{n} buckets that usually cover this stayed silent — {sample}{tail}."
        return "Coverage gap detected across the bucket cohort."
    if card_kind == "tilt":
        best = None  # (z, term, outlet, bucket)
        for tilt in signals.get("tilt_files") or []:
            wire = ((tilt.get("anchors") or {}).get("wire") or {})
            pos = wire.get("positive_tilt") or []
            if not pos:
                continue
            top = pos[0]
            z = float(top.get("z_score", 0))
            if best is None or z > best[0]:
                bg = top.get("bigram") or []
                term = " ".join(bg) if isinstance(bg, list) else str(bg)
                best = (z, term, tilt.get("outlet"), tilt.get("bucket"))
        if best:
            z, term, outlet, bucket = best
            return f"{outlet} ({bucket}) over-uses '{term}' vs wire at z={z:.1f}."
        return "Per-outlet vocabulary tilt detected vs wire baseline."
    if card_kind == "sources":
        sd = (signals.get("sources") or {}).get("sources") or []
        affil = {s.get("speaker_affiliation_bucket") for s in sd if s.get("speaker_affiliation_bucket")}
        return (f"{len(sd)} speakers across {len({s.get('bucket') for s in sd})} "
                f"buckets, {len(affil)} distinct affiliation types.")
    if card_kind == "word":
        llr = (signals.get("within_lang_llr") or {}).get("by_bucket") or {}
        best = None  # (llr, term, bucket)
        for bucket, data in llr.items():
            terms = data.get("distinctive_terms") or []
            if not terms:
                continue
            top = terms[0]
            score = float(top.get("llr", 0))
            if best is None or score > best[0]:
                best = (score, top.get("term"), bucket)
        if best:
            return f"{best[2]} corpus over-uses '{best[1]}' (llr {best[0]:.0f}) vs same-language cohort."
        return "Vocabulary signal accruing." # empty-state for day-zero stories
    return ""


def _recent_dates(today: str, lookback_days: int) -> list[str]:
    """Return the last `lookback_days` dates ending at `today` (exclusive
    of today itself) that have an api/<date>/index.json on disk. Used
    to populate the home page's 5-day archive list."""
    from datetime import date as _date, timedelta
    try:
        today_d = _date.fromisoformat(today)
    except ValueError:
        return []
    out: list[str] = []
    for offset in range(1, lookback_days + 1):
        prev = (today_d - timedelta(days=offset)).isoformat()
        if (API / prev / "index.json").exists():
            out.append(prev)
    return out


def _recent_hero_history(today: str, lookback_days: int) -> list[dict]:
    """Walk api/<prev_date>/index.json for the lookback window; pull the
    todays_card block out of each. Used by pick_todays_card to apply
    the diversity penalty. Bootstraps gracefully (empty list = no
    penalty)."""
    from datetime import date as _date, timedelta
    try:
        today_d = _date.fromisoformat(today)
    except ValueError:
        return []
    history: list[dict] = []
    for offset in range(1, lookback_days + 1):
        prev = (today_d - timedelta(days=offset)).isoformat()
        idx = _safe_load(API / prev / "index.json")
        if idx and idx.get("todays_card"):
            history.append(idx["todays_card"])
    return history


def pick_todays_card(stories: list[dict], today: str) -> dict | None:
    """Score every story per today_picker.json and pick the max.

    `stories` is a list of dicts each carrying at minimum: story_key,
    n_buckets, card_kind, and `signals` (the collect_story_signals
    output). Returns a dict with story_key + card_kind + headline +
    kicker + finding_synthesis + score_breakdown, or None if no story
    clears the min_n_buckets_for_hero gate.
    """
    cfg = _today_picker_cfg()
    scoring = cfg.get("scoring") or {}
    min_buckets = int(scoring.get("min_n_buckets_for_hero", 0))
    mag = scoring.get("magnitude") or {}
    mag_weight = float(mag.get("weight", 0.30))
    strength_weights = scoring.get("archetype_strength_weights") or {}
    div = scoring.get("diversity_bonus") or {}
    penalty_same_kind = float(div.get("penalty_for_same_archetype", 0.0))
    penalty_same_key = float(div.get("penalty_for_same_story_key", 0.0))
    history = _recent_hero_history(today, int(div.get("lookback_days", 5)))
    recent_kinds = {h.get("card_kind") for h in history}
    recent_keys = {h.get("story_key") for h in history}

    eligible: list[tuple[float, dict, dict]] = []
    for s in stories:
        if (s.get("n_buckets") or 0) < min_buckets:
            continue
        kind = s.get("card_kind") or "word"
        strength = float(strength_weights.get(kind, 0.0))
        n_b = float(s.get("n_buckets") or 0)
        magnitude = (n_b / 54.0) * mag_weight  # normalize: 54 = current n_buckets
        diversity = 1.0
        if kind in recent_kinds:
            diversity -= penalty_same_kind
        if s.get("story_key") in recent_keys:
            diversity -= penalty_same_key
        diversity = max(diversity, 0.0)
        score = (magnitude + strength) * diversity
        breakdown = {
            "magnitude": round(magnitude, 3),
            "archetype_strength": round(strength, 3),
            "diversity_bonus": round(diversity, 3),
            "final_score": round(score, 3),
        }
        eligible.append((score, s, breakdown))

    if not eligible:
        return None
    # Sort by score desc, tie-break story_key asc.
    eligible.sort(key=lambda r: (-r[0], r[1].get("story_key", "")))
    score, story, breakdown = eligible[0]
    signals = story.get("signals") or {}
    a = signals.get("analysis") or {}
    return {
        "story_key": story["story_key"],
        "story_title": story.get("title"),
        "card_kind": story["card_kind"],
        # Headline is the journalistic name of the story — the H1 readers see.
        # The finding_synthesis (machine-generated analytical observation) is
        # surfaced separately by the renderer as a synthesis line; it should
        # not be the H1.
        "headline": story.get("title") or story.get("story_key", ""),
        "kicker": (a.get("event_summary") or a.get("tldr") or "").strip(),
        "finding_synthesis": story.get("finding_synthesis", ""),
        "score_breakdown": breakdown,
        "see_how_path": f"/{today}/{story['story_key']}/analysis.md",
    }


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

        # PR A+: collect signals, run cascade picker, stamp card_kind +
        # event_summary + finding_synthesis. The picker gracefully
        # degrades when any signal source is absent.
        signals = collect_story_signals(date, key, briefing)
        card_kind = pick_per_story_card_kind(signals)
        a = signals.get("analysis") or {}
        event_summary = a.get("event_summary") or a.get("tldr") or ""
        entry["card_kind"] = card_kind
        if event_summary:
            entry["event_summary"] = event_summary.strip()
        entry["finding_synthesis"] = compute_finding_synthesis(signals, card_kind)
        # Stash signals on the entry for pick_todays_card; stripped
        # before writing to disk.
        entry["_signals"] = signals

        story_entries.append(entry)

    if not story_entries:
        return None

    # PR A+: daily hero pick across the story list. Writes api/today.json
    # and stamps a todays_card block at the top of the per-date index.
    todays_card = pick_todays_card(
        [{"story_key": e["key"], "title": e["title"],
          "n_buckets": e.get("n_buckets"),
          "card_kind": e.get("card_kind"),
          "finding_synthesis": e.get("finding_synthesis", ""),
          "signals": e.get("_signals", {})}
         for e in story_entries],
        date,
    )
    # Strip the private _signals before serialising story entries.
    for e in story_entries:
        e.pop("_signals", None)

    index_payload: dict = {
        "date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_stories": len(story_entries),
        "stories": story_entries,
    }
    if todays_card:
        index_payload["todays_card"] = {k: v for k, v in todays_card.items()
                                          if k != "see_how_path"}
        # Write api/today.json with full hero payload (includes see_how_path).
        today_payload = meta.stamp({
            "date": date,
            **todays_card,
        })
        (API / "today.json").write_text(
            json.dumps(today_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # PR D-1: render the full home page server-side. Pulls the
        # picked story's signals fresh from disk (the in-memory
        # _signals were stripped above) + every other story's display
        # fields + a 5-day archive list, and writes api/index.html.
        # Replaces the design-preview placeholder content from the
        # cherry-pick.
        from publication.card_renderers import render_index_html
        picked_briefing = json.loads(
            (BRIEFINGS / f"{date}_{todays_card['story_key']}.json")
            .read_text(encoding="utf-8")
        )
        picked_signals = collect_story_signals(
            date, todays_card["story_key"], picked_briefing
        )
        other_stories = [
            {**e, "date": date}
            for e in story_entries
            if e["key"] != todays_card["story_key"]
        ]
        archive_dates = _recent_dates(date, lookback_days=5)
        index_html = render_index_html(
            today_payload, picked_signals, other_stories, archive_dates
        )
        (API / "index.html").write_text(index_html, encoding="utf-8")

        # PR D-2: render PNGs for og:image / social share. Two
        # viewports: 1200x675 native (the og:image the page declares)
        # and 1200x630 twitter (Twitter card spec). Wrapped in
        # try/except so a missing playwright install or chromium
        # download skips PNG generation rather than failing publish —
        # the HTML home page still works.
        try:
            from publication.card_renderers import render_card_html, render_card_png
            card_html = render_card_html(today_payload, picked_signals)
            styles_text = (WEB_SRC / "styles.css").read_text(encoding="utf-8")
            for viewport, name in (("today", "today.png"),
                                     ("today-twitter", "today-twitter.png")):
                png_bytes = render_card_png(card_html, styles_text, viewport=viewport)
                (API / name).write_bytes(png_bytes)
        except RuntimeError as e:
            print(f"  PNG render skipped: {e}", file=sys.stderr)
        except Exception as e:  # pragma: no cover — chromium can be flaky
            print(f"  PNG render failed: {e}", file=sys.stderr)

    index = meta.stamp(index_payload)
    (out_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Plan 2: per-story HTML pages + today's coverage matrix.
    # Each story gets a multi-card-stack page at /<date>/<story>/index.html
    # composed from every archetype renderer that has signal.
    from publication.page_renderers import render_story_page, render_coverage_page
    for entry in story_entries:
        story_key = entry["key"]
        story_dir_local = out_dir / story_key
        if not story_dir_local.exists():
            continue
        try:
            briefing = json.loads(
                (BRIEFINGS / f"{date}_{story_key}.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue
        signals_local = collect_story_signals(date, story_key, briefing)
        long_path = DRAFTS / f"{date}_{story_key}_long.json"
        long_draft = None
        if long_path.exists():
            try:
                long_draft = json.loads(long_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                long_draft = None
        try:
            story_html = render_story_page(date, story_key, signals_local, entry, long_draft)
            (story_dir_local / "index.html").write_text(story_html, encoding="utf-8")
        except Exception as e:  # pragma: no cover — defensive
            print(f"  story page render failed for {story_key}: {e}", file=sys.stderr)

    # Today's coverage matrix — single page rendering coverage/<DATE>.json.
    coverage_src = COVERAGE / f"{date}.json"
    if coverage_src.exists():
        try:
            coverage_data = json.loads(coverage_src.read_text(encoding="utf-8"))
            coverage_html = render_coverage_page(date, coverage_data, story_entries)
            (out_dir / "coverage.html").write_text(coverage_html, encoding="utf-8")
        except (OSError, json.JSONDecodeError, Exception) as e:  # pragma: no cover
            print(f"  coverage page render failed: {e}", file=sys.stderr)

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
    """Copy web/ assets (styles.css, app.js, corrections.html,
    methodology-challenge.html) into api/.

    Pages serves api/ at the site root. As of PR D-1 (meta-v8.7.0)
    api/index.html is RENDERED server-side per day by
    render_index_html() — we skip copying web/index.html here so the
    rendered version isn't overwritten by the design-preview
    template. If build_one_date() doesn't run (empty pipeline day),
    the design-preview index.html falls back via the explicit
    fallback path below. Idempotent.
    """
    if not WEB_SRC.is_dir():
        return
    API.mkdir(parents=True, exist_ok=True)
    for p in WEB_SRC.iterdir():
        if not p.is_file():
            continue
        if p.name == "index.html" and (API / "index.html").exists():
            # The renderer wrote api/index.html; don't clobber.
            continue
        shutil.copy2(p, API / p.name)


def copy_outlet_pages() -> int:
    """Plan 2: walk tilt/<bucket>__<outlet>.json and emit a per-outlet HTML
    page at api/outlet/<bucket>__<outlet>/index.html. Returns the number
    written."""
    if not TILT.is_dir():
        return 0
    from publication.page_renderers import render_outlet_page
    out_base = API / "outlet"
    out_base.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted(TILT.glob("*.json")):
        try:
            tilt = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        bucket = tilt.get("bucket") or p.stem.split("__", 1)[0]
        outlet = tilt.get("outlet") or p.stem.split("__", 1)[-1]
        # Filename-safe directory: same stem as the tilt file.
        slug = p.stem
        out_dir = out_base / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            html = render_outlet_page(bucket, outlet, tilt)
            (out_dir / "index.html").write_text(html, encoding="utf-8")
            n += 1
        except Exception as e:  # pragma: no cover
            print(f"  outlet page render failed for {slug}: {e}", file=sys.stderr)
    return n


def write_methodology_page() -> None:
    """Plan 2: render the methodology page that surfaces today's pin +
    codebook + analysis prompt + picker explanation + drift segments."""
    from publication.page_renderers import render_methodology_page
    meta_dict = json.loads(meta.META_PATH.read_text(encoding="utf-8"))
    # Load the codebook (frames + descriptions).
    codebook_path = ROOT / "frames_codebook.json"
    codebook = None
    if codebook_path.exists():
        try:
            codebook = json.loads(codebook_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            codebook = None
    # Daily analysis prompt.
    prompt_path = ROOT / ".claude" / "prompts" / "daily_analysis.md"
    prompt_md = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    # Picker configs.
    card_picker = json.loads(meta.CARD_PICKER_PATH.read_text(encoding="utf-8")) \
        if meta.CARD_PICKER_PATH.exists() else {}
    today_picker = json.loads(meta.TODAY_PICKER_PATH.read_text(encoding="utf-8")) \
        if meta.TODAY_PICKER_PATH.exists() else {}
    # Today's score breakdown (from api/today.json if present).
    todays_card = None
    today_json = API / "today.json"
    if today_json.exists():
        try:
            todays_card = json.loads(today_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            todays_card = None
    # Drift segments section from METHODOLOGY.md.
    drift_md = ""
    method_md = ROOT / "docs" / "METHODOLOGY.md"
    if method_md.exists():
        try:
            text = method_md.read_text(encoding="utf-8")
            # Capture "## Drift-segment collapses" through the next h2 or EOF.
            m = re.search(r"## Drift-segment collapses\n(.+?)(?=\n## |\Z)", text, re.S)
            if m:
                drift_md = m.group(1).strip()
        except OSError:
            drift_md = ""
    html = render_methodology_page(meta_dict, codebook, prompt_md,
                                     card_picker, today_picker, todays_card,
                                     drift_md)
    out_dir = API / "methodology"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def write_archive_page() -> None:
    """Plan 2: render the archive browser. Walks every api/<date>/index.json
    and produces a chronological table."""
    from publication.page_renderers import render_archive_page
    date_indexes: list[tuple[str, dict]] = []
    for sub in sorted(API.iterdir(), reverse=True):
        if not sub.is_dir():
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", sub.name):
            continue
        idx_path = sub / "index.json"
        if not idx_path.exists():
            continue
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            date_indexes.append((sub.name, idx))
        except (OSError, json.JSONDecodeError):
            continue
    if not date_indexes:
        return
    html = render_archive_page(date_indexes)
    out_dir = API / "archive"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")


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

    # Plan 2: site-level pages (methodology + archive + outlet fingerprints).
    try:
        write_methodology_page()
        print("  + methodology page → api/methodology/")
    except Exception as e:  # pragma: no cover
        print(f"  methodology page failed: {e}", file=sys.stderr)
    try:
        write_archive_page()
        print("  + archive page → api/archive/")
    except Exception as e:  # pragma: no cover
        print(f"  archive page failed: {e}", file=sys.stderr)
    try:
        n_outlet = copy_outlet_pages()
        if n_outlet:
            print(f"  + {n_outlet} outlet fingerprint pages → api/outlet/")
    except Exception as e:  # pragma: no cover
        print(f"  outlet pages failed: {e}", file=sys.stderr)

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
