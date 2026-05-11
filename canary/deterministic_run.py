"""Deterministic canary — Tier 1.

Catches code-drift bugs in the *deterministic* analytical pipeline:
silent refactor regressions in dedup, within_language_llr, or
within_language_pmi. No LLM calls, no embeddings — runs free of
external dependencies.

The expensive other half (4-pass LLM canary against the same corpus)
is designed in canary/ANALYTICAL_DESIGN.md and runs at ~$2.20 per
pin bump; this tier complements it for free.

Flow:
  1. Load canary/deterministic_corpus.json (fixed 16-article corpus
     across 4 buckets / 2 languages).
  2. Run pipeline.dedup.dedup_snapshot on the snapshot block.
  3. Run analytical.within_language_llr on the briefing block.
  4. Run analytical.within_language_pmi on the briefing block.
  5. Stamp the output bundle with meta_version + write to
     canary/deterministic_baseline/<meta_version>.json.
  6. If a prior baseline exists, diff structurally and report.

Failure modes the canary catches:
  - dedup logic change that alters intra-day duplicate counts
  - tokenizer / stopword change that shifts LLR scores
  - LLR / PMI formula refactor that produces different rankings
  - silent off-by-one / accumulator-init bugs in any of the above

Failure modes it does NOT catch:
  - LLM output drift (Tier 2 / canary/run.py covers that)
  - Embedding-dependent paths (build_metrics, clustering)

Usage:
  python -m canary.deterministic_run                  # run + diff vs prior
  python -m canary.deterministic_run --baseline-only  # write baseline; no diff
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import meta
from pipeline.dedup import dedup_snapshot
from analytical.within_language_llr import within_language_llr
from analytical.within_language_pmi import within_language_pmi

ROOT = meta.REPO_ROOT
CANARY = ROOT / "canary"
CORPUS = CANARY / "deterministic_corpus.json"
BASELINES = CANARY / "deterministic_baseline"


def _summarise_dedup(deduped: dict) -> dict:
    """Pluck the structural fields from dedup_snapshot's return dict.
    Excludes deduped_items[] (per-article payload — not load-bearing for
    drift detection, would just bloat the baseline)."""
    return {k: deduped.get(k) for k in (
        "n_url_dupes", "n_title_dupes", "n_cross_day_duplicates",
        "n_total_items", "n_deduped",
    )}


def _summarise_llr(llr_doc: dict) -> dict:
    """Reduce LLR output to a structural fingerprint: per-bucket top-3
    distinctive terms (deterministic-ranked) + total term counts."""
    out: dict = {}
    for bucket, payload in (llr_doc.get("by_bucket") or {}).items():
        top = (payload.get("distinctive_terms") or [])[:3]
        out[bucket] = {
            "lang": payload.get("lang"),
            "n_distinctive": len(payload.get("distinctive_terms") or []),
            "top3_terms": [t.get("term") for t in top],
        }
    return {"n_languages": llr_doc.get("n_languages", 0), "by_bucket": out}


def _summarise_pmi(pmi_doc: dict) -> dict:
    out: dict = {}
    for bucket, payload in (pmi_doc.get("by_bucket") or {}).items():
        top = (payload.get("distinctive_bigrams") or [])[:3]
        out[bucket] = {
            "lang": payload.get("lang"),
            "n_distinctive": len(payload.get("distinctive_bigrams") or []),
            "top3_bigrams": [list(t.get("bigram") or []) for t in top],
        }
    return {"n_languages": pmi_doc.get("n_languages", 0), "by_bucket": out}


def run_canary() -> dict:
    """Execute the deterministic pipeline once. Returns the stamped
    output bundle (not yet written)."""
    if not CORPUS.exists():
        raise FileNotFoundError(
            f"canary corpus missing at {CORPUS}; rebuild via "
            f"canary/_deterministic_corpus_builder.py")
    doc = json.loads(CORPUS.read_text(encoding="utf-8"))
    snapshot = doc["snapshot"]
    briefing = doc["briefing"]

    deduped = dedup_snapshot(snapshot)
    llr = within_language_llr(briefing)
    pmi = within_language_pmi(briefing)

    out = meta.stamp({
        "corpus_path": "canary/deterministic_corpus.json",
        "corpus_hash": _file_sha256(CORPUS),
        "dedup": _summarise_dedup(deduped),
        "llr": _summarise_llr(llr),
        "pmi": _summarise_pmi(pmi),
    })
    return out


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return "sha256:" + h.hexdigest()


def _structural_diff(prior: dict, current: dict) -> list[str]:
    """Walk both dicts and report structural differences. Returns a
    list of human-readable diff lines."""
    diffs: list[str] = []

    def walk(p, c, path: str = ""):
        if type(p) is not type(c):
            diffs.append(f"  {path}: type {type(p).__name__} -> {type(c).__name__}")
            return
        if isinstance(p, dict):
            for k in sorted(set(p) | set(c)):
                if k in {"meta_version", "pinned_at"}:
                    continue
                if k not in p:
                    diffs.append(f"  {path}.{k}: added")
                elif k not in c:
                    diffs.append(f"  {path}.{k}: removed")
                else:
                    walk(p[k], c[k], f"{path}.{k}")
        elif isinstance(p, list):
            if len(p) != len(c):
                diffs.append(f"  {path}: len {len(p)} -> {len(c)}")
            for i, (pi, ci) in enumerate(zip(p, c)):
                walk(pi, ci, f"{path}[{i}]")
        else:
            if p != c:
                diffs.append(f"  {path}: {p!r} -> {c!r}")

    walk(prior, current)
    return diffs


def _latest_baseline() -> Path | None:
    """Return the most recently bumped baseline (sorted by meta_version)."""
    if not BASELINES.is_dir():
        return None
    files = sorted(BASELINES.glob("*.json"))
    return files[-1] if files else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--baseline-only", action="store_true",
                    help="Write the baseline for current pin; skip diff.")
    args = ap.parse_args()

    out = run_canary()
    BASELINES.mkdir(parents=True, exist_ok=True)
    out_path = BASELINES / f"{meta.VERSION}.json"
    out_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path.relative_to(ROOT)}")
    if args.baseline_only:
        return 0

    # Diff against the prior baseline (if any).
    prior_path = _latest_baseline()
    if prior_path == out_path:
        # Look for the next-most-recent.
        siblings = [p for p in sorted(BASELINES.glob("*.json")) if p != out_path]
        prior_path = siblings[-1] if siblings else None
    if prior_path is None:
        print("(no prior baseline — first run)")
        return 0
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    diffs = _structural_diff(prior, out)
    print(f"\ndiff vs {prior_path.name}:")
    if not diffs:
        print("  (no structural change)")
    else:
        for line in diffs:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
