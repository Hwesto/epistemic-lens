"""build.py — assemble one briefing per top-salience cluster (v10 D.3).

For each cluster in `data/snapshots/<DATE>_top_clusters.json` (produced
by core/cluster/salience.py), this script builds a per-cluster corpus
file at `data/briefings/<DATE>_<lineage_id>.json`. The corpus is what
Claude reads to write the framing analysis.

What changed from v9:
  - **No canonical_stories.json.** v9 matched articles to one of 15
    pre-defined stories via softmax-argmax against embedding anchors.
    v10 takes whatever clusters surface from HDBSCAN over the day's
    full article set. Stories are emergent, not pre-set.
  - **Lineage IDs replace story keys.** Filenames carry `<lineage_id>`
    (a stable hash from the cluster's first-appearance day) instead of
    human names like `iran_nuclear`. Persistent stories get persistent
    IDs across days via core/cluster/lineage.py.
  - **Outlets, not buckets.** Each corpus entry carries `outlet` (the
    feed name) plus tags `country`, `lang`, `lean`. The old "bucket"
    field is renamed to `country` — buckets aren't aggregation units
    in v10.
  - **Per-bucket-max → per-outlet-max.** Within a cluster, we keep up
    to N articles per OUTLET (default 2) to maximise framing diversity.
    Title-Jaccard novelty filter still applies.

What stays:
  - signal_text fallback chain (body → summary → title)
  - per-article extraction_status / via_wayback flags
  - coverage_caveats (which countries had zero items today due to feed
    failures — preserved for the analyst's "structural vs editorial
    silence" distinction)
  - meta.stamp() on every briefing for version pinning

Usage:
  python -m core.briefing.build                       # latest day
  python -m core.briefing.build --date 2026-05-12
  python -m core.briefing.build --per-outlet-max 3
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import core.meta as meta
from core.briefing.coverage_warnings import coverage_warnings_for
from core.embed import article_id as aid_module
from core.ingest.extract_bodies import signal_text

SNAPSHOTS = meta.SNAPSHOTS_DIR
BRIEFINGS = meta.BRIEFINGS_DIR
BRIEFINGS.mkdir(parents=True, exist_ok=True)


# Title-tokens helper (kept from v9; novelty filter still useful).
def _title_tokens(s: str) -> set[str]:
    return set(t for t in re.findall(r"[a-z]{4,}", s.lower())
               if t not in {"says", "with", "from", "this", "after", "their",
                             "have", "been", "over", "into", "what", "when",
                             "where", "warns", "could", "would", "will",
                             "more", "than", "they", "while"})


def _lineage_id_for_cluster(date: str, cluster_id: int,
                              lineage_lookup: dict | None) -> str:
    """Return the stable lineage_id for this cluster.

    If a same-lineage cluster appeared earlier (via core/cluster/lineage.py),
    we reuse its lineage_id. Otherwise we mint a fresh one using today's
    date + cluster_id as the seed (same hash recipe as lineage.py:_lineage_id).
    """
    if lineage_lookup is not None:
        lid = lineage_lookup.get((date, cluster_id))
        if lid:
            return lid
    import hashlib
    h = hashlib.sha256(f"{date}|{cluster_id}".encode()).hexdigest()
    return f"L{h[:10]}"


def _load_lineage_lookup(date: str) -> dict | None:
    """Read the most-recent lineage file and return {(date, cluster_id): lineage_id}."""
    archive = meta.ARCHIVE_DIR
    cands = sorted(archive.glob("persistent_lineages_*.json"), reverse=True)
    for p in cands:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out: dict = {}
        for lineage in (doc.get("lineages") or []):
            lid = lineage.get("lineage_id")
            seed_date = lineage.get("seed_date")
            seed_cid = lineage.get("seed_cluster_id")
            latest_date = lineage.get("latest_date")
            latest_cid = lineage.get("latest_cluster_id")
            if lid and seed_date is not None and seed_cid is not None:
                out[(seed_date, int(seed_cid))] = lid
            if lid and latest_date is not None and latest_cid is not None:
                out[(latest_date, int(latest_cid))] = lid
        if out:
            return out
    return None


def build_briefing_for_cluster(
    cluster: dict,
    snap: dict,
    lineage_id: str,
    per_outlet_max: int = 2,
    novelty_threshold: float = 0.4,
) -> dict:
    """For one cluster, assemble the per-outlet corpus."""
    member_ids = set(cluster.get("member_article_ids") or [])
    if not member_ids:
        return _empty_briefing(snap.get("date") or "", cluster, lineage_id)

    perception_cfg = getattr(meta, "PERCEPTION", None) or {}
    model_id = meta.embedding_model()
    sig_version = perception_cfg.get("signal_text_version", "v1")
    outlet_lookup = meta.outlet_by_name()

    by_outlet: dict[str, list[dict]] = defaultdict(list)
    for ck, cv in snap.get("countries", {}).items():
        for f in cv.get("feeds", []):
            feed_name = f.get("name", "")
            for it in f.get("items", []):
                link = it.get("link") or ""
                if not link:
                    continue
                aid = aid_module.article_id(feed_name, link, model_id, sig_version)
                if aid not in member_ids:
                    continue
                level, text = signal_text(it)
                if level == "empty":
                    continue
                outlet_meta = outlet_lookup.get(feed_name) or {}
                by_outlet[feed_name].append({
                    "outlet": feed_name,
                    "country": ck,
                    "country_label": outlet_meta.get("country_label") or "",
                    "lang": outlet_meta.get("lang") or f.get("lang") or "en",
                    "lean": outlet_meta.get("lean") or "",
                    "section": outlet_meta.get("section") or "news",
                    "title": it.get("title", "")[:240],
                    "link": link[:300],
                    "signal_level": level,
                    "signal_text": text,
                    "extraction_status": it.get("extraction_status"),
                    "via_wayback": it.get("extraction_via_wayback", False),
                })

    rank = {"body": 3, "summary": 2, "title": 1}
    corpus: list[dict] = []
    for outlet in sorted(by_outlet):
        arts = sorted(by_outlet[outlet],
                      key=lambda a: (-rank.get(a["signal_level"], 0),
                                     -len(a["signal_text"])))
        kept: list[dict] = []
        kept_tokens: list[set] = []
        for a in arts:
            if len(kept) >= per_outlet_max:
                break
            toks = _title_tokens(a["title"])
            if any(toks and prev and
                    len(toks & prev) / max(1, len(toks | prev)) >= (1 - novelty_threshold)
                    for prev in kept_tokens):
                continue
            kept.append(a)
            kept_tokens.append(toks)
        corpus.extend(kept)

    countries_present = sorted({a["country"] for a in corpus})
    langs_present = sorted({a["lang"] for a in corpus})
    leans_present = sorted({a["lean"] for a in corpus if a["lean"]})
    coverage = coverage_warnings_for(snap.get("date") or "")

    return meta.stamp({
        "date": snap.get("date"),
        "lineage_id": lineage_id,
        "cluster_id": int(cluster.get("cluster_id", -1)),
        "cluster_name": None,
        "salience_score": cluster.get("salience_score"),
        "top_tokens": cluster.get("top_tokens") or [],
        "n_articles_total": sum(len(v) for v in by_outlet.values()),
        "n_outlets": len(by_outlet),
        "n_countries": len(countries_present),
        "n_langs": len(langs_present),
        "countries_present": countries_present,
        "langs_present": langs_present,
        "leans_present": leans_present,
        "signal_breakdown": dict(Counter(a["signal_level"] for a in corpus)),
        "corpus": corpus,
        "coverage_caveats": coverage,
    })


def _empty_briefing(date: str, cluster: dict, lineage_id: str) -> dict:
    return meta.stamp({
        "date": date,
        "lineage_id": lineage_id,
        "cluster_id": int(cluster.get("cluster_id", -1)),
        "cluster_name": None,
        "n_articles_total": 0,
        "n_outlets": 0,
        "n_countries": 0,
        "corpus": [],
        "coverage_caveats": [],
    })


def latest_snapshot_path(snap_dir: Path | None = None) -> Path | None:
    snap_dir = snap_dir or SNAPSHOTS
    date = meta.latest_snapshot_date(snap_dir)
    if not date:
        return None
    p = snap_dir / f"{date}.json"
    return p if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, default=None,
                    help="Path to snapshot file. Default: latest in data/snapshots/.")
    ap.add_argument("--date", default=None,
                    help="Date (YYYY-MM-DD). If --snapshot is given, inferred from it.")
    ap.add_argument("--per-outlet-max", type=int, default=2,
                    help="Max articles per outlet per cluster (default 2).")
    ap.add_argument("--out-dir", type=Path, default=BRIEFINGS)
    args = ap.parse_args()

    snap_path = args.snapshot
    if snap_path is None:
        snap_path = latest_snapshot_path()
    if snap_path is None or not snap_path.exists():
        print("no snapshot found", file=sys.stderr)
        return 1
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    date = args.date or snap.get("date") or snap_path.stem

    top_clusters_path = SNAPSHOTS / f"{date}_top_clusters.json"
    if not top_clusters_path.exists():
        print(f"no top_clusters file for {date}; "
              f"run `python -m core.cluster.salience --date {date}` first",
              file=sys.stderr)
        return 1
    top_doc = json.loads(top_clusters_path.read_text(encoding="utf-8"))
    clusters = top_doc.get("top_clusters") or []
    if not clusters:
        print(f"no top clusters for {date}; nothing to brief", file=sys.stderr)
        return 0

    print(f"Building {len(clusters)} briefings from {snap_path}", flush=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    lineage_lookup = _load_lineage_lookup(date)

    n_written = 0
    for cluster in clusters:
        lid = _lineage_id_for_cluster(date, int(cluster.get("cluster_id", -1)),
                                        lineage_lookup)
        briefing = build_briefing_for_cluster(
            cluster, snap, lid,
            per_outlet_max=args.per_outlet_max,
        )
        out_path = args.out_dir / f"{date}_{lid}.json"
        out_path.write_text(json.dumps(briefing, indent=2, ensure_ascii=False))
        sb = briefing.get("signal_breakdown") or {}
        print(f"  + {lid:<14} "
              f"n_outlets={briefing.get('n_outlets', 0):>3} "
              f"n_countries={briefing.get('n_countries', 0):>2} "
              f"signal: {sb.get('body', 0)} body / {sb.get('summary', 0)} summ "
              f"/ {sb.get('title', 0)} title  -> {out_path.name}", flush=True)
        n_written += 1

    print(f"\n{n_written} briefings written to {args.out_dir}/", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
