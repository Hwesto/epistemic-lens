"""build_briefing.py — assemble per-story framing-comparison briefings.

For a given snapshot, identify the top cross-bucket stories and produce
briefing JSON files containing one signal-text excerpt per bucket. Falls
back to summary-only or title-only when body extraction failed (using
extract_full_text.signal_text()).

Output: briefings/<date>_<slug>.json — feed for video script generation.

Usage:
  python build_briefing.py                    # all auto-detected top stories
  python build_briefing.py --story hormuz     # one keyword cluster
  python build_briefing.py --max-stories 3    # cap how many briefings to write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import meta
from analytical import perception
from analytical.coverage_warnings import coverage_warnings_for
from pipeline.extract_full_text import signal_text

ROOT = meta.REPO_ROOT
SNAPS = ROOT / "snapshots"
FRESH = ROOT / "fresh_pull"
BRIEFINGS = ROOT / "briefings"
BRIEFINGS.mkdir(exist_ok=True)


# Canonical "story groups" — loaded from canonical_stories.json so the patterns
# are pinned by meta_version. The token detector below also surfaces emerging
# stories not in this list.
CANONICAL_STORIES = meta.canonical_stories()


def matches_story(item: dict, patterns, exclude=None) -> bool:
    """LEGACY: meta-v8.x regex matcher.

    NOT called from build_briefing_for_story any more — that path
    delegates to analytical.perception.assign_articles_to_stories (PR2
    Phase B, embedding softmax-argmax). This function survives ONLY as
    the canonical-pattern pre-filter used by find_emerging_stories
    below: when scanning unmatched article titles for emerging tokens,
    we exclude tokens that match an existing canonical regex so the
    discovery candidates aren't drowned out by known stories.

    Future: when find_emerging_stories is retired in favour of
    pipeline/discover_residual (which subtracts perception-assigned
    articles from the embedding cache to find true residuals),
    matches_story can be deleted.
    """
    txt = (item.get("title", "") + " " + item.get("summary", "") +
           " " + item.get("body_text", "")[:1500]).lower()
    for ex in (exclude or []):
        if re.search(ex, txt):
            return False
    return any(re.search(p, txt, re.I) for p in patterns)


def _compute_assignments(snap: dict) -> dict[str, perception.MatchResult]:
    """Encode every snapshot article (if not cached) and assign to a story
    via softmax-argmax. Returns {article_id: MatchResult}.

    Article identification uses analytical.perception.article_id which is
    keyed by (model_id, signal_text_version, feed_name, link), so bumping
    either model or signal-text version regenerates the cache loudly."""
    perception_cfg = getattr(meta, "PERCEPTION", None) or {}
    model_id = perception_cfg.get("embedding_model")
    sig_version = perception_cfg.get("signal_text_version", "v1")
    floor = float(perception_cfg.get("assignment_floor_default",
                                       perception.DEFAULT_FLOOR))
    cosine_gap = float(perception_cfg.get("cosine_gap_default", 0.02))
    if not model_id:
        # Legacy code path: no perception config → empty assignments
        # (callers fall back to regex). Useful for tests + during the
        # 8.x → 9.0 transition.
        return {}

    # Flatten the snapshot to (article_id, lang, item) tuples.
    flat: list[tuple[str, str, dict]] = []
    for ck, cv in (snap.get("countries") or {}).items():
        for f in (cv.get("feeds") or []):
            feed_name = f.get("name") or ""
            for it in (f.get("items") or []):
                link = it.get("link") or ""
                if not link:
                    continue
                aid = perception.article_id(feed_name, link, model_id, sig_version)
                lang = f.get("lang") or "en"
                flat.append((aid, lang, it))
    if not flat:
        return {}

    # Load embedding cache if present (CI's pipeline/embed_articles ran first).
    # Else, encode on the fly — slow but works for tests.
    date = snap.get("date") or ""
    cache = perception.load_embedding_cache(date) if date else None
    if cache is not None:
        cached_ids, cached_vecs = cache
        id_to_row = {aid: i for i, aid in enumerate(cached_ids)}
        # Subset to articles that have a cached row (all of them should
        # under steady state; a few may be missing on partial runs).
        keep_idx = []
        for aid, _, _ in flat:
            keep_idx.append(id_to_row.get(aid))
        # If any IDs missing, the cache is stale vs the snapshot — re-encode.
        if any(i is None for i in keep_idx):
            article_vecs, item_ids, item_langs = _encode_inline(flat, model_id)
        else:
            import numpy as np  # type: ignore
            article_vecs = cached_vecs[keep_idx]
            item_ids = [aid for aid, _, _ in flat]
            item_langs = [lang for _, lang, _ in flat]
    else:
        article_vecs, item_ids, item_langs = _encode_inline(flat, model_id)

    # Encode story anchors → centroids
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError:
        sys.stderr.write("sentence-transformers not installed; "
                          "perception layer disabled\n")
        return {}
    # Re-using the model load if we already loaded it inline; otherwise load now.
    model = _SHARED_MODEL.get(model_id) or SentenceTransformer(model_id)
    _SHARED_MODEL[model_id] = model
    story_anchors = {sk: sv.get("embedding_anchors") or []
                     for sk, sv in CANONICAL_STORIES.items()
                     if sv.get("embedding_anchors")}
    if not story_anchors:
        sys.stderr.write("no embedding_anchors in canonical_stories.json; "
                          "perception layer disabled\n")
        return {}
    centroids = perception.compute_story_centroids(
        story_anchors, model, prefix=perception.model_input_prefix(model_id)
    )
    return perception.assign_articles_to_stories(
        item_ids, item_langs, article_vecs, centroids,
        floor=floor, cosine_gap=cosine_gap,
    )


# Module-level model cache so build_briefing doesn't reload the
# multilingual model when called multiple times in the same process
# (tests, the analyze step, etc.).
_SHARED_MODEL: dict = {}


def _encode_inline(flat, model_id):
    """Fallback encoder used when no per-day .npy cache is present."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        sys.stderr.write("sentence-transformers not installed\n")
        return None, [], []
    model = _SHARED_MODEL.get(model_id) or SentenceTransformer(model_id)
    _SHARED_MODEL[model_id] = model
    prefix = perception.model_input_prefix(model_id)
    texts = [prefix + perception.signal_excerpt_for_embedding(it)
             for _, _, it in flat]
    vecs = model.encode(texts, batch_size=16, show_progress_bar=False,
                          normalize_embeddings=True)
    vecs = np.asarray(vecs, dtype="float32")
    item_ids = [aid for aid, _, _ in flat]
    item_langs = [lang for _, lang, _ in flat]
    return vecs, item_ids, item_langs


def _title_tokens(s: str) -> set[str]:
    return set(t for t in re.findall(r"[a-z]{4,}", s.lower())
               if t not in {"says", "with", "from", "this", "after", "their", "have",
                            "been", "over", "into", "what", "when", "where", "warns",
                            "could", "would", "will", "more", "than", "they", "while"})


def build_briefing_for_story(snap: dict, story_key: str, story_def: dict,
                             per_bucket_max: int = 2,
                             novelty_threshold: float = 0.4,
                             assignments: dict | None = None) -> dict:
    """For one story definition, collect signal-text per bucket.

    `assignments` is the {article_id: perception.MatchResult} dict produced
    by `_compute_assignments`. When provided, articles are filtered by
    softmax-argmax assignment (PR2 Phase B; meta-v9.x). When None (legacy
    pre-9.0 path), falls back to regex `matches_story` against
    `story_def["patterns"]`.

    Per bucket, keeps up to `per_bucket_max` articles that have meaningfully
    different titles (Jaccard token overlap < 1-novelty_threshold).
    Default: 2 per bucket — captures distinct framings (e.g. UK BBC's neutral
    obit + The Independent's "Trump took shot at CNN" angle on Ted Turner).
    """
    perception_cfg = getattr(meta, "PERCEPTION", None) or {}
    model_id = perception_cfg.get("embedding_model") or ""
    sig_version = perception_cfg.get("signal_text_version", "v1")

    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for ck, cv in snap.get("countries", {}).items():
        for f in cv.get("feeds", []):
            feed_name = f.get("name", "")
            for it in f.get("items", []):
                # PR2 Phase B: embedding-based assignment via softmax-argmax.
                # Compute article_id ONCE per item so we don't re-hash for
                # the filter and again for the match_cosine stamp.
                match = None
                if assignments:
                    link = it.get("link") or ""
                    if not link:
                        continue
                    aid = perception.article_id(feed_name, link, model_id, sig_version)
                    match = assignments.get(aid)
                    if not match or match.story_key != story_key:
                        continue
                else:
                    # 8.x → 9.0 transition path: no PERCEPTION pin.
                    if not matches_story(
                        it,
                        story_def.get("patterns") or [],
                        story_def.get("exclude"),
                    ):
                        continue
                level, text = signal_text(it)
                if level == "empty":
                    continue
                article_entry = {
                    "feed": feed_name,
                    "lang": f.get("lang", "en"),
                    "title": it.get("title", "")[:240],
                    "link": it.get("link", "")[:300],
                    "signal_level": level,
                    "signal_text": text,
                    "extraction_status": it.get("extraction_status"),
                    "via_wayback": it.get("extraction_via_wayback", False),
                }
                # Stamp the matcher's confidence so downstream consumers
                # (validators, render, audit) can see how strongly this
                # article was pulled into the story.
                if match is not None:
                    article_entry["match_cosine"] = round(match.cosine, 4)
                    article_entry["match_softmax"] = round(match.softmax_score, 4)
                by_bucket[ck].append(article_entry)

    rank = {"body": 3, "summary": 2, "title": 1}
    corpus = []
    for ck in sorted(by_bucket):
        # Highest signal first, longer text wins ties
        arts = sorted(by_bucket[ck],
                      key=lambda a: (-rank.get(a["signal_level"], 0),
                                     -len(a["signal_text"])))
        kept_for_bucket: list[dict] = []
        kept_token_sets: list[set] = []
        for a in arts:
            if len(kept_for_bucket) >= per_bucket_max:
                break
            tokens = _title_tokens(a["title"])
            # Skip if too similar to an already-kept title in this bucket
            too_similar = False
            for prev in kept_token_sets:
                if not tokens or not prev:
                    continue
                jaccard = len(tokens & prev) / max(1, len(tokens | prev))
                if jaccard >= (1 - novelty_threshold):
                    too_similar = True
                    break
            if too_similar:
                continue
            kept_for_bucket.append(a)
            kept_token_sets.append(tokens)
        for a in kept_for_bucket:
            corpus.append({"bucket": ck, **a})

    # Phase 3i + 3j: stamp per-bucket feed-set hash + the active
    # canonical_stories pin so longitudinal aggregator can detect drift
    # in either dimension across days.
    bucket_feed_set_hashes = meta.bucket_feed_set_hashes(list(by_bucket.keys()))
    # Coverage caveats: buckets that had ZERO items today because every
    # feed in them failed. The analyze prompt is instructed to treat
    # these as structural silence (not editorial choice).
    caveats = coverage_warnings_for(snap.get("date") or "")
    return meta.stamp({
        "date": snap.get("date"),
        "story_key": story_key,
        "story_title": story_def["title"],
        "n_buckets": len(by_bucket),
        "n_articles_total": sum(len(v) for v in by_bucket.values()),
        "signal_breakdown": dict(Counter(a["signal_level"] for a in corpus)),
        "corpus": corpus,
        "bucket_feed_set_hashes": bucket_feed_set_hashes,
        "canonical_stories_hash": meta.META.get("canonical_stories_hash", ""),
        "coverage_caveats": caveats,
    })


def find_emerging_stories(snap: dict, min_buckets: int = 5,
                          ignore_canonical: bool = True) -> list[tuple[str, set]]:
    """Token-frequency detection of unrecognised cross-bucket stories."""
    STOP = set("the and that with from this their have been over into about because while says will could trump iran said".split())
    canon_pat = re.compile(
        "|".join(p for s in CANONICAL_STORIES.values() for p in s["patterns"]),
        re.I,
    ) if ignore_canonical else None

    token_buckets = defaultdict(set)
    for ck, cv in snap.get("countries", {}).items():
        for f in cv.get("feeds", []):
            for it in f.get("items", []):
                title = it.get("title", "")
                if canon_pat and canon_pat.search(title):
                    continue
                seen = set()
                for tok in re.findall(r"[A-Za-z]{5,}", title.lower()):
                    if tok not in STOP:
                        seen.add(tok)
                for tok in seen:
                    token_buckets[tok].add(ck)
    emerging = [(t, b) for t, b in token_buckets.items() if len(b) >= min_buckets]
    emerging.sort(key=lambda x: -len(x[1]))
    return emerging[:10]


def latest_snapshot_path(snap_dir: Path | None = None) -> Path | None:
    snap_dir = snap_dir or SNAPS
    cands = sorted(p for p in snap_dir.glob("[0-9]*.json")
                   if not p.stem.endswith(("_convergence", "_similarity",
                                           "_prompt", "_dedup", "_health")))
    return cands[-1] if cands else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, default=None,
                    help="Path to snapshot file. Default: latest in snapshots/ or fresh_pull/")
    ap.add_argument("--story", default="",
                    help="Build only this canonical story key (e.g. 'hormuz_iran')")
    ap.add_argument("--max-stories", type=int, default=15,
                    help="Cap on how many briefings to write per run. "
                         "Default 15 covers every canonical story; lower values "
                         "truncate by tier-priority order (long_running first).")
    ap.add_argument("--min-buckets", type=int, default=4,
                    help="Skip stories with fewer than N buckets covering them")
    ap.add_argument("--out-dir", type=Path, default=BRIEFINGS)
    args = ap.parse_args()

    snap_path = args.snapshot
    if snap_path is None:
        # Prefer fresh_pull if present (smoke-test artifact)
        snap_path = latest_snapshot_path(FRESH) or latest_snapshot_path(SNAPS)
    if snap_path is None or not snap_path.exists():
        sys.exit("No snapshot found")
    print(f"Building briefings from {snap_path}", flush=True)
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    args.out_dir.mkdir(exist_ok=True)

    # PR2 Phase B: pre-compute softmax-argmax story assignment for every
    # article in the snapshot, in one pass. Each story-build step then just
    # filters to its assigned articles. Replaces the Latin-script regex
    # matcher that rejected 100% of non-Latin articles.
    if (getattr(meta, "PERCEPTION", None) or {}).get("embedding_model"):
        print(f"Computing perception assignments "
              f"(model={meta.PERCEPTION['embedding_model']})...", flush=True)
        assignments = _compute_assignments(snap)
        n_assigned = sum(1 for m in assignments.values() if m.story_key)
        print(f"  {n_assigned} / {len(assignments)} articles assigned to a story",
              flush=True)
    else:
        # 8.x → 9.0 transition path: no PERCEPTION pin yet. Fall back to
        # regex via the legacy matches_story() path inside the per-story loop.
        assignments = None

    n_written = 0
    # Tier-priority iteration: long_running dossiers (Gaza, Taiwan, climate)
    # get first shot at the --max-stories budget; dated short-lived stories
    # only run after the long-runners. Within a tier, alphabetical for
    # determinism. Prior JSON-order iteration silently truncated dossiers
    # that happened to appear later in canonical_stories.json.
    tier_priority = {"long_running": 0, "dated": 2}
    keys = (
        [args.story]
        if args.story
        else sorted(
            CANONICAL_STORIES,
            key=lambda k: (tier_priority.get(CANONICAL_STORIES[k].get("tier"), 1), k),
        )
    )
    for key in keys:
        if key not in CANONICAL_STORIES:
            print(f"  skip: unknown story key '{key}'")
            continue
        story_def = CANONICAL_STORIES[key]
        b = build_briefing_for_story(snap, key, story_def,
                                      assignments=assignments)
        if b["n_buckets"] < args.min_buckets:
            print(f"  - {key:<24} {b['n_buckets']} buckets — under threshold, skipped")
            continue
        out_path = args.out_dir / f"{snap['date']}_{key}.json"
        out_path.write_text(json.dumps(b, indent=2, ensure_ascii=False))
        sb = b["signal_breakdown"]
        print(f"  + {key:<24} {b['n_buckets']:>2} buckets  "
              f"signal: {sb.get('body',0)} body / {sb.get('summary',0)} summ / "
              f"{sb.get('title',0)} title  -> {out_path.name}")
        n_written += 1
        if n_written >= args.max_stories:
            break

    print(f"\n{n_written} briefings written to {args.out_dir}/")

    # Emerging-stories report (just informational)
    emerging = find_emerging_stories(snap, min_buckets=4)
    if emerging:
        print("\nEmerging stories not in canonical list (>=4 buckets):")
        for tok, buckets in emerging[:8]:
            print(f"  {tok:<18} {len(buckets):>2} buckets")


if __name__ == "__main__":
    main()
