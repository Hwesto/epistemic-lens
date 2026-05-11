"""tilt_index.py — per-outlet log-odds vs wire baseline.

For each (bucket, outlet) pair carrying enough articles in the rolling
window, compute log-odds of bigram usage against the wire baseline
(`baseline/wire_bigrams.json`). Output: top distinctive (positive-tilt,
over-represented) and top suppressed (negative-tilt, under-represented)
bigrams per outlet, with Z-scores.

Same statistical apparatus as `analytical/within_language_pmi.py`:
log-odds with Jeffreys prior (α=0.5), Z = log_odds / sqrt(var). Reuses
that module's `log_odds_with_prior` helper.

**Important caveat — this is the *machinery* for the tilt index, not the
public-facing claim.** The tilt index becomes a defensible "tilt vs
neutral" claim only after the project owner publicly commits to
defending the wire baseline as a neutral anchor (Phase 4g). Until then,
the output is "log-odds vs wire" — descriptive, not normative.

Reads:
  - `baseline/wire_bigrams.json` (Phase 4e)
  - `briefings/<DATE>_<story>.json` for the rolling window

Output: `tilt/<bucket>__<outlet>.json` per outlet pair. Each contains
top-K positive-tilt + top-K negative-tilt bigrams.

Skip: insufficient_history if wire baseline isn't built yet, or per-outlet
when the outlet has fewer than `--min-outlet-articles` articles in window.

Usage:
  python -m analytical.tilt_index
  python -m analytical.tilt_index --window-days 30 --top-k 15
  python -m analytical.tilt_index --bucket usa
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import meta
from analytical.within_language_pmi import log_odds_with_prior

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"
BASELINE = ROOT / "baseline"
TILT = ROOT / "tilt"


def load_wire_baseline(path: Path = BASELINE / "wire_bigrams.json") -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
        print(f"FAIL: {path}: {e}", file=sys.stderr)
        return None


def collect_outlet_articles(window_days: int = 30,
                              today: str | None = None,
                              briefings_dir: Path = BRIEFINGS
                              ) -> dict[tuple[str, str], list[dict]]:
    """Per (bucket, outlet), list of articles within the window.
    Excludes wire_services (it IS the baseline) and opinion items."""
    today_d = date.fromisoformat(today) if today else date.today()
    cutoff = (today_d - timedelta(days=window_days)).isoformat()
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in briefings_dir.glob("*.json"):
        if p.stem.endswith(("_metrics", "_within_lang_llr",
                            "_within_lang_pmi", "_headline")):
            continue
        if len(p.stem) < 10:
            continue
        d = p.stem[:10]
        if d < cutoff:
            continue
        try:
            briefing = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
            print(f"FAIL: {p}: {e}", file=sys.stderr)
            continue
        for art in briefing.get("corpus") or []:
            bucket = art.get("bucket")
            outlet = art.get("feed")
            if not bucket or not outlet:
                continue
            if bucket == "wire_services":
                continue  # skip wire — it's the baseline
            if (art.get("section") or "news") == "opinion":
                continue
            out[(bucket, outlet)].append(art)
    return out


def parse_baseline_bigrams(baseline: dict) -> Counter:
    """Parse the 'a|b' keys back into (token, token) tuples."""
    cnt: Counter = Counter()
    for k, n in (baseline.get("bigrams") or {}).items():
        if "|" not in k:
            continue
        a, b = k.split("|", 1)
        cnt[(a, b)] = int(n)
    return cnt


def outlet_bigrams(articles: list[dict]) -> Counter:
    cnt: Counter = Counter()
    for art in articles:
        text = (art.get("title") or "") + "\n" + (art.get("signal_text") or "")
        toks = meta.tokenize(text)
        for i in range(len(toks) - 1):
            cnt[(toks[i], toks[i + 1])] += 1
    return cnt


def build_bucket_mean_baseline(outlets: dict[tuple[str, str], list[dict]]
                                 ) -> Counter:
    """PR 7: aggregate cross-bucket bigram counts as the second anchor
    for the tilt index. This is the *average* of every non-wire outlet
    in the window — what "the cross-bucket consensus" actually looks
    like, in contrast to `wire` (which is the Reuters/AFP/AP framing).
    Reporting tilt against both anchors triangulates: single-anchor
    "tilt vs wire" privileges wire as a hidden truth-baseline; bucket
    mean offers no such privilege but is itself average-of-included-
    outlets and has its own selection bias. Two columns honestly
    surface this rather than pretending either is The Neutral.
    """
    out: Counter = Counter()
    for (bucket, _outlet), arts in outlets.items():
        if bucket == "wire_services":
            continue
        out.update(outlet_bigrams(arts))
    return out


def compute_outlet_tilt(outlet_cnt: Counter,
                          baseline_cnt: Counter,
                          min_count: int = 2,
                          top_k: int = 15) -> dict:
    """Per-outlet tilt: top positive (over-represented vs the baseline) +
    top negative (under-represented vs the baseline) bigrams by Z-score.
    `baseline_cnt` is either the wire-services anchor or the
    cross-bucket-mean anchor — both are valid, neither is uniquely
    neutral."""
    total_o = sum(outlet_cnt.values()) or 1
    total_b = sum(baseline_cnt.values()) or 1
    # Scan the union: outlet-bigrams (positive candidates) AND baseline
    # bigrams the outlet doesn't use (negative candidates).
    candidates = set(outlet_cnt) | set(baseline_cnt)
    positive: list[dict] = []
    negative: list[dict] = []
    for bg in candidates:
        a = int(outlet_cnt.get(bg, 0))
        b = int(baseline_cnt.get(bg, 0))
        if max(a, b) < min_count:
            continue
        log_odds, _, z = log_odds_with_prior(a, b, total_o, total_b)
        rate_o = a / total_o
        rate_b = b / total_b if total_b else 0
        entry = {
            "bigram": list(bg),
            "count_in_outlet": a,
            "count_in_baseline": b,
            "rate_in_outlet": round(rate_o, 6),
            "rate_in_baseline": round(rate_b, 6),
            "log_odds": round(log_odds, 3),
            "z_score": round(z, 2),
        }
        if z >= 1.96:
            positive.append(entry)
        elif z <= -1.96:
            negative.append(entry)
    positive.sort(key=lambda r: -r["z_score"])
    negative.sort(key=lambda r: r["z_score"])
    return {
        "n_outlet_bigrams": int(total_o),
        "n_baseline_bigrams": int(total_b),
        "n_outlet_distinct": len(outlet_cnt),
        "positive_tilt": positive[:top_k],
        "negative_tilt": negative[:top_k],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--window-days", type=int, default=30)
    ap.add_argument("--min-outlet-articles", type=int, default=3,
                    help="Skip outlets with fewer articles in window.")
    ap.add_argument("--top-k", type=int, default=15)
    ap.add_argument("--bucket", default=None,
                    help="Filter to outlets in this bucket only.")
    ap.add_argument("--today", default=None)
    ap.add_argument("--out-dir", default=str(TILT))
    args = ap.parse_args()

    baseline = load_wire_baseline()
    if not baseline:
        print("insufficient_history: no baseline/wire_bigrams.json yet. "
              "Run `python -m analytical.wire_baseline` first.")
        return 0
    wire_cnt = parse_baseline_bigrams(baseline)
    if sum(wire_cnt.values()) == 0:
        print("insufficient_history: wire baseline is empty.")
        return 0

    outlets = collect_outlet_articles(window_days=args.window_days,
                                        today=args.today)
    # PR 7: second anchor for triangulation. Compute the cross-bucket-mean
    # baseline once per run and pass it alongside `wire` to each per-outlet
    # tilt computation. Output documents both anchors so consumers don't
    # have to treat `wire` as a hidden truth-baseline.
    bucket_mean_cnt = build_bucket_mean_baseline(outlets)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n_written = 0
    for (bucket, outlet), arts in sorted(outlets.items()):
        if args.bucket and bucket != args.bucket:
            continue
        if len(arts) < args.min_outlet_articles:
            continue
        outlet_cnt = outlet_bigrams(arts)
        tilt_wire = compute_outlet_tilt(outlet_cnt, wire_cnt, top_k=args.top_k)
        tilt_mean = compute_outlet_tilt(outlet_cnt, bucket_mean_cnt, top_k=args.top_k)
        out = meta.stamp({
            "bucket": bucket,
            "outlet": outlet,
            "window_days": args.window_days,
            "n_articles_in_window": len(arts),
            "wire_baseline_pin": baseline.get("meta_version", "?"),
            "wire_baseline_n_articles": baseline.get("n_articles", 0),
            "n_outlet_distinct": tilt_wire["n_outlet_distinct"],
            "anchors": {
                "wire": {
                    "n_baseline_bigrams": tilt_wire["n_baseline_bigrams"],
                    "positive_tilt": tilt_wire["positive_tilt"],
                    "negative_tilt": tilt_wire["negative_tilt"],
                },
                "bucket_mean": {
                    "n_baseline_bigrams": tilt_mean["n_baseline_bigrams"],
                    "positive_tilt": tilt_mean["positive_tilt"],
                    "negative_tilt": tilt_mean["negative_tilt"],
                },
            },
        })
        # Filename: <bucket>__<outlet>.json with outlet sanitised.
        outlet_safe = (outlet.replace("/", "_").replace(" ", "_")
                              .replace("|", "_").replace("(", "")
                              .replace(")", ""))[:60]
        out_path = out_dir / f"{bucket}__{outlet_safe}.json"
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        n_written += 1
    print(f"wrote {n_written} per-outlet tilt files to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
