"""canary/run.py — drift canary for the daily Claude analyzer.

Runs eight frozen (article, instruction) pairs (canary/prompts.json) through
the pinned analyzer model on every daily cron. Logs raw JSON outputs to
canary/results/<date>.json. Compares today's outputs to canary/baseline/*.json
via:

  1. **Categorical agreement** — does the model still pick the same
     primary_frame as the baseline run? Reported as exact-match rate.
  2. **Embedding similarity** — for prose continuity, embed each output
     and compare cosine to baseline. Mean similarity should stay > 0.92.

If either gate trips, the workflow step writes a warning into the job
summary. It does NOT fail the workflow — drift is not a defect, it's a
signal to review. Repeated drift means the snapshot ID Anthropic served
yesterday is no longer the snapshot they're serving today; the snapshot
pin needs review.

First run: if no baseline exists, today's run becomes the baseline.

Usage:
  python -m canary.run                  # run + write results + diff vs baseline
  python -m canary.run --baseline       # treat today's run as the new baseline
  python -m canary.run --dry-run        # report counts; no API calls
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
CANARY = ROOT / "canary"
PROMPTS_PATH = CANARY / "prompts.json"
BASELINE_DIR = CANARY / "baseline"
RESULTS_DIR = CANARY / "results"

CATEGORICAL_GATE = 0.75   # < 75% primary_frame match → warn
EMBEDDING_GATE = 0.92     # < 0.92 mean cosine → warn
MAX_OUTPUT_TOKENS = 256


def _client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    return anthropic.Anthropic()


def _model() -> str:
    return meta.CLAUDE.get("model", "claude-sonnet-4-6")


def _parse(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        s = s[nl + 1 :] if nl != -1 else s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        i, j = s.find("{"), s.rfind("}")
        if i == -1 or j == -1:
            return {}
        try:
            return json.loads(s[i : j + 1])
        except json.JSONDecodeError:
            return {}


def run_one(client, item: dict) -> dict:
    """Run one canary item through the analyzer; return the output record."""
    prompt = item["article"] + "\n\n" + item["instruction"]
    try:
        msg = client.messages.create(
            model=_model(),
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        return {
            "id": item["id"],
            "ok": False,
            "error": str(e)[:200],
            "primary_frame": None,
            "secondary_frame": None,
            "raw_text": "",
        }
    parts: list[str] = []
    for block in msg.content:
        btype = getattr(block, "type", None)
        btext = getattr(block, "text", None)
        if btype == "text" and btext:
            parts.append(btext)
    raw = "\n".join(parts).strip()
    parsed = _parse(raw)
    return {
        "id": item["id"],
        "ok": True,
        "primary_frame": parsed.get("primary_frame"),
        "secondary_frame": parsed.get("secondary_frame"),
        "raw_text": raw,
    }


def cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n])) or 1.0
    nb = math.sqrt(sum(x * x for x in b[:n])) or 1.0
    return dot / (na * nb)


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embed a batch via the project's pinned multilingual model.

    Returns None if sentence-transformers is unavailable or the model isn't
    cached locally; the caller falls back to categorical-only diff.
    """
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError:
        return None
    try:
        model = SentenceTransformer(meta.EMBEDDING["model"])
    except Exception:
        return None
    return [list(map(float, v)) for v in model.encode(texts, batch_size=8)]


def diff_vs_baseline(today: list[dict], baseline: list[dict]) -> dict:
    """Compute categorical-match and (optionally) embedding-cosine drift."""
    by_id_baseline = {r["id"]: r for r in baseline}
    matched = 0
    total = 0
    per_item: list[dict] = []
    for r in today:
        b = by_id_baseline.get(r["id"])
        if not b:
            continue
        total += 1
        match = (
            r.get("primary_frame")
            and r.get("primary_frame") == b.get("primary_frame")
        )
        if match:
            matched += 1
        per_item.append({
            "id": r["id"],
            "today_primary": r.get("primary_frame"),
            "baseline_primary": b.get("primary_frame"),
            "match": bool(match),
        })
    cat_rate = matched / total if total else None

    # Embedding cosine over raw_text. Skipped silently if model unavailable.
    embeddings = embed_texts(
        [r["raw_text"] for r in today] + [by_id_baseline[r["id"]]["raw_text"] for r in today]
    )
    mean_cos = None
    if embeddings is not None and len(embeddings) >= 2 * len(today) and len(today) > 0:
        n = len(today)
        sims = [cosine(embeddings[i], embeddings[n + i]) for i in range(n)]
        mean_cos = sum(sims) / len(sims) if sims else None

    drift_warnings: list[str] = []
    if cat_rate is not None and cat_rate < CATEGORICAL_GATE:
        drift_warnings.append(
            f"categorical primary_frame match rate {cat_rate:.2f} < {CATEGORICAL_GATE} gate"
        )
    if mean_cos is not None and mean_cos < EMBEDDING_GATE:
        drift_warnings.append(
            f"mean output cosine {mean_cos:.3f} < {EMBEDDING_GATE} gate"
        )

    return {
        "categorical_match_rate": cat_rate,
        "mean_embedding_cosine": mean_cos,
        "n_items": total,
        "drift_warnings": drift_warnings,
        "per_item": per_item,
    }


def latest_baseline_path(base_dir: Path = BASELINE_DIR) -> Path | None:
    if not base_dir.exists():
        return None
    files = sorted(p for p in base_dir.glob("*.json"))
    return files[-1] if files else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--baseline",
        action="store_true",
        help="Promote today's run to canary/baseline/<date>.json (also writes results).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip API calls; report what would happen.",
    )
    args = ap.parse_args()

    if not PROMPTS_PATH.exists():
        print(f"missing canary prompts at {PROMPTS_PATH}", file=sys.stderr)
        return 1
    items = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))["items"]

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print(f"DRY RUN: would call {len(items)} canary items against {_model()}")
        return 0

    client = _client()
    if client is None:
        print(
            "WARN: ANTHROPIC_API_KEY missing or anthropic SDK not installed. "
            "Skipping canary.",
            file=sys.stderr,
        )
        return 0

    today = [run_one(client, item) for item in items]
    record = {
        "date": today_iso,
        "model": _model(),
        "n_items": len(items),
        "results": today,
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    record = meta.stamp(record)

    out_results = RESULTS_DIR / f"{today_iso}.json"
    out_results.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"results -> {out_results}")

    baseline_path = latest_baseline_path()
    if args.baseline or baseline_path is None:
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        out_baseline = BASELINE_DIR / f"{today_iso}.json"
        out_baseline.write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"baseline -> {out_baseline}")
        return 0

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["results"]
    diff = diff_vs_baseline(today, baseline)

    print()
    print(f"Drift vs {baseline_path.name}:")
    print(f"  categorical match rate: {diff['categorical_match_rate']}")
    print(f"  mean output cosine:     {diff['mean_embedding_cosine']}")
    if diff["drift_warnings"]:
        print()
        print("  WARNINGS:")
        for w in diff["drift_warnings"]:
            print(f"    - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
