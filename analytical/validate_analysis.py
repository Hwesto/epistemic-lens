#!/usr/bin/env python3
"""validate_analysis.py — editorial checks on analysis JSON.

Phase 4: makes over-reach impossible by construction, not by prompt
discipline alone.

Three classes of check, in order of severity:

1. Schema validation (jsonschema) — cheap, catches malformed shape.
2. Citation grounding — every `signal_text_idx` referenced anywhere in
   the analysis must resolve to a real entry in the briefing's
   corpus[]. Catches hallucinated quotes / fabricated outlets.
3. Number reconciliation — every n_buckets, n_articles, isolation
   score, and bucket-exclusive vocab term referenced in the analysis
   must match the matching values in metrics.json. Catches inflated
   counts and fabricated similarity scores.

Exit non-zero on ANY violation, with a human-readable error per issue.
Designed to run as a pre-commit step (agent runs it before git commit)
AND as a post-hoc step in daily.yml (defense in depth).

Usage:
  python validate_analysis.py                          # all today's analyses
  python validate_analysis.py --date 2026-05-08        # specific date
  python validate_analysis.py analyses/<file>.json     # one file
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta
from meta import REPO_ROOT as ROOT
ANALYSES = ROOT / "analyses"
BRIEFINGS = ROOT / "briefings"
SCHEMA_PATH = ROOT / "docs" / "api" / "schema" / "analysis.schema.json"
CODEBOOK_PATH = ROOT / "frames_codebook.json"


def _codebook_ids() -> set[str]:
    """Closed taxonomy of valid frame_id values (Boydstun/Card)."""
    if not CODEBOOK_PATH.exists():
        return set()
    raw = json.loads(CODEBOOK_PATH.read_text(encoding="utf-8"))
    return {f["frame_id"] for f in raw.get("frames") or []}


class ValidationError(Exception):
    pass


def _load_briefing(date: str, story_key: str) -> dict:
    p = BRIEFINGS / f"{date}_{story_key}.json"
    if not p.exists():
        raise ValidationError(f"briefing missing: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _load_metrics(date: str, story_key: str) -> dict:
    p = BRIEFINGS / f"{date}_{story_key}_metrics.json"
    if not p.exists():
        raise ValidationError(f"metrics missing: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def check_schema(analysis: dict) -> list[str]:
    """Return list of schema violation messages (empty = pass)."""
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema not installed; cannot run schema check"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    validator = jsonschema.Draft202012Validator(schema)
    for e in validator.iter_errors(analysis):
        path = ".".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"schema: {path}: {e.message}")
    return errors


def _outlet_of(corpus_entry: dict | None) -> str | None:
    """Return the outlet (`feed`) name for a corpus entry, or None."""
    if not corpus_entry:
        return None
    feed = corpus_entry.get("feed")
    return feed if (feed and feed != "?") else None


WIRE_SYNDICATION_JACCARD = 0.6


def check_wire_syndication(analysis: dict, briefing: dict) -> list[str]:
    """Flag paradoxes where both quotes are wire-syndicated copy.

    If `paradox.a.signal_text` and `paradox.b.signal_text` share Jaccard ≥
    `WIRE_SYNDICATION_JACCARD` over the pinned tokeniser's tokens, the
    "opposing-bloc convergence" the paradox claims is actually two outlets
    publishing the same Reuters / AFP / AP wire copy verbatim. That's not
    a paradox — that's syndication. Caught the Virgin Mary RT↔SCMP case on
    May 12.
    """
    p = analysis.get("paradox") or {}
    corpus = briefing.get("corpus") or []
    if not p or "a" not in p or "b" not in p:
        return []
    idx_a = p.get("a", {}).get("signal_text_idx")
    idx_b = p.get("b", {}).get("signal_text_idx")
    if not (isinstance(idx_a, int) and isinstance(idx_b, int)):
        return []
    if not (0 <= idx_a < len(corpus) and 0 <= idx_b < len(corpus)):
        return []
    text_a = corpus[idx_a].get("signal_text") or ""
    text_b = corpus[idx_b].get("signal_text") or ""
    tokens_a = set(meta.tokenize(text_a))
    tokens_b = set(meta.tokenize(text_b))
    if not tokens_a or not tokens_b:
        return []
    overlap = len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))
    if overlap < WIRE_SYNDICATION_JACCARD:
        return []
    return [
        f"paradox: wire-syndicated copy (jaccard={overlap:.2f} >= "
        f"{WIRE_SYNDICATION_JACCARD:.2f}). The opposing-bloc 'convergence' "
        f"is two outlets republishing the same wire dispatch verbatim, "
        f"not a genuine paradox."
    ]


def _collect_signal_text_idxs(analysis: dict) -> list[tuple[str, int]]:
    """Yield (where, idx) pairs for every signal_text_idx in the analysis."""
    out: list[tuple[str, int]] = []
    for fi, f in enumerate(analysis.get("frames") or []):
        for ei, ev in enumerate(f.get("evidence") or []):
            if "signal_text_idx" in ev:
                out.append((f"frames[{fi}].evidence[{ei}]", ev["signal_text_idx"]))
    p = analysis.get("paradox")
    if p:
        for side in ("a", "b"):
            if "signal_text_idx" in p.get(side, {}):
                out.append((f"paradox.{side}", p[side]["signal_text_idx"]))
    for si, s in enumerate(analysis.get("single_outlet_findings") or []):
        if "signal_text_idx" in s:
            out.append((f"single_outlet_findings[{si}]", s["signal_text_idx"]))
    return out


def check_citations(analysis: dict, briefing: dict) -> list[str]:
    """Verify every signal_text_idx resolves AND quote substring matches.

    Side effect: when an `outlet` field is missing or '?' on an evidence /
    single_outlet_finding entry whose `signal_text_idx` points at a real
    corpus row, this fills it from `corpus[idx].feed` in-place. Catches the
    pre-meta-v7.4 pattern where the agent left outlet blank and downstream
    consumers rendered '?' to readers.
    """
    errors: list[str] = []
    corpus = briefing.get("corpus", [])
    n = len(corpus)

    # Every claimed bucket in evidence/paradox/findings must match the
    # corpus entry's bucket at that index. Prevents "I quoted Italy but
    # actually pointed at the USA entry."
    for fi, f in enumerate(analysis.get("frames") or []):
        for ei, ev in enumerate(f.get("evidence") or []):
            idx = ev.get("signal_text_idx")
            if idx is None:
                continue
            if not (0 <= idx < n):
                errors.append(
                    f"citation: frames[{fi}].evidence[{ei}].signal_text_idx={idx} "
                    f"out of range [0,{n})"
                )
                continue
            entry = corpus[idx]
            if not (ev.get("outlet") and ev["outlet"] != "?"):
                auto = _outlet_of(entry)
                if auto:
                    ev["outlet"] = auto
            if ev.get("bucket") and entry.get("bucket") != ev["bucket"]:
                errors.append(
                    f"citation: frames[{fi}].evidence[{ei}] claims bucket "
                    f"{ev['bucket']!r} but corpus[{idx}].bucket is "
                    f"{entry.get('bucket')!r}"
                )
            quote = (ev.get("quote") or "").strip()
            text = (entry.get("signal_text") or "")
            if quote and quote not in text:
                errors.append(
                    f"citation: frames[{fi}].evidence[{ei}] quote not found "
                    f"verbatim in corpus[{idx}].signal_text "
                    f"(quote={quote[:60]!r}...)"
                )

    p = analysis.get("paradox")
    if p:
        for side in ("a", "b"):
            s = p.get(side, {})
            idx = s.get("signal_text_idx")
            if idx is None:
                continue
            if not (0 <= idx < n):
                errors.append(
                    f"citation: paradox.{side}.signal_text_idx={idx} "
                    f"out of range [0,{n})"
                )
                continue
            entry = corpus[idx]
            if not (s.get("outlet") and s["outlet"] != "?"):
                auto = _outlet_of(entry)
                if auto:
                    s["outlet"] = auto
            if s.get("bucket") and entry.get("bucket") != s["bucket"]:
                errors.append(
                    f"citation: paradox.{side} claims bucket "
                    f"{s['bucket']!r} but corpus[{idx}].bucket is "
                    f"{entry.get('bucket')!r}"
                )
            quote = (s.get("quote") or "").strip()
            text = (entry.get("signal_text") or "")
            if quote and quote not in text:
                errors.append(
                    f"citation: paradox.{side} quote not found verbatim in "
                    f"corpus[{idx}].signal_text (quote={quote[:60]!r}...)"
                )

    for si, s in enumerate(analysis.get("single_outlet_findings") or []):
        idx = s.get("signal_text_idx")
        if idx is None:
            continue
        if not (0 <= idx < n):
            errors.append(
                f"citation: single_outlet_findings[{si}].signal_text_idx={idx} "
                f"out of range [0,{n})"
            )
            continue
        entry = corpus[idx]
        if not (s.get("outlet") and s["outlet"] != "?"):
            auto = _outlet_of(entry)
            if auto:
                s["outlet"] = auto
        if s.get("bucket") and entry.get("bucket") != s["bucket"]:
            errors.append(
                f"citation: single_outlet_findings[{si}] claims bucket "
                f"{s['bucket']!r} but corpus[{idx}].bucket is "
                f"{entry.get('bucket')!r}"
            )

    return errors


def check_codebook(analysis: dict) -> list[str]:
    """Every frame must use a frame_id from frames_codebook.json (Boydstun/Card).

    Schema enum already enforces this at the JSON-schema layer; this check
    produces a clearer error message and additionally requires that frames
    using `frame_id == 'OTHER'` carry a non-empty `sub_frame`, since OTHER
    is meant as an escape hatch with explicit justification.
    """
    errors: list[str] = []
    valid = _codebook_ids()
    if not valid:
        errors.append(
            "codebook: frames_codebook.json missing or empty — cannot validate frame_id"
        )
        return errors
    for fi, f in enumerate(analysis.get("frames") or []):
        fid = f.get("frame_id")
        if not fid:
            errors.append(f"codebook: frames[{fi}] missing required frame_id")
            continue
        if fid not in valid:
            errors.append(
                f"codebook: frames[{fi}].frame_id {fid!r} not in codebook "
                f"(valid: {sorted(valid)})"
            )
            continue
        if fid == "OTHER" and not (f.get("sub_frame") or "").strip():
            errors.append(
                f"codebook: frames[{fi}].frame_id is OTHER but sub_frame is "
                f"empty — OTHER requires a sub_frame justification"
            )
    return errors


def check_numbers(analysis: dict, metrics: dict) -> list[str]:
    """Reconcile n_buckets, n_articles, isolation values against metrics."""
    errors: list[str] = []

    # n_buckets / n_articles must match metrics.
    if analysis.get("n_buckets") != metrics.get("n_buckets"):
        errors.append(
            f"numbers: n_buckets {analysis.get('n_buckets')} != "
            f"metrics.n_buckets {metrics.get('n_buckets')}"
        )
    if analysis.get("n_articles") != metrics.get("n_articles"):
        errors.append(
            f"numbers: n_articles {analysis.get('n_articles')} != "
            f"metrics.n_articles {metrics.get('n_articles')}"
        )

    # isolation_top values must match metrics.isolation (LaBSE cosine, primary).
    metrics_iso_primary = {
        r["bucket"]: r["mean_similarity"] for r in metrics.get("isolation") or []
    }
    for ii, r in enumerate(analysis.get("isolation_top") or []):
        b = r.get("bucket")
        if b not in metrics_iso_primary:
            errors.append(
                f"numbers: isolation_top[{ii}].bucket {b!r} not in "
                f"metrics.isolation"
            )
            continue
        v = r.get("mean_similarity")
        if v is not None and abs(metrics_iso_primary[b] - v) > 1e-6:
            errors.append(
                f"numbers: isolation_top[{ii}].mean_similarity {v} != "
                f"metrics value {metrics_iso_primary[b]} for bucket {b!r}"
            )

    # exclusive_vocab terms claimed must appear in metrics.bucket_exclusive_vocab.
    metrics_excl = metrics.get("bucket_exclusive_vocab") or {}
    for hi, h in enumerate(analysis.get("exclusive_vocab_highlights") or []):
        b = h.get("bucket")
        if b not in metrics_excl:
            errors.append(
                f"numbers: exclusive_vocab_highlights[{hi}].bucket {b!r} not in "
                f"metrics.bucket_exclusive_vocab"
            )
            continue
        metric_terms = {e["term"] for e in metrics_excl[b]}
        for ti, t in enumerate(h.get("terms") or []):
            if t not in metric_terms:
                errors.append(
                    f"numbers: exclusive_vocab_highlights[{hi}].terms[{ti}] "
                    f"{t!r} claimed exclusive to {b!r} but not in "
                    f"metrics.bucket_exclusive_vocab[{b!r}]"
                )

    return errors


def validate_one(analysis_path: Path) -> tuple[int, list[str]]:
    """Returns (exit_code, errors). 0 = clean."""
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

    schema_errs = check_schema(analysis)
    if schema_errs:
        # Schema fail: don't bother with downstream checks.
        return 1, schema_errs

    date = analysis["date"]
    story_key = analysis["story_key"]

    try:
        briefing = _load_briefing(date, story_key)
    except ValidationError as e:
        return 1, [str(e)]
    try:
        metrics = _load_metrics(date, story_key)
    except ValidationError as e:
        return 1, [str(e)]

    errs: list[str] = []
    errs.extend(check_codebook(analysis))
    errs.extend(check_citations(analysis, briefing))
    errs.extend(check_wire_syndication(analysis, briefing))
    errs.extend(check_numbers(analysis, metrics))
    return (1 if errs else 0), errs


def check_quote_grounding_sources(
    sources_doc: dict, briefing: dict
) -> list[str]:
    """Phase 3a: parallel-validate source-attribution JSON.

    Each `sources[i].exact_quote` must appear verbatim in the article it's
    attributed to (`corpus[signal_text_idx].signal_text`). The bucket field
    must match. Catches hallucinated quotes the same way the body validator
    does.

    Defers schema validity to the producer (the source-attribution agent
    runs its own self-check); this is defence in depth at validate time.
    """
    errors: list[str] = []
    sources = sources_doc.get("sources") or []
    corpus = briefing.get("corpus") or []
    n_articles = len(corpus)
    for ii, s in enumerate(sources):
        idx = s.get("signal_text_idx")
        if not isinstance(idx, int) or idx < 0 or idx >= n_articles:
            errors.append(
                f"sources[{ii}]: signal_text_idx {idx} out of range "
                f"(corpus length {n_articles})"
            )
            continue
        article = corpus[idx]
        quote = (s.get("exact_quote") or "").strip()
        text = article.get("signal_text") or ""
        if quote and quote not in text:
            errors.append(
                f"sources[{ii}]: quote not found verbatim in "
                f"corpus[{idx}].signal_text — {quote[:60]!r}"
            )
        if s.get("bucket") != article.get("bucket"):
            errors.append(
                f"sources[{ii}]: claims bucket {s.get('bucket')!r} but "
                f"corpus[{idx}].bucket = {article.get('bucket')!r}"
            )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    targets = list(args.files) if args.files else sorted(
        ANALYSES.glob(f"{args.date or datetime.now(timezone.utc).strftime('%Y-%m-%d')}_*.json")
    )
    if not targets:
        print("No analyses to validate.")
        return 0

    total_errors = 0
    for t in targets:
        if t.suffix != ".json":
            continue
        # Skip Phase 2 sibling artefacts (headline, divergence) — they
        # share the analysis schema but are validated elsewhere.
        if t.stem.endswith(("_headline", "_divergence")):
            continue
        rc, errs = validate_one(t)
        if rc == 0:
            print(f"  OK  {t.name}")
        else:
            print(f"  FAIL  {t.name}")
            for e in errs:
                print(f"    - {e}")
            total_errors += len(errs)

    # Phase 3a: parallel-validate source-attribution outputs.
    SOURCES = ROOT / "sources"
    if SOURCES.exists():
        date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for sp in sorted(SOURCES.glob(f"{date}_*.json")):
            if sp.parent.name == "aggregate":
                continue
            try:
                sd = json.loads(sp.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  FAIL  {sp.name}: {e}")
                total_errors += 1
                continue
            story_key = sd.get("story_key")
            try:
                briefing = _load_briefing(date, story_key)
            except ValidationError as e:
                print(f"  FAIL  {sp.name}: {e}")
                total_errors += 1
                continue
            errs = check_quote_grounding_sources(sd, briefing)
            if errs:
                print(f"  FAIL  {sp.name}")
                for e in errs:
                    print(f"    - {e}")
                total_errors += len(errs)
            else:
                print(f"  OK    {sp.name}  ({len(sd.get('sources') or [])} sources)")

    if total_errors:
        print(f"\n{total_errors} validation error(s).")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
