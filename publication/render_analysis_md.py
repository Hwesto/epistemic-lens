#!/usr/bin/env python3
"""render_analysis_md.py — render JSON analyses into human-readable markdown.

The canonical analytical artifact is `analyses/<DATE>_<story_key>.json` — the
shape Claude emits, schema-validated against `docs/api/schema/analysis.schema.json`.
This script reads those JSON files and produces matching `.md` files for PR
review and the Pages render.

The MD is a presentation layer. Never the source of truth. If you want to
edit the analysis, edit the JSON.

Usage:
  python render_analysis_md.py                   # all today's analyses
  python render_analysis_md.py --date 2026-05-08 # specific date
  python render_analysis_md.py FILE.json         # specific file
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from meta import REPO_ROOT as ROOT
from analytical.build_metrics import weighted_frame_distribution
ANALYSES = ROOT / "analyses"
BRIEFINGS = ROOT / "briefings"


SOURCES = ROOT / "sources"


def _load_sources_sibling(analysis: dict) -> dict | None:
    """Load `sources/<DATE>_<story>.json` for the given analysis. Returns
    None if missing (Phase 3a; renderer's section is skipped if absent)."""
    date = analysis.get("date")
    story_key = analysis.get("story_key")
    if not (date and story_key):
        return None
    p = SOURCES / f"{date}_{story_key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_sibling(analysis: dict, suffix: str) -> dict | None:
    """Load sibling JSON `<DATE>_<story>{suffix}.json`.

    Looks first under `briefings/` (where LLR/PMI artefacts live) then under
    `analyses/` (where divergence lives). Returns None if missing/unreadable
    so the renderer's section is simply skipped.
    """
    date = analysis.get("date")
    story_key = analysis.get("story_key")
    if not (date and story_key):
        return None
    candidates = [
        BRIEFINGS / f"{date}_{story_key}{suffix}.json",
        ANALYSES / f"{date}_{story_key}{suffix}.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def render(a: dict) -> str:
    """JSON analysis dict -> markdown string."""
    out: list[str] = []

    # Header
    out.append(f"# {a['story_title']}")
    out.append("")
    out.append(f"**Date:** {a['date']}  ")
    out.append(f"**Story key:** `{a['story_key']}`  ")
    out.append(f"**Coverage:** {a['n_buckets']} buckets, {a['n_articles']} articles  ")
    if a.get("model"):
        out.append(f"**Model:** `{a['model']}`  ")
    out.append(f"**Methodology pin:** `meta_version {a.get('meta_version', '?')}`  ")
    out.append("")
    out.append("---")
    out.append("")

    # TL;DR
    out.append("## TL;DR")
    out.append("")
    out.append(a["tldr"])
    out.append("")

    # Frames
    out.append(f"## Frames ({len(a['frames'])})")
    out.append("")
    for f in a["frames"]:
        heading = f.get("frame_id") or f.get("label") or "UNLABELED"
        if f.get("sub_frame"):
            heading = f"{heading} — {f['sub_frame']}"
        out.append(f"### {heading}")
        out.append("")
        out.append(f"**Buckets:** {', '.join(f'`{b}`' for b in f['buckets'])}")
        out.append("")
        for ev in f["evidence"]:
            attribution = f"`{ev['bucket']}`"
            if ev.get("outlet"):
                attribution = f"`{ev['bucket']}` / {ev['outlet']}"
            out.append(f"> {ev['quote'].strip()}")
            out.append(f">")
            out.append(f"> — {attribution} (corpus[{ev['signal_text_idx']}])")
            out.append("")

    # Population-weighted view (Phase 1). Reads bucket_weights.json via
    # build_metrics.weighted_frame_distribution; weighted_share is the
    # population × audience-reach share of each frame; bootstrap CIs (5/95
    # over 1000 bucket-resampled iters) hedge against bucket-set sampling
    # error. Low-confidence buckets (weight=0 or default) flagged.
    wfd = weighted_frame_distribution(a)
    if wfd.get("frames"):
        out.append("## Population-weighted view")
        out.append("")
        out.append(
            "Weighted by bucket population × audience reach (`bucket_weights.json`); "
            "bootstrap CI 5–95% over 1000 bucket-resampled iterations. Unweighted "
            "share = 1 / (frames carrying any bucket) for comparison."
        )
        out.append("")
        bs = wfd.get("bootstrap") or {}
        cis_available = "weighted_share_ci_lo" in next(iter(wfd["frames"].values()), {})
        if cis_available:
            out.append("| Frame | Weighted share | 90% CI | Unweighted | Buckets |")
            out.append("| --- | ---: | --- | ---: | ---: |")
        else:
            out.append("| Frame | Weighted share | Unweighted | Buckets |")
            out.append("| --- | ---: | ---: | ---: |")
        for fid, info in wfd["frames"].items():
            ws = info["weighted_share"]
            uw = info["unweighted_share"]
            bn = info.get("buckets_total", "")
            if cis_available:
                ci = f"[{info['weighted_share_ci_lo']:.2f}, {info['weighted_share_ci_hi']:.2f}]"
                out.append(f"| `{fid}` | {ws:.3f} | {ci} | {uw:.3f} | {bn} |")
            else:
                out.append(f"| `{fid}` | {ws:.3f} | {uw:.3f} | {bn} |")
        out.append("")
        if wfd.get("low_confidence_buckets"):
            out.append(
                "_Low-confidence weights (treat with caution): "
                + ", ".join(f"`{b}`" for b in wfd["low_confidence_buckets"]) + "._"
            )
            out.append("")
        if wfd.get("default_weight_buckets"):
            out.append(
                "_Default-weight buckets (no entry in `bucket_weights.json`): "
                + ", ".join(f"`{b}`" for b in wfd["default_weight_buckets"]) + "._"
            )
            out.append("")
        if bs and bs.get("skipped"):
            out.append(f"_Bootstrap CIs skipped: {bs.get('reason', 'unknown')}._")
            out.append("")

    # Divergence (LaBSE cosine; field name `isolation_top` retained for schema continuity)
    if a.get("isolation_top"):
        out.append("## Most divergent buckets")
        out.append("")
        out.append("| Bucket | mean_similarity | Note |")
        out.append("| --- | --- | --- |")
        for r in a["isolation_top"]:
            score = r.get("mean_similarity", "")
            note = r.get("note", "")
            out.append(f"| `{r['bucket']}` | {score} | {note} |")
        out.append("")

    # Exclusive vocab
    if a.get("exclusive_vocab_highlights"):
        out.append("## Bucket-exclusive vocabulary")
        out.append("")
        out.append("| Bucket | Distinctive terms | What it reveals |")
        out.append("| --- | --- | --- |")
        for h in a["exclusive_vocab_highlights"]:
            terms = ", ".join(f"*{t}*" for t in h["terms"])
            reveals = h.get("what_it_reveals", "")
            out.append(f"| `{h['bucket']}` | {terms} | {reveals} |")
        out.append("")

    # Within-language LLR (Phase 2). Read the sibling JSON if it exists.
    llr_data = _load_sibling(a, "_within_lang_llr")
    if llr_data and llr_data.get("by_bucket"):
        out.append("## Within-language LLR distinctive vocab")
        out.append("")
        out.append(
            "Per-bucket terms over-represented vs the same-language cohort "
            "(Dunning log-likelihood ratio; p ≤ 0.001). Effect size is "
            "log-rate-ratio."
        )
        out.append("")
        out.append("| Bucket | Lang | Top distinctive terms (LLR) |")
        out.append("| --- | --- | --- |")
        for bucket, info in llr_data["by_bucket"].items():
            terms = info.get("distinctive_terms") or []
            if not terms:
                continue
            preview = ", ".join(
                f"`{t['term']}` ({t['llr']})" for t in terms[:5]
            )
            out.append(f"| `{bucket}` | {info.get('lang', '?')} | {preview} |")
        out.append("")

    # Within-language PMI / log-odds bigrams (Phase 2).
    pmi_data = _load_sibling(a, "_within_lang_pmi")
    if pmi_data and pmi_data.get("by_bucket"):
        out.append("## Associative bigrams (within-language)")
        out.append("")
        out.append(
            "Bigrams over-represented in this bucket vs the same-language "
            "cohort. Log-odds with Jeffreys prior; |Z| ≥ 1.96."
        )
        out.append("")
        out.append("| Bucket | Lang | Top bigram associations |")
        out.append("| --- | --- | --- |")
        for bucket, info in pmi_data["by_bucket"].items():
            assocs = info.get("associations") or []
            if not assocs:
                continue
            preview = ", ".join(
                f"`{' '.join(a['bigram'])}` (z={a['z_score']})" for a in assocs[:4]
            )
            out.append(f"| `{bucket}` | {info.get('lang', '?')} | {preview} |")
        out.append("")

    # Voices — source attribution (Phase 3a).
    sources_doc = _load_sources_sibling(a)
    if sources_doc and sources_doc.get("sources"):
        from collections import Counter, defaultdict
        sources = sources_doc["sources"]
        out.append("## Voices")
        out.append("")
        out.append(
            f"{len(sources)} direct quote(s) extracted across "
            f"{len({s.get('outlet') for s in sources})} outlet(s)."
        )
        out.append("")
        # Top speakers
        speakers = Counter()
        types = Counter()
        for s in sources:
            sp = s.get("speaker_name") or f"<unnamed: {s.get('role_or_affiliation', '?')}>"
            speakers[sp] += 1
            types[s.get("speaker_type", "unknown")] += 1
        out.append("**Top speakers:** "
                   + ", ".join(f"{sp} ({n})" for sp, n in speakers.most_common(5)))
        out.append("")
        out.append("**Speaker types:** "
                   + ", ".join(f"{t} {n}" for t, n in types.most_common()))
        out.append("")

    # Headline-body divergence (Phase 2).
    div_data = _load_sibling(a, "_divergence")
    if div_data and div_data.get("n_buckets_compared", 0) > 0:
        out.append("## Sensationalism index (headline ↔ body divergence)")
        out.append("")
        rate = div_data.get("agreement_rate")
        n_compared = div_data.get("n_buckets_compared")
        n_diverging = len(div_data.get("highest_diverging_buckets") or [])
        out.append(
            f"**Agreement rate:** {rate} across {n_compared} buckets "
            f"compared. {n_diverging} bucket(s) carry a different dominant "
            f"frame in their headline than their body."
        )
        out.append("")
        diverging = div_data.get("highest_diverging_buckets") or []
        if diverging:
            out.append("| Bucket | Body frame | Headline frame |")
            out.append("| --- | --- | --- |")
            for d in diverging[:8]:
                out.append(
                    f"| `{d['bucket']}` | `{d['body_frame']}` | "
                    f"`{d['headline_frame']}` |"
                )
            out.append("")

    # Paradox
    out.append("## Paradox")
    out.append("")
    p = a.get("paradox")
    if p is None:
        out.append("_No paradox in this corpus._")
    else:
        out.append(f"**{p['joint_conclusion']}**")
        out.append("")
        for side_key in ("a", "b"):
            s = p[side_key]
            out.append(f"> {s['quote'].strip()}")
            out.append(f">")
            out.append(f"> — `{s['bucket']}` / {s['outlet']} (corpus[{s['signal_text_idx']}])")
            out.append("")
    out.append("")

    # Silences
    if a.get("silences"):
        out.append("## Silence as data")
        out.append("")
        for s in a["silences"]:
            out.append(f"- **`{s['bucket']}`** — {s['what_they_covered_instead']}")
        out.append("")

    # Single-outlet findings
    if a.get("single_outlet_findings"):
        out.append("## Single-outlet findings")
        out.append("")
        for i, f in enumerate(a["single_outlet_findings"], 1):
            ref = (f" (corpus[{f['signal_text_idx']}])"
                   if f.get("signal_text_idx") is not None else "")
            out.append(f"{i}. **{f['outlet']}** (`{f['bucket']}`): {f['finding']}{ref}")
        out.append("")

    # Bottom line
    out.append("## Bottom line")
    out.append("")
    out.append(a["bottom_line"])
    out.append("")

    # Footer
    out.append("---")
    out.append("")
    out.append(
        f"_Generated by `render_analysis_md.py` from "
        f"`analyses/{a['date']}_{a['story_key']}.json`. The JSON is the "
        f"canonical artifact; this markdown is a render._"
    )
    out.append("")

    return "\n".join(out)


def render_one(json_path: Path) -> Path:
    a = json.loads(json_path.read_text(encoding="utf-8"))
    md = render(a)
    md_path = json_path.with_suffix(".md")
    md_path.write_text(md, encoding="utf-8")
    return md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", type=Path,
                    help="Specific .json analysis files. Default: all for --date.")
    ap.add_argument("--date", default=None,
                    help="Date YYYY-MM-DD. Default: today UTC.")
    args = ap.parse_args()

    if args.files:
        targets = list(args.files)
    else:
        date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        targets = sorted(ANALYSES.glob(f"{date}_*.json"))
        if not targets:
            print(f"No JSON analyses found for {date}.")
            return 0

    # Phase 2 `<story>_headline.json` files are a separate-shape artifact
    # consumed by `analytical.headline_body_divergence`. They lack the fields
    # this renderer expects (story_title, event_summary). Skip them silently.
    targets = [t for t in targets if not t.stem.endswith("_headline")]
    if not targets:
        print("No primary analysis JSON files to render (only _headline.json present).")
        return 0

    for t in targets:
        if not t.exists():
            print(f"  skip: {t} not found", file=sys.stderr)
            continue
        if t.suffix != ".json":
            print(f"  skip: {t} is not .json", file=sys.stderr)
            continue
        out = render_one(t)
        print(f"  + {t.name:<48} -> {out.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
