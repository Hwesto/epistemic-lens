"""analytical/auto_promote.py — auto-promote emerging stories to canonical patterns.

Reads the last 7 days of snapshots in `snapshots/`, runs the existing
`build_briefing.find_emerging_stories` token-frequency detector against each,
and tracks which tokens persist across days. Tokens that appear in the
emerging-stories list ≥3 of 7 days are reported as **promotion candidates**.

Default policy is **report-only**: candidates land in
`archive/auto_promoted_<date>.md` for human review. The user (or follow-up
agent) decides whether to manually edit `canonical_stories.json` to promote a
candidate. Auto-promotion that silently mutates pinned methodology inputs is
out of scope — promotion bumps the methodology pin (minor for additive,
major if patterns are revised) and that decision should be conscious.

Usage:
  python -m core.cluster.auto_promote                    # 7-day window ending today
  python -m core.cluster.auto_promote --window 14        # different window
  python -m core.cluster.auto_promote --threshold 4      # stricter persistence
  python -m core.cluster.auto_promote --json             # machine-readable output
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import core.meta as meta
from core.briefing.build import find_emerging_stories

ROOT = meta.REPO_ROOT
SNAPSHOTS = ROOT / "snapshots"
ARCHIVE = ROOT / "archive"

DEFAULT_WINDOW_DAYS = 7
DEFAULT_PERSISTENCE = 3  # token must appear on >= N of WINDOW days
DEFAULT_MIN_BUCKETS = 4  # passed through to find_emerging_stories per day


def existing_canonical_tokens() -> set[str]:
    """Tokens that already appear in canonical_stories.json patterns.

    Used to filter candidates: if a token is already implicitly captured by
    an existing pattern, promoting it again would just spam the candidate
    report. Strips regex metacharacters (\\b, character classes, .{0,N})
    before tokenizing so word boundaries don't inflate to spurious "b"
    prefixes (e.g. \\bhormuz\\b would otherwise yield 'bhormuzb').
    """
    out: set[str] = set()
    for s in meta.canonical_stories().values():
        for p in s.get("patterns", []):
            # Strip backslash-escapes (\b, \w, \d, \s, etc.) and quantifier
            # blocks ".{0,40}" — anything regex-syntactic that doesn't carry
            # natural-language semantics.
            cleaned = re.sub(r"\\[a-zA-Z]", " ", p)
            cleaned = re.sub(r"\.\{[\d,]*\}", " ", cleaned)
            cleaned = re.sub(r"[\\^$.|?*+()\[\]{}]", " ", cleaned)
            for tok in re.findall(r"[a-z]{4,}", cleaned.lower()):
                out.add(tok)
    return out


def load_snapshot(date: str) -> dict | None:
    p = SNAPSHOTS / f"{date}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def detect_persistent_tokens(
    end_date: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    persistence: int = DEFAULT_PERSISTENCE,
    min_buckets: int = DEFAULT_MIN_BUCKETS,
) -> list[dict]:
    """Find tokens that recur across the window.

    Returns a list of {token, days_seen, mean_buckets, sample_dates,
    sample_buckets} sorted by (days_seen DESC, mean_buckets DESC).
    """
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    canonical = existing_canonical_tokens()
    per_day: dict[str, dict[str, set[str]]] = {}  # token -> date -> bucket set

    for d in range(window_days):
        date = (end - timedelta(days=d)).isoformat()
        snap = load_snapshot(date)
        if snap is None:
            continue
        emerging = find_emerging_stories(snap, min_buckets=min_buckets)
        for tok, buckets in emerging:
            if tok in canonical:
                continue
            per_day.setdefault(tok, {})[date] = buckets

    candidates: list[dict] = []
    for tok, dates in per_day.items():
        if len(dates) < persistence:
            continue
        all_buckets: set[str] = set()
        for s in dates.values():
            all_buckets |= s
        candidates.append({
            "token": tok,
            "days_seen": len(dates),
            "mean_buckets": round(
                sum(len(b) for b in dates.values()) / len(dates), 2
            ),
            "sample_dates": sorted(dates.keys()),
            "sample_buckets": sorted(all_buckets),
        })
    candidates.sort(key=lambda r: (-r["days_seen"], -r["mean_buckets"]))
    return candidates


def load_lineage_candidates(end_date: str) -> list[dict]:
    """PR2 Phase C: read archive/persistent_residual_<end_date>.json
    (written by analytical.persistence_tracker) and filter to lineages
    that meet the promotion gate (≥3 days, ≥4 buckets). Returns [] if
    the file doesn't exist (persistence_tracker hasn't run yet)."""
    p = ARCHIVE / f"persistent_residual_{end_date}.json"
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for L in (doc.get("lineages") or []):
        if L.get("day_count", 0) >= 3 and L.get("n_buckets_union", 0) >= 4:
            out.append(L)
    return out


def render_markdown(
    candidates: list[dict],
    end_date: str,
    window_days: int,
    persistence: int,
    lineage_candidates: list[dict] | None = None,
) -> str:
    out: list[str] = []
    out.append(f"# Auto-promote candidates — {end_date}")
    out.append("")
    out.append(
        f"Window: {window_days} days ending {end_date}. "
        f"Persistence threshold: token must appear on at least {persistence} "
        f"days. Tokens already implicit in canonical_stories.json are filtered."
    )
    out.append("")
    out.append(f"**Pin:** `meta_version {meta.VERSION}`")
    out.append("")
    if not candidates:
        out.append("_No candidates met the persistence threshold this window._")
        out.append("")
        out.append(
            "This is expected if the canonical base already covers most "
            "long-running stories. Lower `--threshold` if you want a wider net."
        )
        return "\n".join(out)
    out.append("## How to promote")
    out.append("")
    out.append(
        "1. Pick a candidate below that maps to a real, ongoing story."
    )
    out.append(
        "2. Hand-write 3-5 specific regex patterns for `canonical_stories.json` "
        "that capture the story (not just the token). Multi-token patterns "
        "are stronger than single-token ones — the auto-promote token is "
        "only the *signal* that something is recurring."
    )
    out.append(
        "3. Add a new entry under `stories` with `tier: \"long_running\"`."
    )
    out.append(
        "4. Bump pin: `python baseline_pin.py --bump minor --reason 'added "
        "<story_key> from auto-promote'`."
    )
    out.append("")
    # PR2 Phase C: lineage candidates first (embedding-based; stronger
    # signal than the token detector since it operates on the residual
    # AFTER perception assignment, so canonical-covered stories don't
    # crowd out emerging ones).
    lineage_file = ARCHIVE / f"persistent_residual_{end_date}.json"
    if not lineage_file.exists():
        out.append("## Lineage candidates (PR2 Phase C — embedding residual)")
        out.append("")
        out.append(
            f"_persistence_tracker hasn't run yet for `{end_date}` — no "
            "lineage candidates available. Expected on the first week after "
            "deploying Phase C, or when the weekly cron hasn't fired since "
            "the daily cron started writing residual_clusters.json. Token "
            "candidates below are unaffected._"
        )
        out.append("")
    elif not lineage_candidates:
        out.append("## Lineage candidates (PR2 Phase C — embedding residual)")
        out.append("")
        out.append(
            "_persistence_tracker ran but no lineages met the promotion gate "
            "(>=3 days, >=4 buckets). Either the residual pool is genuinely "
            "stable (canonical set covers everything) or the window is still "
            "ramping up after deployment._"
        )
        out.append("")
    elif lineage_candidates:
        out.append("## Lineage candidates (PR2 Phase C — embedding residual)")
        out.append("")
        out.append(
            "These lineages persisted ≥3 days with ≥4 distinct buckets in the "
            "residual cluster pool (articles the perception layer left "
            "unassigned to a canonical story). The same article-set re-clusters "
            "day-over-day → real story, not a one-day spike."
        )
        out.append("")
        out.append(
            "| Lineage | Days | Buckets | Consensus tokens | Sample buckets |"
        )
        out.append("|---|---:|---:|---|---|")
        for L in lineage_candidates[:20]:
            tokens = ", ".join(L.get("consensus_tokens", [])[:6])
            buckets = ", ".join(L.get("buckets_seen", [])[:6])
            if len(L.get("buckets_seen", [])) > 6:
                buckets += "…"
            out.append(
                f"| `{L['lineage_id']}` | {L['day_count']} "
                f"| {L['n_buckets_union']} | {tokens} | {buckets} |"
            )
        out.append("")
        out.append(
            "Inspect a lineage's articles via "
            "`jq '.lineages[] | select(.lineage_id==\"…\") | .latest_member_ids' "
            f"archive/persistent_residual_{end_date}.json`."
        )
        out.append("")

    out.append("## Token candidates (legacy detector)")
    out.append("")
    out.append("| Token | Days | Mean buckets | Sample dates | Sample buckets |")
    out.append("|---|---:|---:|---|---|")
    for c in candidates[:30]:
        out.append(
            f"| `{c['token']}` | {c['days_seen']} | {c['mean_buckets']} "
            f"| {', '.join(c['sample_dates'][:3])}{'…' if len(c['sample_dates']) > 3 else ''} "
            f"| {', '.join(c['sample_buckets'][:5])}{'…' if len(c['sample_buckets']) > 5 else ''} |"
        )
    out.append("")
    out.append(
        "_Generated by `analytical/auto_promote.py`. Report-only by design — "
        "no canonical_stories.json or meta_version.json was modified._"
    )
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--end",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="End-of-window date (YYYY-MM-DD). Default: today UTC.",
    )
    ap.add_argument(
        "--window", type=int, default=DEFAULT_WINDOW_DAYS,
        help=f"Window length in days. Default: {DEFAULT_WINDOW_DAYS}.",
    )
    ap.add_argument(
        "--threshold", type=int, default=DEFAULT_PERSISTENCE,
        help=f"Token must appear on >= N days. Default: {DEFAULT_PERSISTENCE}.",
    )
    ap.add_argument(
        "--min-buckets", type=int, default=DEFAULT_MIN_BUCKETS,
        help=f"Min buckets for find_emerging_stories per day. Default: {DEFAULT_MIN_BUCKETS}.",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON, not Markdown.")
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output file. Default: archive/auto_promoted_<end>.md (or .json).",
    )
    args = ap.parse_args()

    candidates = detect_persistent_tokens(
        args.end, args.window, args.threshold, args.min_buckets
    )
    # PR2 Phase C: also surface lineage candidates from
    # analytical/persistence_tracker.py output (if present).
    lineage_cands = load_lineage_candidates(args.end)

    if args.json:
        body = json.dumps(
            {
                "end_date": args.end,
                "window_days": args.window,
                "persistence_threshold": args.threshold,
                "meta_version": meta.VERSION,
                "token_candidates": candidates,
                "lineage_candidates": lineage_cands,
            },
            indent=2,
            ensure_ascii=False,
        )
        suffix = ".json"
    else:
        body = render_markdown(candidates, args.end, args.window,
                                 args.threshold,
                                 lineage_candidates=lineage_cands)
        suffix = ".md"

    out_path = args.out or (ARCHIVE / f"auto_promoted_{args.end}{suffix}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"Wrote {out_path}: {len(candidates)} token candidate(s), "
          f"{len(lineage_cands)} lineage candidate(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
