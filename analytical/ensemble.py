"""analytical/ensemble.py — multi-LLM ensemble agreement on frame_id selections.

Re-runs the daily framing analysis through 2-3 raters and computes
Krippendorff's alpha on the closed-codebook `frame_id` selections. The
result is published as `analyses/<date>_<story>_ensemble.json` next to
the canonical analysis.

Raters (configurable; missing API keys gracefully drop the rater):
  - claude-sonnet-4-6 (the canonical analyzer; pinned snapshot)
  - claude-haiku-4-5  (cheap intra-family control for prompt sensitivity)
  - llama-3.3-70b-versatile via Groq (different family; controls for
    Anthropic-specific bias). Set GROQ_API_KEY to enable.

Publication policy (per remediation plan):
  alpha >= 0.6  → ship analysis as-is
  0.4 <= a < 0.6 → ship with `frame_agreement.preliminary = true`
  alpha < 0.4   → suppress frames with rater disagreement

Inputs:
  briefings/<date>_<story>.json
  briefings/<date>_<story>_metrics.json
  frames_codebook.json
Output:
  analyses/<date>_<story>_ensemble.json

Usage:
  python -m analytical.ensemble                    # all today's briefings
  python -m analytical.ensemble --date 2026-05-08  # specific date
  python -m analytical.ensemble briefings/<file>   # specific briefing
  python -m analytical.ensemble --dry-run          # report-only

Env:
  ANTHROPIC_API_KEY  required for the Anthropic raters.
  GROQ_API_KEY       optional. Adds Llama 3.3 70B as a third rater.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta
from analytical.krippendorff import alpha_nominal, agreement_summary

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"
ANALYSES = ROOT / "analyses"
CODEBOOK_PATH = ROOT / "frames_codebook.json"

ENSEMBLE = meta.META.get("ensemble") or {}
ALPHA_GATE_SHIP = float(ENSEMBLE.get("alpha_gate_ship", 0.6))
ALPHA_GATE_PRELIMINARY = float(ENSEMBLE.get("alpha_gate_preliminary", 0.4))
MAX_OUTPUT_TOKENS = int(ENSEMBLE.get("max_output_tokens", 1024))


# ---------------------------------------------------------------------------
# Codebook
# ---------------------------------------------------------------------------
def load_codebook() -> tuple[list[str], dict[str, str]]:
    """Returns (ordered_ids, id_to_definition)."""
    raw = json.loads(CODEBOOK_PATH.read_text(encoding="utf-8"))
    ids = [f["frame_id"] for f in raw["frames"]]
    defs = {f["frame_id"]: f["definition"] for f in raw["frames"]}
    return ids, defs


def codebook_prompt(briefing: dict, codebook_ids: list[str], codebook_defs: dict[str, str]) -> str:
    """Build a single-shot prompt asking a rater to label this corpus.

    The rater sees the briefing + codebook, returns ranked frame_id
    selections (no quotes — that's the canonical analysis's job; the
    ensemble's only job is agreement on the closed-taxonomy labels).
    """
    codebook_table = "\n".join(
        f"- `{fid}` — {codebook_defs[fid]}"
        for fid in codebook_ids
    )
    corpus_view = []
    for i, art in enumerate(briefing.get("corpus") or []):
        body = (
            (art.get("signal_text_en") or art.get("signal_text") or "")[:800]
        )
        title = art.get("title_en") or art.get("title") or ""
        corpus_view.append(
            f"[{i}] bucket={art.get('bucket')} outlet={art.get('feed')}\n"
            f"    title: {title}\n"
            f"    body: {body}"
        )
    corpus_text = "\n\n".join(corpus_view)

    return f"""You are rating a cross-country news corpus for **closed-taxonomy
framing**. You must select 2-8 frames carried by this corpus, drawn ONLY from
the codebook below. Your job is the LABEL, not the analysis — no quotes
required, no story-specific elaboration.

CODEBOOK (Boydstun/Card; closed taxonomy):
{codebook_table}

CORPUS for "{briefing.get('story_title', '')}":

{corpus_text}

Return STRICT JSON of this shape (no prose, no markdown fence):
{{"frames": [{{"frame_id": "ECONOMIC", "buckets": ["...", "..."]}}, ...]}}

Rules:
- Every `frame_id` MUST be one of the codebook IDs verbatim.
- Order the frames from most-prominent in the corpus to least.
- Use OTHER only when no codebook frame fits. Each frame must list at least one bucket.
- 2 to 8 frames total. No duplicates.
"""


# ---------------------------------------------------------------------------
# Raters
# ---------------------------------------------------------------------------
def _parse_frame_ids(text: str, valid_ids: set[str]) -> list[str]:
    """Extract frame_id list from rater output. Tolerant of code fences."""
    s = text.strip()
    # Strip common code fence patterns
    if s.startswith("```"):
        first_nl = s.find("\n")
        s = s[first_nl + 1 :] if first_nl != -1 else s[3:]
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        # Last-ditch: find the first '{' and last '}' and try again
        i, j = s.find("{"), s.rfind("}")
        if i == -1 or j == -1:
            return []
        try:
            obj = json.loads(s[i : j + 1])
        except json.JSONDecodeError:
            return []
    out: list[str] = []
    for f in obj.get("frames") or []:
        fid = f.get("frame_id")
        if fid in valid_ids and fid not in out:
            out.append(fid)
    return out


def rate_with_anthropic(
    model: str, prompt: str, valid_ids: set[str]
) -> list[str] | None:
    """Returns ordered frame_id list, or None if SDK/key missing or call fails."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    client = anthropic.Anthropic()
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return None
    parts: list[str] = []
    for block in msg.content:
        btype = getattr(block, "type", None)
        btext = getattr(block, "text", None)
        if btype == "text" and btext:
            parts.append(btext)
    return _parse_frame_ids("\n".join(parts), valid_ids)


def rate_with_groq(
    model: str, prompt: str, valid_ids: set[str]
) -> list[str] | None:
    """Llama 3.3 70B via Groq. None if SDK/key missing or call fails."""
    if not os.environ.get("GROQ_API_KEY"):
        return None
    try:
        from groq import Groq  # type: ignore
    except ImportError:
        return None
    client = Groq()
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return None
    text = resp.choices[0].message.content if resp.choices else ""
    return _parse_frame_ids(text or "", valid_ids)


def default_raters() -> list[dict]:
    """Standard rater suite. A rater is a dict {name, kind, model}."""
    raters = [
        {
            "name": "sonnet-4-6",
            "kind": "anthropic",
            "model": meta.CLAUDE.get("model", "claude-sonnet-4-6"),
        },
        {
            "name": "haiku-4-5",
            "kind": "anthropic",
            "model": ENSEMBLE.get("haiku_model", "claude-haiku-4-5-20251001"),
        },
    ]
    if os.environ.get("GROQ_API_KEY"):
        raters.append(
            {
                "name": "llama-3.3-70b-groq",
                "kind": "groq",
                "model": ENSEMBLE.get("groq_model", "llama-3.3-70b-versatile"),
            }
        )
    return raters


def call_rater(rater: dict, prompt: str, valid_ids: set[str]) -> list[str] | None:
    if rater["kind"] == "anthropic":
        return rate_with_anthropic(rater["model"], prompt, valid_ids)
    if rater["kind"] == "groq":
        return rate_with_groq(rater["model"], prompt, valid_ids)
    return None


# ---------------------------------------------------------------------------
# Per-briefing orchestration
# ---------------------------------------------------------------------------
def build_ensemble(
    briefing_path: Path,
    raters: list[dict] | None = None,
    rate_fn=call_rater,
    dry_run: bool = False,
) -> dict:
    """Run all raters, compute Krippendorff alpha, write ensemble JSON.

    `rate_fn` is injected so tests can stub the network calls.
    """
    briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
    codebook_ids, codebook_defs = load_codebook()
    valid_ids = set(codebook_ids)

    raters = raters if raters is not None else default_raters()
    prompt = codebook_prompt(briefing, codebook_ids, codebook_defs)

    rater_outputs: list[dict] = []
    for r in raters:
        if dry_run:
            rater_outputs.append({"rater": r["name"], "model": r["model"], "frames": None, "skipped": True})
            continue
        frames = rate_fn(r, prompt, valid_ids)
        rater_outputs.append({
            "rater": r["name"],
            "model": r["model"],
            "frames": frames,
            "skipped": frames is None,
        })

    # Build the per-frame rating matrix used for Krippendorff alpha.
    # Each "item" is one of the codebook IDs; each rater either picked it
    # (label = "PICKED") or did not pick it (label = "NOT_PICKED"). This
    # converts the unordered-set output into a categorical matrix that
    # nominal alpha can score.
    rating_matrix: list[list[str | None]] = []
    for fid in codebook_ids:
        item_row: list[str | None] = []
        for r in rater_outputs:
            if r.get("skipped") or r["frames"] is None:
                item_row.append(None)
            else:
                item_row.append("PICKED" if fid in r["frames"] else "NOT_PICKED")
        rating_matrix.append(item_row)

    summary = agreement_summary(rating_matrix)
    alpha = summary["alpha"]

    # Derive the consensus frame set: frames picked by >=2 raters (or by the
    # only rater with output, if alpha is undefined).
    active_raters = [r for r in rater_outputs if r.get("frames") is not None]
    if len(active_raters) == 0:
        consensus: list[str] = []
        gate = "no_raters"
    elif len(active_raters) == 1:
        consensus = list(active_raters[0]["frames"])
        gate = "single_rater"
    else:
        threshold = max(2, len(active_raters) // 2 + 1)  # majority
        pick_counts: dict[str, int] = {}
        for r in active_raters:
            for fid in r["frames"]:
                pick_counts[fid] = pick_counts.get(fid, 0) + 1
        consensus = [fid for fid, n in pick_counts.items() if n >= threshold]
        # Order consensus by mean rank across raters for stability.
        rank_sums: dict[str, float] = {fid: 0.0 for fid in consensus}
        rank_counts: dict[str, int] = {fid: 0 for fid in consensus}
        for r in active_raters:
            for i, fid in enumerate(r["frames"]):
                if fid in rank_sums:
                    rank_sums[fid] += i
                    rank_counts[fid] += 1
        consensus.sort(
            key=lambda fid: rank_sums[fid] / max(1, rank_counts[fid])
        )
        if alpha is None:
            gate = "alpha_undefined"
        elif alpha >= ALPHA_GATE_SHIP:
            gate = "ship"
        elif alpha >= ALPHA_GATE_PRELIMINARY:
            gate = "preliminary"
        else:
            gate = "suppress"

    artifact = meta.stamp({
        "date": briefing.get("date"),
        "story_key": briefing.get("story_key"),
        "story_title": briefing.get("story_title"),
        "raters": [
            {"rater": r["rater"], "model": r["model"], "skipped": r["skipped"]}
            for r in rater_outputs
        ],
        "rater_outputs": rater_outputs,
        "krippendorff_alpha": alpha,
        "alpha_gate_ship": ALPHA_GATE_SHIP,
        "alpha_gate_preliminary": ALPHA_GATE_PRELIMINARY,
        "gate": gate,
        "consensus_frame_ids": consensus,
        "agreement_summary": summary,
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    })

    out_path = ANALYSES / f"{briefing.get('date')}_{briefing.get('story_key')}_ensemble.json"
    if not dry_run:
        ANALYSES.mkdir(exist_ok=True)
        out_path.write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return artifact


def briefings_for_date(date: str, dir_: Path = BRIEFINGS) -> list[Path]:
    return sorted(
        p for p in dir_.glob(f"{date}_*.json") if not p.stem.endswith("_metrics")
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--date", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    targets = (
        list(args.files)
        if args.files
        else briefings_for_date(
            args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
    )
    if not targets:
        print(f"No briefings for {args.date or 'today'}")
        return 0

    raters = default_raters()
    print(f"Raters: {[r['name'] for r in raters]}")

    for t in targets:
        art = build_ensemble(t, raters=raters, dry_run=args.dry_run)
        a = art["krippendorff_alpha"]
        a_disp = f"{a:.3f}" if isinstance(a, float) else "n/a"
        print(
            f"  + {t.name:<48} alpha={a_disp} gate={art['gate']} "
            f"consensus={art['consensus_frame_ids']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
