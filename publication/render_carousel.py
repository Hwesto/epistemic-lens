#!/usr/bin/env python3
"""render_carousel.py — template-based carousel draft from a JSON analysis.

Sibling of render_thread.py. Slide-deck format suitable for Instagram /
LinkedIn / TikTok-still rendering. Deterministic Python; no LLM.

Slide order (variable; only the title slide is mandatory):
  1. Title (n_buckets, n_articles, story_title)
  2. The most striking finding (paradox > isolation > exclusive vocab > generic)
  3..N. One slide per frame (kind=frame), most-buckets-first
  N+1. Paradox slide (kind=paradox), if exists
  N+2. Silence slide (kind=silence), if any silences
  Last. Closing CTA

Schema: docs/api/schema/carousel.schema.json — slides array 4..10.
We aim for 6-8 slides per story.

Usage:
  python render_carousel.py
  python render_carousel.py --date 2026-05-08
  python render_carousel.py analyses/<file>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta
from publication._shared import (
    ISOLATION_HERO_THRESHOLD,
    corpus_source as _corpus_source,
    load_briefing as _load_briefing,
    truncate as _truncate,
    validate_against_schema,
)

ROOT = meta.REPO_ROOT
ANALYSES = ROOT / "analyses"
DRAFTS = ROOT / "drafts"

MAX_SLIDE_BODY_CHARS = 200


def _title_slide(a: dict) -> dict:
    return {
        "title": a["story_title"],
        "body": _truncate(
            f"{a['n_buckets']} buckets · {a['n_articles']} articles · "
            f"{len(a.get('frames') or [])} frames",
            MAX_SLIDE_BODY_CHARS,
        ),
        "kind": "callout",
    }


def _hook_slide(a: dict, briefing: dict) -> dict | None:
    """Most striking finding — first body slide after title."""
    p = a.get("paradox")
    if p:
        return {
            "title": "The paradox",
            "body": _truncate(p["joint_conclusion"], MAX_SLIDE_BODY_CHARS),
            "kind": "paradox",
        }
    iso = a.get("isolation_top") or []
    if iso and iso[0].get("mean_jaccard", 1) < ISOLATION_HERO_THRESHOLD:
        b = iso[0]
        return {
            "title": f"`{b['bucket']}` stands alone",
            "body": _truncate(
                b.get("note") or f"mean_jaccard {b['mean_jaccard']} — most isolated.",
                MAX_SLIDE_BODY_CHARS,
            ),
            "kind": "stat",
        }
    excl = a.get("exclusive_vocab_highlights") or []
    if excl:
        h = excl[0]
        return {
            "title": f"Only `{h['bucket']}` says these words",
            "body": _truncate(
                ", ".join(h["terms"][:5])
                + (f". {h.get('what_it_reveals')}" if h.get("what_it_reveals") else ""),
                MAX_SLIDE_BODY_CHARS,
            ),
            "kind": "stat",
        }
    return None


def _frame_slide(frame: dict, briefing: dict) -> dict | None:
    if not frame.get("evidence"):
        return None
    ev = frame["evidence"][0]
    n_b = len(frame.get("buckets", []))
    body_parts = [f"{n_b} bucket{'s' if n_b != 1 else ''}"]
    if frame.get("description"):
        body_parts.append(frame["description"])
    body_parts.append(f'"{ev["quote"]}" — {ev.get("outlet") or ev["bucket"]}')
    body = " · ".join(body_parts)
    slide: dict = {
        "title": frame["label"],
        "body": _truncate(body, MAX_SLIDE_BODY_CHARS),
        "kind": "frame",
    }
    src = _corpus_source(briefing, ev["signal_text_idx"])
    if src:
        slide["source"] = src
    return slide


def _silence_slide(silences: list) -> dict | None:
    if not silences:
        return None
    s = silences[0]
    return {
        "title": "Silence as data",
        "body": _truncate(
            f"`{s['bucket']}` didn't cover this. They covered "
            f"{s['what_they_covered_instead']} instead.",
            MAX_SLIDE_BODY_CHARS,
        ),
        "kind": "silence",
    }


def _closing_slide() -> dict:
    return {
        "title": "Daily framings",
        "body": "epistemic-lens · how the world tells the same story differently.",
        "kind": "callout",
    }


def render(a: dict, briefing: dict) -> dict:
    slides: list[dict] = [_title_slide(a)]

    h = _hook_slide(a, briefing)
    hook_was_paradox = h is not None and h.get("kind") == "paradox"
    if h:
        slides.append(h)

    # Frames, most-buckets-first
    frames = sorted(a.get("frames") or [],
                    key=lambda f: -len(f.get("buckets", [])))
    for f in frames[:5]:
        s = _frame_slide(f, briefing)
        if s:
            slides.append(s)

    # Silence — preferred unless the hook already led on the paradox
    # angle AND we're tight on slots. Equivalent to the original two-
    # branch logic, but reads as one expression and doesn't index into
    # slides[1] (which would IndexError if hook was None and frames
    # was empty — unreachable today, but fragile).
    sil = _silence_slide(a.get("silences") or [])
    if sil and (not hook_was_paradox or len(slides) < 9):
        slides.append(sil)

    # Schema requires 4..10 slides. Trim the BODY to 9 first, then
    # append the closing CTA — so the closing is never the slide that
    # gets dropped when we exceed the cap.
    slides = slides[:9]
    slides.append(_closing_slide())

    if len(slides) < 4:
        # Floor protection: pad with a metric callout if we're under
        # schema's minItems=4. Unreachable today (frames.minItems=2
        # guarantees ≥4), but kept for defence in depth.
        iso = a.get("isolation_top") or []
        if iso:
            top = iso[0]
            slides.insert(-1, {
                "title": f"Most isolated: `{top['bucket']}`",
                "body": _truncate(top.get("note") or
                                  f"mean_jaccard {top['mean_jaccard']}", MAX_SLIDE_BODY_CHARS),
                "kind": "stat",
            })

    out = {
        "story_key": a["story_key"],
        "date": a["date"],
        "title": a["story_title"],
        "slides": slides,
        "closing": "Read the full analysis: api/" + a["date"] + "/" + a["story_key"] + "/analysis.md",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": "template:render_carousel.py",
    }
    return meta.stamp(out)


class RenderError(Exception):
    """Raised by render_one for per-file failures (corrupt JSON, schema
    rejection, unreadable file). main() catches these so one bad analysis
    doesn't block the others."""


def render_one(json_path: Path) -> Path:
    try:
        a = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RenderError(f"corrupt JSON: {e}") from e
    except OSError as e:
        raise RenderError(f"unreadable: {e}") from e
    briefing = _load_briefing(a["date"], a["story_key"])
    draft = render(a, briefing)
    validate_against_schema(draft, "carousel")
    DRAFTS.mkdir(exist_ok=True)
    out = DRAFTS / f"{a['date']}_{a['story_key']}_carousel.json"
    out.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    targets = list(args.files) if args.files else sorted(
        ANALYSES.glob(f"{args.date or datetime.now(timezone.utc).strftime('%Y-%m-%d')}_*.json")
    )
    if not targets:
        print("No analyses to render carousels from.")
        return 0

    n_failed = 0
    for t in targets:
        if t.suffix != ".json":
            print(f"  FAIL  {t.name}: not a .json file", file=sys.stderr)
            n_failed += 1
            continue
        try:
            out = render_one(t)
        except (RenderError, ValueError, KeyError) as e:
            print(f"  FAIL  {t.name}: {e}", file=sys.stderr)
            n_failed += 1
            continue
        print(f"  +  {t.name:<48} -> {out.name}")

    if n_failed:
        print(f"\n{n_failed} render failure(s) across {len(targets)} file(s).",
              file=sys.stderr)
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
