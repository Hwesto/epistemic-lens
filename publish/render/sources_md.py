"""render_sources_md.py — render `sources/<DATE>_<story>.json` to MD.

Companion to `render_analysis_md.py`. Produces a focused "Voices" markdown
file per story that's useful in isolation (e.g. for an outlet-specific
audit trail). The story-level analysis MD also embeds a Voices section
inline; this module is for cases where consumers want sources alone.

Output: `sources/<DATE>_<story_key>.md` (sits alongside the JSON).

Usage:
  python -m publication.render_sources_md
  python -m publication.render_sources_md --date 2026-05-08
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
SOURCES = ROOT / "sources"


def render_sources(sources_doc: dict) -> str:
    """JSON sources doc → markdown."""
    out: list[str] = []
    out.append(f"# Voices — {sources_doc.get('story_title', '?')}")
    out.append("")
    out.append(f"**Date:** {sources_doc.get('date', '?')}  ")
    out.append(f"**Story key:** `{sources_doc.get('story_key', '?')}`  ")
    sources = sources_doc.get("sources") or []
    out.append(f"**Sources extracted:** {len(sources)}  ")
    out.append(f"**Methodology pin:** `meta_version "
               f"{sources_doc.get('meta_version', '?')}`")
    out.append("")
    out.append("---")
    out.append("")

    if not sources:
        out.append("_No source quotes were extracted from this story. The "
                   "underlying articles may have been wire-style or stub-only._")
        return "\n".join(out)

    # Speaker rollup
    speakers = Counter()
    types = Counter()
    stances = Counter()
    by_outlet: dict[str, list] = defaultdict(list)
    for s in sources:
        sp = s.get("speaker_name") or f"<unnamed: {s.get('role_or_affiliation', '?')}>"
        speakers[sp] += 1
        types[s.get("speaker_type", "unknown")] += 1
        stances[s.get("stance_toward_target", "unclear")] += 1
        by_outlet[s.get("outlet", "?")].append(s)

    out.append("## Top speakers")
    out.append("")
    out.append("| Speaker | Quotes |")
    out.append("| --- | ---: |")
    for sp, n in speakers.most_common(10):
        out.append(f"| {sp} | {n} |")
    out.append("")

    out.append("## Speaker type distribution")
    out.append("")
    for t, n in types.most_common():
        out.append(f"- **{t}**: {n}")
    out.append("")

    out.append("## Stance distribution")
    out.append("")
    for s, n in stances.most_common():
        out.append(f"- **{s}**: {n}")
    out.append("")

    out.append("## Quotes by outlet")
    out.append("")
    for outlet in sorted(by_outlet):
        rows = by_outlet[outlet]
        out.append(f"### {outlet} ({len(rows)} quotes)")
        out.append("")
        for s in rows:
            speaker = s.get("speaker_name") or s.get("role_or_affiliation", "?")
            verb = s.get("attributive_verb", "said")
            quote = (s.get("exact_quote") or "").strip()
            out.append(f"- **{speaker}** {verb}: > {quote}")
            out.append(f"  _({s.get('speaker_type', 'unknown')}; "
                       f"stance: {s.get('stance_toward_target', 'unclear')})_")
        out.append("")

    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None)
    ap.add_argument("files", nargs="*", type=Path)
    args = ap.parse_args()

    if args.files:
        targets = list(args.files)
    else:
        date = args.date or datetime.now(timezone.utc).date().isoformat()
        targets = [
            p for p in SOURCES.glob(f"{date}_*.json")
            if p.parent.name != "aggregate"
        ]
    if not targets:
        print("No sources files to render.")
        return 0

    for p in targets:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  skip {p.name}: {e}", file=sys.stderr)
            continue
        md = render_sources(doc)
        out_path = p.with_suffix(".md")
        out_path.write_text(md, encoding="utf-8")
        print(f"  + {p.name} -> {out_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
