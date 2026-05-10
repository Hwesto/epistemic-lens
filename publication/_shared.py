"""Shared helpers for the publication renderers.

Both render_thread.py and render_carousel.py read briefings, look up
corpus sources by signal_text_idx, truncate text to a hard char ceiling,
and pick the same "hero" finding (paradox > isolation > exclusive vocab >
generic) as the lead. Keeping those four behaviours in one place stops
the two renderers (and the frontend's hero-pick logic in web/app.js)
from drifting apart.

Also provides a thin jsonschema wrapper so every renderer fails closed
on a schema mismatch instead of silently emitting a malformed draft.
"""
from __future__ import annotations

import json
import re
from typing import Iterable

import meta
# Re-export the shared schema validator so renderers can import it from
# the publication-shared module without depending on the meta module
# directly. Kept as `validate_against_schema` for back-compat with
# existing renderer call sites.
from meta import validate_schema as validate_against_schema  # noqa: F401

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"


# ---------------------------------------------------------------------------
# Briefing / corpus helpers
# ---------------------------------------------------------------------------

def load_briefing(date: str, story_key: str) -> dict:
    return json.loads(
        (BRIEFINGS / f"{date}_{story_key}.json").read_text(encoding="utf-8")
    )


def corpus_source(briefing: dict, idx: int) -> dict | None:
    """Return {bucket, url, outlet} for briefing.corpus[idx], or None."""
    corpus = briefing.get("corpus", [])
    if not (0 <= idx < len(corpus)):
        return None
    e = corpus[idx]
    url = e.get("link") or ""
    if not url:
        return None
    return {"bucket": e.get("bucket", ""), "url": url, "outlet": e.get("feed", "")}


def truncate(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Hero pick — single source for both render_thread.py and render_carousel.py.
# Frontend (web/app.js) mirrors this priority order; if you change it here,
# update the JS too.
# ---------------------------------------------------------------------------

ISOLATION_HERO_THRESHOLD = 0.05  # mean_jaccard below this counts as "isolated"


def pick_hero(analysis: dict) -> dict:
    """Return the strongest finding for the lead post.

    Output shape:
        {"kind": "paradox"|"isolation"|"exclusive_vocab"|"generic", ...payload}
    Payload fields differ by kind; callers pattern-match on `kind`.
    """
    p = analysis.get("paradox")
    if p:
        return {"kind": "paradox", "paradox": p}

    iso = analysis.get("isolation_top") or []
    if iso and iso[0].get("mean_jaccard", 1) < ISOLATION_HERO_THRESHOLD:
        return {"kind": "isolation", "top": iso[0]}

    excl = analysis.get("exclusive_vocab_highlights") or []
    if excl:
        return {"kind": "exclusive_vocab", "top": excl[0]}

    return {"kind": "generic"}


# ---------------------------------------------------------------------------
# Long-form: every inline [text](url) must appear in sources[].
# ---------------------------------------------------------------------------

_MD_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")


def long_link_audit(draft: dict, briefing: dict | None = None) -> list[str]:
    """Return a list of error strings for citation drift in a long-form draft.

    Checks (in order):
      1. Every inline link in body_md must appear in sources[].
      2. If briefing supplied: every sources[].url must appear in the
         briefing's corpus[].link. Catches fabricated URLs that are
         self-consistent within the draft (cited in body and listed in
         sources) but never actually came from the source material.

    Empty list = clean."""
    body = draft.get("body_md", "")
    sources: Iterable[dict] = draft.get("sources") or []
    declared = {s.get("url") for s in sources if s.get("url")}
    errors: list[str] = []
    for url in _MD_LINK_RE.findall(body):
        if url not in declared:
            errors.append(f"link {url!r} in body_md is not in sources[]")

    if briefing is not None:
        corpus_urls = {
            c.get("link") for c in (briefing.get("corpus") or [])
            if c.get("link")
        }
        for s in sources:
            url = s.get("url")
            if url and url not in corpus_urls:
                errors.append(
                    f"sources[] url {url!r} is not in briefing corpus[].link "
                    f"(fabricated or off-corpus)"
                )

    return errors
