"""article_id.py — versioned article identifier.

Used by every script that needs to identify the same article across
runs: embed_articles (writes the cache keyed by article_id), cluster_daily
(subtracts assigned articles from the universe), build_briefing (looks
up an article's cluster assignment).

The ID composes (model_id, signal_text_version, feed_name, link) into
one sha256-12 hash. Bumping the embedding model OR the signal-text
extraction version invalidates every cache key loudly — a stale .npy
cannot silently serve old vectors after a model swap.

Extracted from analytical/perception.py during v10 D.3 since the
perception layer's softmax-argmax matcher retires but article_id is
still needed everywhere downstream.
"""
from __future__ import annotations

import hashlib


def article_id(feed_name: str, link: str, model_id: str,
                signal_text_version: str) -> str:
    """Versioned article ID (12-char hex). Stable across runs as long
    as (model_id, signal_text_version) don't change."""
    key = f"{model_id}|{signal_text_version}|{feed_name}|{link}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def signal_excerpt_for_embedding(item: dict, max_chars: int = 1500) -> str:
    """The text we feed to the embedding model: title + (body | summary | title)
    truncated to max_chars. Mirrors the eval-set construction in
    calibration/build_eval_set.py. Keeping the input identical across
    runs is what makes article_id stable."""
    title = (item.get("title") or "")[:240]
    body = item.get("body_text") or ""
    if len(body) >= 100:
        return title + "\n" + body[:max_chars]
    summary = item.get("summary") or ""
    if len(summary) >= 60:
        return title + "\n" + summary[:max_chars]
    return title


def model_input_prefix(model_id: str) -> str:
    """Model-specific input prefix: e5 wants 'passage: ', others use ''."""
    if "e5" in model_id.lower():
        return "passage: "
    return ""
