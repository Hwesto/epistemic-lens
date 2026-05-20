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
import os
import re as _stdlib_re
from functools import lru_cache
from pathlib import Path

try:
    import regex as _re  # Unicode-aware: supports \p{L} property escapes.
    _REGEX_LIB_AVAILABLE = True
except ImportError:  # pragma: no cover
    _re = _stdlib_re
    _REGEX_LIB_AVAILABLE = False

# v10 layout: meta.py lives at core/meta.py; config files at core/config/;
# data dirs at data/; publish artefacts at publish/; tests at tests/.
# REPO_ROOT is the actual repo root (one level up from core/).
REPO_ROOT = Path(__file__).parent.parent
ROOT = REPO_ROOT  # legacy alias for existing call sites
CONFIG_DIR = REPO_ROOT / "core" / "config"
META_PATH = CONFIG_DIR / "meta_version.json"
STOPWORDS_PATH = CONFIG_DIR / "stopwords.txt"
# v10: canonical_stories.json + bucket_* configs are LEGACY. Retained for
# v9 → v10 transition only (D.2/D.3 stop reading them). The new sources
# of truth are outlets.json + country_weights.json + outlet_quality.json.
CANONICAL_STORIES_PATH = CONFIG_DIR / "canonical_stories.json"  # LEGACY
FRAMES_CODEBOOK_PATH = CONFIG_DIR / "frames_codebook.json"
BUCKET_QUALITY_PATH = CONFIG_DIR / "bucket_quality.json"  # LEGACY
BUCKET_WEIGHTS_PATH = CONFIG_DIR / "bucket_weights.json"  # LEGACY
FEEDS_PATH = CONFIG_DIR / "feeds.json"                    # ingest config (nested by country)
# v10 outlet-first config:
OUTLETS_PATH = CONFIG_DIR / "outlets.json"
COUNTRY_WEIGHTS_PATH = CONFIG_DIR / "country_weights.json"
OUTLET_QUALITY_PATH = CONFIG_DIR / "outlet_quality.json"
# Picker config still lives in publish/ since it's a render-layer concern
CARD_PICKER_PATH = REPO_ROOT / "publish" / "api" / "card_picker.json"
TODAY_PICKER_PATH = REPO_ROOT / "publish" / "api" / "today_picker.json"
# Prompts split: core/analyze for analytical prompts; publish/render for draft prompts
PROMPTS_DIR = REPO_ROOT / "core" / "analyze" / "prompts"
PUBLISH_PROMPTS_DIR = REPO_ROOT / "publish" / "render" / "prompts"
# JSON schemas served from /api/schema/ live in publish/api/schemas/
SCHEMAS_DIR = REPO_ROOT / "publish" / "api" / "schemas"
# Runtime data dirs all under data/
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
BRIEFINGS_DIR = REPO_ROOT / "data" / "briefings"
ANALYSES_DIR = REPO_ROOT / "data" / "analyses"
SOURCES_DIR = REPO_ROOT / "data" / "sources"
DRAFTS_DIR = REPO_ROOT / "data" / "drafts"
COVERAGE_DIR = REPO_ROOT / "data" / "coverage"
TRAJECTORY_DIR = REPO_ROOT / "data" / "trajectory"
BASELINE_DIR = REPO_ROOT / "data" / "baseline"
TILT_DIR = REPO_ROOT / "data" / "tilt"
LAG_DIR = REPO_ROOT / "data" / "lag"
ROBUSTNESS_DIR = REPO_ROOT / "data" / "robustness"
DISTRIBUTION_PENDING_DIR = REPO_ROOT / "data" / "distribution_pending"
ARCHIVE_DIR = REPO_ROOT / "data" / "archive"


def latest_snapshot_date(snap_dir: "Path | None" = None) -> str | None:
    """Most recent YYYY-MM-DD that has a raw snapshot file in data/snapshots/.

    The stem must be EXACTLY a date. This is the single source of truth for
    "which day are we processing" — using a date-strict match (not a
    blocklist of suffixes) means sibling artefacts that share the date
    prefix — `<date>_embeddings`, `<date>_embedding_ids`, `<date>_clusters`,
    `<date>_top_clusters`, `<date>_health`, `<date>_dedup`, `<date>_convergence`,
    … — can never be mistaken for a snapshot and yield a bogus date string.
    """
    snap_dir = snap_dir or SNAPSHOTS_DIR
    dates = sorted(
        p.stem for p in snap_dir.glob("[0-9][0-9][0-9][0-9]-*.json")
        if _stdlib_re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)
    )
    return dates[-1] if dates else None


def embedding_model() -> str:
    """The sentence-embedding model id for the daily clustering cache.

    Pinned in meta_version.json (`perception.embedding_model`); the
    `EMBEDDING_MODEL` environment variable overrides it for local testing
    or model experiments without a pin bump. core/embed/encode.py,
    core/cluster/cluster_daily.py and core/briefing/build.py all read this
    one function, so the versioned article_id cache key stays consistent
    across the three within a single run.
    """
    return os.environ.get("EMBEDDING_MODEL") or (
        PERCEPTION.get("embedding_model") or "")


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


def compute_pin_self_hash(meta_dict: dict) -> str:
    """Tamper-evidence for meta_version.json itself.

    Hashes the entire pinned config minus the `pin_self_hash` field
    (chicken-and-egg). Hand-editing any field — pin_reason, pinned_at,
    any *_hash, any nested config — without rerunning
    `baseline_pin.py --bump` produces a mismatch that
    `assert_pinned()` raises on.

    Without this, the audit's per-input-file hashes only catch drift
    in the *referenced* files. They can't catch a hand-edit to
    meta_version.json that, say, shuffles `prompts_hash` to a stale
    value or rewrites `pin_reason` to lie about what changed.
    """
    sanitized = {k: v for k, v in meta_dict.items() if k != "pin_self_hash"}
    payload = json.dumps(sanitized, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


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
CLAUDE = META["claude"]
FEEDS_META = META["feeds"]
# Embedding config. v10 reads only `embedding_model` + `signal_text_version`
# from this block — they compose into the versioned article_id, so bumping
# either invalidates every embedding-cache key loudly. Read by:
#   - core/embed/encode.py        (model_id + signal_text_version for cache keys)
#   - core/cluster/cluster_daily.py (same, to key the cache it reads back)
#   - core/briefing/build.py      (same, to resolve member articles)
# Empty {} on pins that predate the block, so old artefacts still import cleanly.
PERCEPTION = META.get("perception") or {}


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
    """LEGACY (v9): closed-world story definitions. v10 has no canonical
    set — stories emerge from daily HDBSCAN clustering. Returns empty
    dict when canonical_stories.json is absent (v10 default)."""
    if not CANONICAL_STORIES_PATH.exists():
        return {}
    raw = json.loads(CANONICAL_STORIES_PATH.read_text(encoding="utf-8"))
    return raw.get("stories") or {}


@lru_cache(maxsize=1)
def outlets() -> list[dict]:
    """v10 source of truth: flat list of outlets.

    Each outlet: name, url, lang, country (was bucket), country_label,
    lean, section, status. Some carry optional tags (ownership). Read
    from core/config/outlets.json.

    For consumers wanting the old "buckets" abstraction, use
    `outlets_by_country()` to get the same {country: [outlet_name, ...]}
    grouping. Buckets are no longer an aggregation unit in v10 — they're
    just one of several tags articles carry.
    """
    raw = json.loads(OUTLETS_PATH.read_text(encoding="utf-8"))
    return raw.get("outlets") or []


@lru_cache(maxsize=1)
def outlets_by_country() -> dict[str, list[str]]:
    """{country_key: [outlet_name, ...]} — convenience grouping.
    Replaces _feeds_by_bucket(); same shape."""
    out: dict[str, list[str]] = {}
    for o in outlets():
        out.setdefault(o.get("country", ""), []).append(o.get("name", ""))
    for k in out:
        out[k].sort()
    return out


@lru_cache(maxsize=1)
def outlet_by_name() -> dict[str, dict]:
    """{outlet_name: outlet_dict} for fast metadata lookup."""
    return {o.get("name", ""): o for o in outlets()}


@lru_cache(maxsize=1)
def _feeds_by_bucket() -> dict[str, list[str]]:
    """LEGACY (v9 callers): per-bucket feed names.
    Equivalent to outlets_by_country() — kept as alias during v10
    transition. New code should call outlets_by_country() directly."""
    return outlets_by_country()


def bucket_feed_set_hash(bucket: str) -> str:
    """sha256(:|sorted feed names) per bucket. Phase 3i.

    A bucket's feed set is finer-grained than its key: when a feed is added
    or removed within a bucket, the key stays but the hash changes. Used by
    `analytical/longitudinal.py` to detect sub-bucket drift across days
    that the existing `bucket_set_signature` (over bucket KEYS) misses.
    Returns 16-char hex truncation; collision-resistant for our N.
    """
    import hashlib
    names = _feeds_by_bucket().get(bucket, [])
    s = "|".join(names)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def bucket_feed_set_hashes(buckets: list[str] | None = None) -> dict[str, str]:
    """Return {bucket: feed_set_hash} for the given buckets (default: all)."""
    by = _feeds_by_bucket()
    keys = buckets if buckets is not None else list(by.keys())
    return {b: bucket_feed_set_hash(b) for b in keys}


@lru_cache(maxsize=1)
def outlet_quality_entries() -> dict:
    """Per-outlet (or per-country, mixed) quality tier from outlet_quality.json.
    Entries can be keyed by outlet name (e.g. "google_news_reuters") or by
    country (e.g. "africa"). Empty dict if file absent."""
    if not OUTLET_QUALITY_PATH.exists():
        if BUCKET_QUALITY_PATH.exists():
            # Fallback to legacy bucket_quality.json during v9→v10 transition
            return json.loads(BUCKET_QUALITY_PATH.read_text(encoding="utf-8")).get("buckets") or {}
        return {}
    return json.loads(OUTLET_QUALITY_PATH.read_text(encoding="utf-8")).get("entries") or {}


def is_quant_excluded(key: str) -> bool:
    """True if outlet OR country is tier=EXCLUDE_QUANT (drop from quantitative metrics).
    `key` can be an outlet name or a country code; lookup tries the entry as-is."""
    return outlet_quality_entries().get(key, {}).get("tier") == "EXCLUDE_QUANT"


# Legacy alias (v9 callers used `bucket_quality()`):
def bucket_quality() -> dict:
    """LEGACY: alias for outlet_quality_entries()."""
    return outlet_quality_entries()


@lru_cache(maxsize=1)
def country_weights_table() -> dict:
    """Per-country weighting parameters from country_weights.json."""
    if not COUNTRY_WEIGHTS_PATH.exists():
        if BUCKET_WEIGHTS_PATH.exists():
            # Fallback to legacy bucket_weights.json during v9→v10 transition
            return json.loads(BUCKET_WEIGHTS_PATH.read_text(encoding="utf-8")).get("buckets") or {}
        return {}
    return json.loads(COUNTRY_WEIGHTS_PATH.read_text(encoding="utf-8")).get("countries") or {}


def country_weight(country: str) -> float:
    """Weight for population-weighted aggregates. Defaults to 1.0 for unknowns.

    Formula: population_m * audience_reach (see country_weights.json).
    Returns 0 for countries explicitly weighted to 0 (wires bucket, opinion
    bucket, EXCLUDE_QUANT aggregators) so they don't double-count.
    """
    entry = country_weights_table().get(country)
    if entry is None:
        return 1.0
    pop = float(entry.get("population_m", 0))
    reach = float(entry.get("audience_reach", 0))
    return pop * reach


def country_weight_confidence(country: str) -> str:
    """Returns 'high', 'medium', 'low', or 'unknown'."""
    entry = country_weights_table().get(country)
    if entry is None:
        return "unknown"
    return entry.get("confidence", "unknown")


# Legacy aliases (v9 callers used `bucket_weight` / `bucket_weight_confidence`):
def bucket_weights_table() -> dict:
    """LEGACY: alias for country_weights_table()."""
    return country_weights_table()


def bucket_weight(bucket: str) -> float:
    """LEGACY: alias for country_weight()."""
    return country_weight(bucket)


def bucket_weight_confidence(bucket: str) -> str:
    """LEGACY: alias for country_weight_confidence()."""
    return country_weight_confidence(bucket)


# Tokenisation primitives — kept here so build_metrics, build_briefing, and
# any future analytical script use the same regex + normalization rules.
# Compiled with the `regex` lib when available so Unicode property escapes
# (\p{L}) work. If the pinned regex uses Unicode property escapes and the
# `regex` package is not installed, fail loudly with an actionable message
# instead of crashing inside re.compile() with a cryptic "bad escape \p".
_TOKEN_RE_PATTERN = TOKENIZER["regex"]
if not _REGEX_LIB_AVAILABLE and r"\p" in _TOKEN_RE_PATTERN:
    raise ImportError(
        f"meta.py: pinned tokenizer regex {_TOKEN_RE_PATTERN!r} uses "
        f"Unicode property escapes (\\p{{...}}) that stdlib `re` does not "
        f"support. Install the `regex` package:\n"
        f"    pip install regex"
    )
_TOKEN_RE = _re.compile(_TOKEN_RE_PATTERN)
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

    declared = META.get("frames_codebook_hash")
    if declared and FRAMES_CODEBOOK_PATH.exists():
        actual = file_hash(FRAMES_CODEBOOK_PATH)
        if declared != actual:
            drift["frames_codebook"] = (declared, actual)

    declared = META.get("bucket_quality_hash")
    if declared and BUCKET_QUALITY_PATH.exists():
        actual = file_hash(BUCKET_QUALITY_PATH)
        if declared != actual:
            drift["bucket_quality"] = (declared, actual)

    declared = META.get("bucket_weights_hash")
    if declared and BUCKET_WEIGHTS_PATH.exists():
        actual = file_hash(BUCKET_WEIGHTS_PATH)
        if declared != actual:
            drift["bucket_weights"] = (declared, actual)

    declared = META.get("card_picker_hash")
    if declared and CARD_PICKER_PATH.exists():
        actual = file_hash(CARD_PICKER_PATH)
        if declared != actual:
            drift["card_picker"] = (declared, actual)

    declared = META.get("today_picker_hash")
    if declared and TODAY_PICKER_PATH.exists():
        actual = file_hash(TODAY_PICKER_PATH)
        if declared != actual:
            drift["today_picker"] = (declared, actual)

    declared = CLAUDE.get("prompts_hash")
    if declared and PROMPTS_DIR.exists():
        actual = dir_hash(PROMPTS_DIR)
        if declared != actual:
            drift["claude.prompts"] = (declared, actual)

    declared = META.get("schemas_hash")
    if declared and SCHEMAS_DIR.exists():
        actual = dir_hash(SCHEMAS_DIR, "*.json")
        if declared != actual:
            drift["schemas"] = (declared, actual)

    # Self-tamper-evidence: hand-edits to meta_version.json itself
    # (pin_reason rewrites, hash shuffles, anything not via baseline_pin.py)
    # trigger drift on this check.
    declared = META.get("pin_self_hash")
    if declared:
        actual = compute_pin_self_hash(META)
        if declared != actual:
            drift["pin_self"] = (declared, actual)

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


def load_schema(name: str) -> dict:
    """Load `publish/api/schemas/<name>.schema.json` as a parsed dict."""
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
