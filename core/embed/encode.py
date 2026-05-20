"""embed_articles.py — encode every article in a snapshot for the perception layer.

PR2 Phase B. Reads snapshots/<DATE>.json, extracts the signal-text excerpt
per article (matching the eval-set construction in calibration/), encodes
with the model from meta.PERCEPTION['embedding_model'], and writes:

  snapshots/<DATE>_embeddings.npy        — (N, D) float32 array
  snapshots/<DATE>_embedding_ids.json    — list of N versioned article_ids

The article_id key for each row is
  sha256(f"{model_id}|{signal_text_version}|{feed_name}|{link}")[:12]
matching analytical.perception.article_id(). Bumping either
`meta.PERCEPTION.embedding_model` or `meta.PERCEPTION.signal_text_version`
in meta_version.json invalidates EVERY cached embedding key, so a stale
.npy cannot silently serve old vectors after a model swap.

The .npy artefact is excluded from git via .gitignore — it's ~13MB per
day at e5-large's 1024-dim float32, and CI runners regenerate fresh each
cron. Local development re-runs reuse when present.

Usage:
  python -m core.embed.encode                  # latest snapshot in snapshots/
  python -m core.embed.encode --date 2026-05-19
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import core.meta as meta
from core.embed import article_id as perception  # alias: legacy callers
# expected perception.article_id/model_input_prefix/signal_excerpt_for_embedding.
# The new article_id module exports those three; softmax-argmax retires in D.3.

SNAPSHOTS = meta.SNAPSHOTS_DIR


def encode_snapshot(date: str, snapshots_dir: Path = SNAPSHOTS) -> int:
    """Encode every article in snapshots/<DATE>.json. Returns 0 on success,
    non-zero on error. Skips if the cache already exists for the current
    (model_id, signal_text_version) combo — call sites that need a forced
    refresh should delete the .npy first."""
    snap_path = snapshots_dir / f"{date}.json"
    if not snap_path.exists():
        print(f"snapshot not found: {snap_path}", file=sys.stderr)
        return 1
    perception_cfg = getattr(meta, "PERCEPTION", None) or {}
    model_id = perception_cfg.get("embedding_model")
    sig_version = perception_cfg.get("signal_text_version", "v1")
    if not model_id:
        print("meta.PERCEPTION.embedding_model is unset; cannot embed",
              file=sys.stderr)
        return 1

    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    items: list[tuple[str, dict]] = []  # (article_id, item)
    for ck, cv in (snap.get("countries") or {}).items():
        for f in (cv.get("feeds") or []):
            feed_name = f.get("name") or ""
            for it in (f.get("items") or []):
                link = it.get("link") or ""
                if not link:
                    continue
                aid = perception.article_id(feed_name, link, model_id, sig_version)
                items.append((aid, it))
    if not items:
        print(f"no articles in {snap_path}; nothing to embed", file=sys.stderr)
        return 0

    print(f"{len(items)} articles to embed using {model_id}", flush=True)

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as e:
        print(f"sentence-transformers / numpy not installed: {e}",
              file=sys.stderr)
        return 1

    t0 = time.time()
    model = SentenceTransformer(model_id)
    load_s = time.time() - t0
    print(f"  loaded model in {load_s:.1f}s", flush=True)

    prefix = perception.model_input_prefix(model_id)
    texts = [prefix + perception.signal_excerpt_for_embedding(it)
             for _, it in items]

    t1 = time.time()
    vecs = model.encode(texts, batch_size=16, show_progress_bar=False,
                          normalize_embeddings=True)
    enc_s = time.time() - t1
    vecs = np.asarray(vecs, dtype="float32")
    print(f"  encoded {len(texts)} articles in {enc_s:.1f}s "
          f"({len(texts)/max(enc_s,0.01):.1f}/sec)", flush=True)

    ids_path = snapshots_dir / f"{date}_embedding_ids.json"
    vec_path = snapshots_dir / f"{date}_embeddings.npy"
    ids_path.write_text(
        json.dumps([aid for aid, _ in items], separators=(",", ":")),
        encoding="utf-8",
    )
    np.save(vec_path, vecs)
    print(f"  wrote {vec_path.name} ({vecs.nbytes // 1024} KB) "
          f"+ {ids_path.name}", flush=True)
    return 0


def latest_snapshot_date() -> str | None:
    cands = sorted(p for p in SNAPSHOTS.glob("[0-9]*.json")
                   if not p.stem.endswith(("_convergence", "_similarity",
                                           "_prompt", "_dedup", "_health",
                                           "_pull_report")))
    if not cands:
        return None
    # filename = "<date>.json"
    return cands[-1].stem


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None,
                    help="Date (YYYY-MM-DD). Defaults to latest snapshot.")
    args = ap.parse_args()
    date = args.date or latest_snapshot_date()
    if not date:
        print("no snapshot date found", file=sys.stderr)
        return 1
    return encode_snapshot(date)


if __name__ == "__main__":
    sys.exit(main())
