#!/usr/bin/env python3
"""render_thread.py — template-based thread draft from a JSON analysis.

Phase 3: drafts that don't need free-form prose are deterministic
templates over the canonical analysis JSON. No LLM call.

For each `analyses/<DATE>_<story_key>.json`, produces
`drafts/<DATE>_<story_key>_thread.json` conforming to
`docs/api/schema/thread.schema.json`.

Hook selection (priority order):
  1. Paradox (opposing blocs converging) — strongest signal
  2. Isolation outlier (one bucket sharply distinct)
  3. Bucket-exclusive vocab (a frame nobody else carries)
  4. Generic structural ("N buckets, M frames")

Each tweet that quotes or cites a corpus entry includes a `sources`
array with the bucket + briefing-corpus URL + outlet name. URLs come
from `briefings/<DATE>_<story_key>.json` corpus[idx].link, looked up
by the `signal_text_idx` field in the analysis evidence.

Usage:
  python render_thread.py                          # all today's analyses
  python render_thread.py --date 2026-05-08
  python render_thread.py analyses/<file>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = Path(__file__).parent
ANALYSES = ROOT / "analyses"
BRIEFINGS = ROOT / "briefings"
DRAFTS = ROOT / "drafts"
SCHEMA_PATH = ROOT / "docs" / "api" / "schema" / "thread.schema.json"

MAX_TWEET_CHARS = 280
MAX_HOOK_CHARS = 240


def _load_briefing(date: str, story_key: str) -> dict:
    p = BRIEFINGS / f"{date}_{story_key}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _corpus_source(briefing: dict, idx: int) -> dict | None:
    """Return {bucket, url, outlet} for briefing.corpus[idx], or None."""
    corpus = briefing.get("corpus", [])
    if 0 <= idx < len(corpus):
        e = corpus[idx]
        url = e.get("link") or ""
        if not url:
            return None
        return {"bucket": e.get("bucket", ""), "url": url, "outlet": e.get("feed", "")}
    return None


def _truncate(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _build_hook(a: dict) -> str:
    """Pick the strongest finding for the lead tweet."""
    # 1. Paradox — opposite-bloc convergence
    p = a.get("paradox")
    if p:
        ab = f"{p['a']['outlet']} and {p['b']['outlet']}"
        return _truncate(
            f"{ab} — opposite political universes — both said the same thing about "
            f"{a['story_title']}. Nobody else did.",
            MAX_HOOK_CHARS,
        )

    # 2. Isolation outlier — one bucket sharply distinct
    iso = a.get("isolation_top") or []
    if iso and iso[0].get("mean_jaccard", 1) < 0.05:
        b = iso[0]["bucket"]
        return _truncate(
            f"{a['n_buckets']} outlets covered {a['story_title']}. "
            f"`{b}` used totally different words.",
            MAX_HOOK_CHARS,
        )

    # 3. Bucket-exclusive vocab — a frame nobody else carries
    excl = a.get("exclusive_vocab_highlights") or []
    if excl:
        h = excl[0]
        terms = ", ".join(f"\"{t}\"" for t in h["terms"][:3])
        return _truncate(
            f"On {a['story_title']}, only `{h['bucket']}` used: {terms}. "
            f"That changes the story.",
            MAX_HOOK_CHARS,
        )

    # 4. Generic structural
    nf = len(a.get("frames") or [])
    return _truncate(
        f"{a['n_buckets']} outlets covered {a['story_title']}. "
        f"{nf} distinct frames. Here's what that means.",
        MAX_HOOK_CHARS,
    )


def _frame_tweet(frame: dict, briefing: dict) -> dict | None:
    """One tweet per frame — label + bucket count + first quote, with source."""
    if not frame.get("evidence"):
        return None
    ev = frame["evidence"][0]
    source = _corpus_source(briefing, ev["signal_text_idx"])
    n_b = len(frame.get("buckets", []))
    plural = "s" if n_b != 1 else ""
    text = _truncate(
        f"Frame: {frame['label']} ({n_b} bucket{plural}). "
        f"\"{_truncate(ev['quote'], 140)}\" — {ev.get('outlet') or ev['bucket']}",
        MAX_TWEET_CHARS,
    )
    out: dict = {"text": text}
    if source:
        out["sources"] = [source]
    return out


def _paradox_tweet(p: dict, briefing: dict) -> dict:
    sa = _corpus_source(briefing, p["a"]["signal_text_idx"])
    sb = _corpus_source(briefing, p["b"]["signal_text_idx"])
    text = _truncate(
        f"The paradox: {p['joint_conclusion']} "
        f"({p['a']['outlet']} & {p['b']['outlet']}, opposite blocs.)",
        MAX_TWEET_CHARS,
    )
    sources = [s for s in (sa, sb) if s]
    out: dict = {"text": text}
    if sources:
        out["sources"] = sources
    return out


def _silence_tweet(silences: list) -> dict | None:
    if not silences:
        return None
    s = silences[0]
    return {
        "text": _truncate(
            f"Silence as data: `{s['bucket']}` didn't cover this — "
            f"they covered {s['what_they_covered_instead']} instead.",
            MAX_TWEET_CHARS,
        )
    }


def _structural_tweet(a: dict) -> dict:
    return {
        "text": _truncate(
            f"{a['n_buckets']} buckets, {a['n_articles']} articles, "
            f"{len(a.get('frames') or [])} distinct frames in today's coverage.",
            MAX_TWEET_CHARS,
        )
    }


def _outlet_finding_tweet(findings: list, briefing: dict) -> dict | None:
    if not findings:
        return None
    f = findings[0]
    text = _truncate(f"**{f['outlet']}** ({f['bucket']}): {f['finding']}", MAX_TWEET_CHARS)
    out: dict = {"text": text}
    if f.get("signal_text_idx") is not None:
        s = _corpus_source(briefing, f["signal_text_idx"])
        if s:
            out["sources"] = [s]
    return out


def render(a: dict, briefing: dict) -> dict:
    """Analysis JSON + briefing JSON → thread draft JSON."""
    hook = _build_hook(a)

    tweets: list[dict] = [_structural_tweet(a)]

    # Up to 4 frame tweets — most-buckets-first
    frames = sorted(a.get("frames") or [],
                    key=lambda f: -len(f.get("buckets", [])))
    for f in frames[:4]:
        t = _frame_tweet(f, briefing)
        if t:
            tweets.append(t)

    # Paradox tweet if present
    if a.get("paradox"):
        tweets.append(_paradox_tweet(a["paradox"], briefing))

    # Silence tweet
    sil = _silence_tweet(a.get("silences") or [])
    if sil:
        tweets.append(sil)

    # Outlet finding
    of = _outlet_finding_tweet(a.get("single_outlet_findings") or [], briefing)
    if of:
        tweets.append(of)

    # Schema requires 3..12 tweets. Trim to 8 to keep it readable.
    tweets = tweets[:8]

    out = {
        "story_key": a["story_key"],
        "date": a["date"],
        "hook": hook,
        "tweets": tweets,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": "template:render_thread.py",
    }
    return meta.stamp(out)


def render_one(json_path: Path) -> Path:
    a = json.loads(json_path.read_text(encoding="utf-8"))
    briefing = _load_briefing(a["date"], a["story_key"])
    draft = render(a, briefing)

    DRAFTS.mkdir(exist_ok=True)
    out = DRAFTS / f"{a['date']}_{a['story_key']}_thread.json"
    out.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", type=Path,
                    help="Specific .json analysis files. Default: all for --date.")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    targets = list(args.files) if args.files else sorted(
        ANALYSES.glob(f"{args.date or datetime.now(timezone.utc).strftime('%Y-%m-%d')}_*.json")
    )
    if not targets:
        print("No analyses to render threads from.")
        return 0

    for t in targets:
        if t.suffix != ".json":
            continue
        out = render_one(t)
        print(f"  + {t.name:<48} -> {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
