"""salience.py — rank daily clusters by editorial salience (v10 D.3).

After core/cluster/cluster_daily.py produces ~50-200 clusters per day,
this script ranks them and picks the top N to receive briefings +
analysis. The other clusters land in archive but don't trigger LLM work.

Salience score:
  salience = n_articles
             × min(1.0, n_countries / total_countries_today)
             × (1.0 + lang_bonus)
             × stability

Where:
  - n_articles: cluster member count. Larger = more coverage.
  - n_countries: distinct countries contributing articles. Cross-bloc
    presence is the whole point of the project.
  - lang_bonus: 0.5 if cluster spans ≥2 languages, else 0. Multilingual
    coverage is editorial signal (story matters to multiple linguistic
    spheres).
  - stability: HDBSCAN's per-cluster persistence score (0-1) if
    available, else 1.0. Stable clusters are denser and more coherent.

The top-N cap is intentionally small (default 15) — that's what
core/analyze/prompts/daily_analysis.md can realistically process per
day. Beyond ~15 stories, editorial focus dilutes and the LLM cost
balloons without proportional value.

Outputs `data/snapshots/<DATE>_top_clusters.json` — the input to
core/briefing/build.py.

Usage:
  python -m core.cluster.salience                # latest day
  python -m core.cluster.salience --top-n 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import core.meta as meta

SNAPSHOTS = meta.SNAPSHOTS_DIR
DEFAULT_TOP_N = 15


def score_cluster(c: dict, total_countries: int) -> float:
    """Return salience score per the formula in the module doc."""
    n_articles = int(c.get("n_articles", 0))
    n_countries = int(c.get("n_countries", 0))
    n_langs = int(c.get("n_langs", 0))
    stability = c.get("stability")
    if stability is None:
        stability = 1.0
    country_spread = min(1.0, n_countries / max(1, total_countries))
    lang_bonus = 0.5 if n_langs >= 2 else 0.0
    return n_articles * country_spread * (1.0 + lang_bonus) * float(stability)


def rank(date: str, top_n: int = DEFAULT_TOP_N) -> dict:
    clusters_path = SNAPSHOTS / f"{date}_clusters.json"
    if not clusters_path.exists():
        raise FileNotFoundError(
            f"clusters file missing for {date}; "
            f"run `python -m core.cluster.cluster_daily --date {date}` first"
        )
    doc = json.loads(clusters_path.read_text(encoding="utf-8"))
    clusters = doc.get("clusters") or []
    if not clusters:
        return _write_top(date, [], top_n)
    # Total countries across ALL clusters today — denominator for spread.
    total_countries = len({c
                            for cluster in clusters
                            for c in (cluster.get("country_distribution") or {})})
    if total_countries == 0:
        total_countries = 1
    # Score every cluster, sort desc, take top-N.
    scored = []
    for c in clusters:
        s = score_cluster(c, total_countries)
        scored.append({**c, "salience_score": round(s, 3)})
    scored.sort(key=lambda c: -c["salience_score"])
    top = scored[:top_n]
    print(f"  ranked {len(clusters)} clusters; top {len(top)} selected", flush=True)
    print(f"  salience range: {top[-1]['salience_score']:.2f} … "
          f"{top[0]['salience_score']:.2f}" if top else "  (empty)",
          flush=True)
    return _write_top(date, top, top_n)


def _write_top(date: str, top: list[dict], top_n: int) -> dict:
    out = meta.stamp({
        "date": date,
        "top_n_requested": top_n,
        "n_selected": len(top),
        "top_clusters": top,
    })
    out_path = SNAPSHOTS / f"{date}_top_clusters.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  wrote {out_path.name}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None,
                    help="Date (YYYY-MM-DD). Defaults to latest clusters file.")
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                    help=f"Top N clusters to select (default {DEFAULT_TOP_N}).")
    args = ap.parse_args()
    if args.date is None:
        cands = sorted(SNAPSHOTS.glob("[0-9]*_clusters.json"))
        if not cands:
            print("no _clusters.json found", file=sys.stderr)
            return 1
        # strip "_clusters.json" suffix
        args.date = cands[-1].stem.replace("_clusters", "")
    try:
        rank(args.date, top_n=args.top_n)
    except FileNotFoundError as e:
        print(f"::warning::{e}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
