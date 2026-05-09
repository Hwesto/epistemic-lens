"""wire_baseline.py — rolling N-day wire-services bigram corpus.

The "wire baseline" is the project's anchor for the tilt index (4f):
combined Reuters + AP + AFP + other wire-services bucket articles across
the last N days, tokenised the same way as `within_language_pmi.py`,
emitted as a bigram counter that downstream `tilt_index.py` can compare
each outlet against.

Why wire-as-baseline? Wire copy is the closest thing to a "no-frame"
control in news coverage: it's deliberately written to be re-used by
hundreds of outlets, so its language tends toward the common-denominator
descriptive form. The choice of wire-as-neutral is a *commitment* not a
fact — see `docs/METHODOLOGY.md` "Pin discipline for wire baseline" for
the project's stance. The tilt index machinery ships at v7.4.0; the
public claim about "tilt vs neutral" only becomes defensible once the
project owner commits to defending the wire baseline (Phase 4g).

Reads `briefings/<DATE>_<story>.json` → corpus[i] entries with
`bucket=="wire_services"` → tokenises (title + signal_text via
`meta.tokenize`) → builds bigram counter from adjacent stopword-filtered
tokens. Same tokenisation as the rest of the pipeline; bigrams skip
across stopwords.

Output: `baseline/wire_bigrams.json` — single rolling artefact, not
per-day. Each run reads the last `--window-days` of briefings and
overwrites.

Skip: with `insufficient_history` when fewer than `--min-days` (default
14) of briefings have wire articles.

Usage:
  python -m analytical.wire_baseline                       # default 90-day window
  python -m analytical.wire_baseline --window-days 30
  python -m analytical.wire_baseline --min-days 7          # for testing
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"
BASELINE = ROOT / "baseline"


def collect_wire_articles(window_days: int = 90,
                            today: str | None = None,
                            briefings_dir: Path = BRIEFINGS) -> list[dict]:
    """All wire_services articles across briefings within the window."""
    today_d = date.fromisoformat(today) if today else date.today()
    cutoff = (today_d - timedelta(days=window_days)).isoformat()
    out: list[dict] = []
    for p in briefings_dir.glob("*.json"):
        if p.stem.endswith(("_metrics", "_within_lang_llr",
                            "_within_lang_pmi", "_headline")):
            continue
        # First two tokens of the stem are the date.
        if len(p.stem) < 10:
            continue
        d = p.stem[:10]
        if d < cutoff:
            continue
        try:
            briefing = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for art in briefing.get("corpus") or []:
            if art.get("bucket") == "wire_services":
                out.append({**art, "_briefing_date": d,
                            "_briefing_path": p.name})
    return out


def build_bigrams(articles: list[dict]) -> Counter:
    """Tokenise each article and count adjacent (stopword-filtered) bigrams."""
    bigrams: Counter = Counter()
    for art in articles:
        text = (art.get("title") or "") + "\n" + (art.get("signal_text") or "")
        toks = meta.tokenize(text)
        for i in range(len(toks) - 1):
            bigrams[(toks[i], toks[i + 1])] += 1
    return bigrams


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--window-days", type=int, default=90)
    ap.add_argument("--min-days", type=int, default=14,
                    help="Skip with insufficient_history if fewer days carry wire articles.")
    ap.add_argument("--today", default=None)
    ap.add_argument("--out-dir", default=str(BASELINE))
    args = ap.parse_args()

    articles = collect_wire_articles(window_days=args.window_days,
                                       today=args.today)
    days_with_wire = len({a["_briefing_date"] for a in articles})
    if days_with_wire < args.min_days:
        print(f"insufficient_history: {days_with_wire} days with wire articles, "
              f"need ≥{args.min_days}. Skipping wire-baseline build.")
        return 0

    bigrams = build_bigrams(articles)
    n_articles = len(articles)
    n_bigrams = sum(bigrams.values())

    # Cap output size: keep top-K most common bigrams. Bigram counter for
    # 90 days × ~50 wire articles/day × ~200 tokens = ~900K bigram tokens
    # but only ~50K distinct. Store all distinct ≥ count 2 for stability.
    filtered = {f"{a}|{b}": n for (a, b), n in bigrams.items() if n >= 2}

    out = meta.stamp({
        "_doc": (
            "Rolling wire-services bigram corpus. Anchor for tilt_index.py. "
            "Bigrams keyed as 'a|b' (pipe-joined adjacent stopword-filtered "
            "tokens). Counts ≥ 2 only — singletons are noise."
        ),
        "window_days": args.window_days,
        "n_days_with_wire": days_with_wire,
        "n_articles": n_articles,
        "n_distinct_bigrams": len(bigrams),
        "n_bigrams_kept": len(filtered),
        "n_total_bigram_tokens": n_bigrams,
        "bigrams": dict(sorted(filtered.items(), key=lambda kv: -kv[1])),
    })
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "wire_bigrams.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"  wire_baseline: {n_articles} articles across {days_with_wire} days, "
          f"{len(filtered)} distinct bigrams (count≥2). → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
