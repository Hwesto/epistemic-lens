"""meta.py — single source of truth for the methodology pin.

Reads meta_version.json and exports every constant that affects analytical
output: tokenizer rules, stopwords, embedding model, clustering thresholds,
extraction limits, signal_text fallback rules, canonical story patterns,
and the Claude model + prompt set used by the analyze/draft jobs.

Any script that reads feeds, tokenises text, computes metrics, runs the
embedding model, or invokes Claude should `from meta import ...` rather
than hardcoding constants. That way one version bump in meta_version.json
moves the whole pipeline atomically.

`assert_pinned()` re-hashes the pinned input files (feeds.json,
stopwords.txt, canonical_stories.json, .claude/prompts/) and raises if
they've drifted from the declared hashes. CI runs this on every PR.

`stamp(artifact)` embeds `meta_version` at the top of any dict before
it's written to disk, so longitudinal consumers can always tell which
era an artifact belongs to.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent
META_PATH = ROOT / "meta_version.json"
STOPWORDS_PATH = ROOT / "stopwords.txt"
CANONICAL_STORIES_PATH = ROOT / "canonical_stories.json"
FEEDS_PATH = ROOT / "feeds.json"
PROMPTS_DIR = ROOT / ".claude" / "prompts"

# Public alias used by scripts that have moved into subdirectories
# (pipeline/, analytical/, publication/, video/). Their own
# Path(__file__).parent points at the subdir, not the repo root, so
# they read REPO_ROOT from here as the single source of truth.
REPO_ROOT = ROOT


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def dir_hash(path: Path, glob: str = "*.md") -> str:
    """Hash files under a directory, sorted by path for determinism."""
    h = hashlib.sha256()
    for p in sorted(path.glob(glob)):
        if not p.is_file():
            continue
        h.update(p.relative_to(path).as_posix().encode() + b"\n")
        h.update(p.read_bytes())
        h.update(b"\n--\n")
    return f"sha256:{h.hexdigest()}"


# Fields excluded from the self-hash. Everything else inside meta_version.json
# (every threshold, every nested config sub-tree, every embedded hash) is
# covered, so a hand-edit of any pinned value without re-running
# baseline_pin.py is detected by assert_pinned() at CI time.
_PIN_SELF_HASH_EXCLUDE = (
    "_doc",
    "meta_version",
    "pinned_at",
    "pin_reason",
    "pin_self_hash",
)


def pin_self_hash_of(d: dict) -> str:
    """SHA-256 of the pin's value content, excluding identity / commentary
    fields. Used by baseline_pin.py to write the hash and by assert_pinned()
    to verify nobody hand-edited a threshold without bumping the version."""
    payload = {k: v for k, v in d.items() if k not in _PIN_SELF_HASH_EXCLUDE}
    serialised = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256()
    h.update(serialised.encode("utf-8"))
    return f"sha256:{h.hexdigest()}"


def pin_self_hash() -> str:
    """Self-hash of the loaded methodology pin."""
    return pin_self_hash_of(META)


@lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(META_PATH.read_text(encoding="utf-8"))


META = _load()
VERSION: str = META["meta_version"]

# Configuration sub-trees (see meta_version.json for the live values).
TOKENIZER = META["tokenizer"]
EMBEDDING = META["embedding"]
CLUSTERING = META["clustering"]
METRICS = META["metrics"]
EXTRACTION = META["extraction"]
INGEST = META["ingest"]
SIGNAL_TEXT = META["signal_text"]
BRIEFING = META["briefing"]
CLAUDE = META["claude"]
FEEDS_META = META["feeds"]
HEALTH = META["health"]
FEED_ROT = META["feed_rot"]


@lru_cache(maxsize=1)
def stopwords() -> frozenset[str]:
    """Tokenised stopword set. Comment lines and blanks are ignored."""
    out: set[str] = set()
    for raw in STOPWORDS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        out.update(w.lower() for w in line.split())
    return frozenset(out)


@lru_cache(maxsize=1)
def canonical_stories() -> dict:
    """Compiled story-group definitions for build_briefing.py."""
    raw = json.loads(CANONICAL_STORIES_PATH.read_text(encoding="utf-8"))
    return raw["stories"]


# Tokenisation primitives — kept here so build_metrics, build_briefing, and
# any future analytical script use the same regex + normalization rules.
_TOKEN_RE = re.compile(TOKENIZER["regex"])
_PLURAL_SUFFIXES = tuple(TOKENIZER["plural_suffixes"])
_MIN_LEN = int(TOKENIZER["min_token_length"])


def normalize_token(tok: str) -> str:
    """Lowercase + light-touch plural normalization."""
    tok = tok.lower()
    if len(tok) > _MIN_LEN:
        for suf in _PLURAL_SUFFIXES:
            if tok.endswith(suf) and len(tok) - len(suf) >= _MIN_LEN:
                return tok[: -len(suf)]
    return tok


def tokenize(text: str) -> list[str]:
    """Tokenize text using the pinned regex + stopword filter + normalization.

    Returns a list (not Counter) — callers that need counts can wrap with
    Counter themselves; callers that need sets just `set()` the result.
    """
    if not text:
        return []
    stop = stopwords()
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        n = normalize_token(raw)
        if len(n) < _MIN_LEN or n in stop:
            continue
        out.append(n)
    return out


def assert_pinned(strict: bool = True) -> dict[str, tuple[str, str]]:
    """Verify on-disk inputs match meta_version.json's declared hashes.

    Returns {key: (declared, actual)} for any mismatches. Raises
    RuntimeError if strict and there are mismatches.
    """
    drift: dict[str, tuple[str, str]] = {}

    declared = FEEDS_META.get("hash")
    if declared:
        actual = file_hash(FEEDS_PATH)
        if declared != actual:
            drift["feeds"] = (declared, actual)

    declared = TOKENIZER.get("stopwords_hash")
    if declared:
        actual = file_hash(STOPWORDS_PATH)
        if declared != actual:
            drift["tokenizer.stopwords"] = (declared, actual)

    declared = META.get("canonical_stories_hash")
    if declared and CANONICAL_STORIES_PATH.exists():
        actual = file_hash(CANONICAL_STORIES_PATH)
        if declared != actual:
            drift["canonical_stories"] = (declared, actual)

    declared = CLAUDE.get("prompts_hash")
    if declared and PROMPTS_DIR.exists():
        actual = dir_hash(PROMPTS_DIR)
        if declared != actual:
            drift["claude.prompts"] = (declared, actual)

    # Self-hash: catches edits to any pinned value inside meta_version.json
    # that didn't go through baseline_pin.py --bump. The four hashes above
    # only check the external pinned files; this one closes the gap for
    # values that live inside the pin itself (thresholds, model names,
    # cluster knobs, etc).
    declared_self = META.get("pin_self_hash")
    actual_self = pin_self_hash()
    if declared_self is None:
        drift["pin_self_hash"] = ("(missing — run baseline_pin.py --bump)", actual_self)
    elif declared_self != actual_self:
        drift["pin_self_hash"] = (declared_self, actual_self)

    if drift and strict:
        lines = ["Methodology drift detected (meta_version=" + VERSION + "):"]
        for k, (dec, act) in drift.items():
            lines.append(f"  {k}:")
            lines.append(f"    declared: {dec}")
            lines.append(f"    actual:   {act}")
        lines.append("")
        lines.append("Either revert your changes, or bump meta_version.json:")
        lines.append("  python baseline_pin.py --bump <patch|minor|major> --reason '...'")
        raise RuntimeError("\n".join(lines))
    return drift


def stamp(artifact: dict) -> dict:
    """Embed `meta_version` at the top of an artifact dict, in-place."""
    artifact["meta_version"] = VERSION
    return artifact


# ---------------------------------------------------------------------------
# Schema validation — shared utility used by the publication renderers and
# the pipeline observability layer. Each schema lives at
# docs/api/schema/<name>.schema.json. This wrapper fails closed so a
# malformed artifact cannot be written.
# ---------------------------------------------------------------------------

SCHEMAS_DIR = ROOT / "docs" / "api" / "schema"


def load_schema(name: str) -> dict:
    """Load `docs/api/schema/<name>.schema.json` as a parsed dict."""
    return json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def validate_schema(data: dict, schema_name: str) -> None:
    """Validate `data` against `<schema_name>.schema.json`.

    Raises ValueError on schema mismatch, RuntimeError if jsonschema is
    missing (hard dependency for the renderer + observability paths).
    """
    try:
        import jsonschema
    except ImportError as e:
        raise RuntimeError(
            "jsonschema is required for schema validation but is not "
            "installed. Run: pip install jsonschema"
        ) from e
    try:
        jsonschema.validate(instance=data, schema=load_schema(schema_name))
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise ValueError(
            f"{schema_name} failed schema: {e.message} (at {path})"
        ) from e


def fingerprint() -> dict:
    """Compact summary suitable for logging or job-summary lines."""
    return {
        "meta_version": VERSION,
        "feeds_count": FEEDS_META.get("n_feeds"),
        "embedding_model": EMBEDDING.get("model"),
        "claude_model": CLAUDE.get("model"),
    }


if __name__ == "__main__":
    import sys

    try:
        assert_pinned(strict=True)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    print(f"meta pinned OK — version {VERSION}")
    for k, v in fingerprint().items():
        print(f"  {k}: {v}")
