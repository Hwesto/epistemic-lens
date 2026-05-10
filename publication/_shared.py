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
from pathlib import Path
from typing import Iterable

import meta

ROOT = meta.REPO_ROOT
BRIEFINGS = ROOT / "briefings"
SCHEMAS = ROOT / "docs" / "api" / "schema"

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


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
# Schema validation
# ---------------------------------------------------------------------------

def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def validate_against_schema(data: dict, schema_name: str) -> None:
    """Raise ValueError if `data` doesn't match `<schema_name>.schema.json`.

    Fails closed so a malformed draft cannot be written. If jsonschema
    isn't installed, raises — schema validation is a hard requirement of
    the publication path.
    """
    if not HAS_JSONSCHEMA:
        raise RuntimeError(
            "jsonschema is required for renderer validation but is not "
            "installed. Run: pip install jsonschema"
        )
    schema = _load_schema(schema_name)
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        raise ValueError(
            f"{schema_name} draft failed schema: {e.message} "
            f"(at {'/'.join(str(p) for p in e.absolute_path) or '<root>'})"
        ) from e


# ---------------------------------------------------------------------------
# Long-form: every inline [text](url) must appear in sources[].
# ---------------------------------------------------------------------------

_MD_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")


def long_link_audit(draft: dict) -> list[str]:
    """Return a list of error strings for any inline link in body_md whose
    URL doesn't appear in sources[]. Empty list = clean."""
    body = draft.get("body_md", "")
    sources: Iterable[dict] = draft.get("sources") or []
    declared = {s.get("url") for s in sources if s.get("url")}
    errors: list[str] = []
    for url in _MD_LINK_RE.findall(body):
        if url not in declared:
            errors.append(f"link {url!r} in body_md is not in sources[]")
    return errors
