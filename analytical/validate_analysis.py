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
   counts and fabricated jaccard scores.

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

from meta import REPO_ROOT as ROOT
ANALYSES = ROOT / "analyses"
BRIEFINGS = ROOT / "briefings"
SCHEMA_PATH = ROOT / "docs" / "api" / "schema" / "analysis.schema.json"


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
    """Return list of schema violation messages (empty = pass).

    Hard-requires jsonschema (declared in requirements.txt since
    Phase 3). The earlier soft-fail-on-import-error was dead defensive
    code once jsonschema became a pinned dependency.
    """
    import jsonschema  # ImportError = environment misconfiguration; bubble it.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    validator = jsonschema.Draft202012Validator(schema)
    for e in validator.iter_errors(analysis):
        path = ".".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"schema: {path}: {e.message}")
    return errors


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

    Both the claimed quote and the corpus signal_text are whitespace-
    normalised before the substring check so a stray newline or
    double-space in either side doesn't trigger a false positive.
    """
    errors: list[str] = []
    corpus = briefing.get("corpus", [])
    n = len(corpus)

    def _normalise_ws(s: str) -> str:
        return " ".join((s or "").split())

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
            if ev.get("bucket") and entry.get("bucket") != ev["bucket"]:
                errors.append(
                    f"citation: frames[{fi}].evidence[{ei}] claims bucket "
                    f"{ev['bucket']!r} but corpus[{idx}].bucket is "
                    f"{entry.get('bucket')!r}"
                )
            quote = _normalise_ws(ev.get("quote") or "")
            text = _normalise_ws(entry.get("signal_text") or "")
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
            if s.get("bucket") and entry.get("bucket") != s["bucket"]:
                errors.append(
                    f"citation: paradox.{side} claims bucket "
                    f"{s['bucket']!r} but corpus[{idx}].bucket is "
                    f"{entry.get('bucket')!r}"
                )
            quote = _normalise_ws(s.get("quote") or "")
            text = _normalise_ws(entry.get("signal_text") or "")
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
        if s.get("bucket") and entry.get("bucket") != s["bucket"]:
            errors.append(
                f"citation: single_outlet_findings[{si}] claims bucket "
                f"{s['bucket']!r} but corpus[{idx}].bucket is "
                f"{entry.get('bucket')!r}"
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

    # isolation_top mean_jaccard values must match metrics.isolation entries.
    metrics_iso = {r["bucket"]: r["mean_jaccard"]
                   for r in metrics.get("isolation") or []}
    for ii, r in enumerate(analysis.get("isolation_top") or []):
        b = r.get("bucket")
        v = r.get("mean_jaccard")
        if b not in metrics_iso:
            errors.append(
                f"numbers: isolation_top[{ii}].bucket {b!r} not in "
                f"metrics.isolation"
            )
            continue
        if v is not None and abs(metrics_iso[b] - v) > 1e-6:
            errors.append(
                f"numbers: isolation_top[{ii}] mean_jaccard {v} != "
                f"metrics value {metrics_iso[b]} for bucket {b!r}"
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
    errs.extend(check_citations(analysis, briefing))
    errs.extend(check_numbers(analysis, metrics))
    return (1 if errs else 0), errs


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
        rc, errs = validate_one(t)
        if rc == 0:
            print(f"  OK  {t.name}")
        else:
            print(f"  FAIL  {t.name}")
            for e in errs:
                print(f"    - {e}")
            total_errors += len(errs)

    if total_errors:
        print(f"\n{total_errors} validation error(s) across {len(targets)} file(s).")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
