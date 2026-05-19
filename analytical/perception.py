"""perception.py — softmax-argmax story matcher (PR2 Phase B).

Replaces the Latin-script regex matcher (`build_briefing.matches_story`)
that rejected 100% of non-Latin script articles. Each article is
encoded with a multilingual embedding model, scored against every
canonical story's anchor centroid (cosine), and assigned to its
strongest match above a per-story floor.

Algorithm:
  1. For each story, encode its `embedding_anchors` list (English + native-script
     variants written in calibration/embedding_anchors_draft.json, copied to
     canonical_stories.json by Phase B). Take the mean of unit-normed vectors;
     re-normalise. That's the story centroid.
  2. For each article, encode (title + signal_text[:1500]).
  3. Score article vs each story centroid (cosine = dot product, since both unit-norm).
  4. Apply per-language floor delta if `per_lang_floor_delta[lang][story]` is set.
  5. Argmax over the n_stories scores → assigned story.
  6. Keep the assignment only if argmax_cosine >= story.assignment_floor.

This is the disambiguation-by-competition design from the LLM-challenge
critique (#2 — exclude-anchors don't scale). An article about US-Iran Hormuz
negotiations would previously match `lebanon_buffer` AND `hormuz_iran` AND
`iran_nuclear` via independent thresholds; softmax-argmax picks the strongest
and the others receive zero.

Calibrated 2026-05-19 against a 343-row Opus silver-labeled eval set.
Winner: intfloat/multilingual-e5-large. Macro F1 = 0.815;
4 of 5 gate-checkable per-language F1s pass; Arabic shortfall = 0.033.
See `calibration/perception_eval_report.md`.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import meta

# Articles below this raw cosine never get assigned (after per-lang delta
# adjustment). Set by Phase A calibration; conservative default for safety.
DEFAULT_FLOOR = 0.40


@dataclass(frozen=True)
class MatchResult:
    """One article's assignment decision. `story_key=None` means "no story"
    (cosine below floor on every story)."""
    story_key: str | None
    cosine: float          # the argmax cosine
    softmax_score: float   # the softmax-normalised score of the argmax story
    second_best_story: str | None  # for downstream FP investigation
    second_best_cosine: float

    def to_dict(self) -> dict:
        return {
            "story_key": self.story_key,
            "cosine": round(self.cosine, 4),
            "softmax_score": round(self.softmax_score, 4),
            "second_best_story": self.second_best_story,
            "second_best_cosine": round(self.second_best_cosine, 4),
        }


def article_id(feed_name: str, link: str, model_id: str,
                signal_text_version: str) -> str:
    """Versioned article ID. Bumping model_id or signal_text_version in
    meta_version.json invalidates every cached embedding under this key,
    so a stale cache CANNOT silently serve old vectors after a model swap."""
    key = f"{model_id}|{signal_text_version}|{feed_name}|{link}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def signal_excerpt_for_embedding(item: dict, max_chars: int = 1500) -> str:
    """The text we feed to the embedding model. Mirrors the eval-set
    construction in calibration/build_eval_set.py — title + first 1500
    chars of body/summary/title fallback chain. Keeping this in sync with
    the calibration is critical; the silver-label F1 numbers only transfer
    if production uses the same input."""
    title = (item.get("title") or "")[:240]
    body = item.get("body_text") or ""
    if len(body) >= 100:
        return title + "\n" + body[:max_chars]
    summary = item.get("summary") or ""
    if len(summary) >= 60:
        return title + "\n" + summary[:max_chars]
    return title


def compute_story_centroids(
    story_anchors: dict[str, list[str]],
    model,
    prefix: str = "",
):
    """Encode each story's anchors with the passed sentence-transformers
    model, mean-pool, unit-normalise. Returns {story_key: np.ndarray (D,)}.

    `prefix` is the model-specific input directive (e5 wants
    "passage: "; LaBSE / bge-m3 use ""). Mirrors INPUT_PREFIXES in
    calibration/benchmark_models.py."""
    import numpy as np  # type: ignore

    story_keys = sorted(story_anchors)
    flat: list[str] = []
    spans: list[tuple[int, int]] = []
    for sk in story_keys:
        n = len(story_anchors[sk])
        spans.append((len(flat), len(flat) + n))
        flat.extend(prefix + a for a in story_anchors[sk])
    vecs = model.encode(flat, batch_size=16, show_progress_bar=False,
                          normalize_embeddings=True)
    vecs = np.asarray(vecs, dtype="float32")
    out: dict[str, "np.ndarray"] = {}
    for sk, (i0, i1) in zip(story_keys, spans):
        c = vecs[i0:i1].mean(axis=0)
        nrm = float(np.linalg.norm(c))
        if nrm > 0:
            c = c / nrm
        out[sk] = c
    return out


def assign_articles_to_stories(
    item_ids: list[str],
    item_langs: list[str],
    article_vecs,
    story_centroids,
    floor: float = DEFAULT_FLOOR,
    per_lang_floor_delta: dict | None = None,
) -> dict[str, MatchResult]:
    """Batch softmax-argmax assignment.

    article_vecs: (N, D) numpy array, rows ALREADY unit-normalised.
    story_centroids: {story_key: (D,) array, unit-normalised}.

    Returns {article_id: MatchResult}. Articles with argmax_cosine below
    floor (after per-lang adjustment) get story_key=None.
    """
    import numpy as np  # type: ignore

    keys = sorted(story_centroids)
    if not keys:
        return {aid: MatchResult(None, 0.0, 0.0, None, 0.0)
                for aid in item_ids}
    centroid_matrix = np.stack([story_centroids[k] for k in keys])  # (S, D)
    # cosine = vecs @ centroid_matrix.T → (N, S) since both unit-normed
    scores = article_vecs @ centroid_matrix.T

    # Softmax per row (temperature=1.0 — exploratory; could be tuned)
    exp_scores = np.exp(scores - scores.max(axis=1, keepdims=True))
    softmax = exp_scores / exp_scores.sum(axis=1, keepdims=True)

    # Argmax + scores
    argmax_idx = scores.argmax(axis=1)
    argmax_cos = scores[np.arange(len(scores)), argmax_idx]
    argmax_sm = softmax[np.arange(len(softmax)), argmax_idx]
    # Second-best for downstream auditing
    masked = scores.copy()
    masked[np.arange(len(scores)), argmax_idx] = -np.inf
    second_idx = masked.argmax(axis=1)
    second_cos = scores[np.arange(len(scores)), second_idx]

    out: dict[str, MatchResult] = {}
    for i, aid in enumerate(item_ids):
        sk = keys[int(argmax_idx[i])]
        effective_floor = floor
        if per_lang_floor_delta is not None:
            delta = (per_lang_floor_delta.get(sk) or {}).get(item_langs[i], 0.0)
            effective_floor = floor + delta
        if float(argmax_cos[i]) < effective_floor:
            out[aid] = MatchResult(None, float(argmax_cos[i]), float(argmax_sm[i]),
                                   keys[int(second_idx[i])],
                                   float(second_cos[i]))
        else:
            out[aid] = MatchResult(sk, float(argmax_cos[i]), float(argmax_sm[i]),
                                   keys[int(second_idx[i])],
                                   float(second_cos[i]))
    return out


def load_embedding_cache(
    date: str, cache_dir: Path | None = None
) -> tuple[list[str], "np.ndarray"] | None:
    """Load article embedding cache for a date. Returns (ids, vecs) or None
    if missing. Cache lives at snapshots/<DATE>_embeddings.{npy,ids.json}.

    Cache format: numpy .npy matrix paired with a JSON id list. The .npy
    is excluded from git (.gitignore) since it's ~30MB/day; CI regenerates
    fresh each cron via pipeline/embed_articles.py. Local re-runs reuse
    when present."""
    import numpy as np  # type: ignore

    cache_dir = cache_dir or (meta.REPO_ROOT / "snapshots")
    vec_path = cache_dir / f"{date}_embeddings.npy"
    id_path = cache_dir / f"{date}_embedding_ids.json"
    if not vec_path.exists() or not id_path.exists():
        return None
    vecs = np.load(vec_path)
    ids = json.loads(id_path.read_text(encoding="utf-8"))
    if len(ids) != vecs.shape[0]:
        # Cache is corrupt; let caller re-encode.
        return None
    return ids, vecs


def model_input_prefix(model_id: str) -> str:
    """Return the model-specific input prefix string.

    e5-family models expect "passage: " or "query: " on inputs;
    LaBSE / BGE-M3 expect raw text.
    """
    if "e5" in model_id.lower():
        return "passage: "
    return ""
