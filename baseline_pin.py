"""baseline_pin.py — bump the methodology pin in meta_version.json.

Run when you've intentionally changed something that affects analytical
output: added/removed a feed, edited stopwords, changed a canonical story
pattern, swapped the embedding model, edited a Claude prompt. Recomputes
the hashes for every pinned input and writes them back into
meta_version.json with a bumped version number and a reason string.

Usage
  python baseline_pin.py --check
      Report drift between live files and meta_version.json. Exit 1 if any
      mismatch. Used by CI; safe to run any time.

  python baseline_pin.py --bump patch
      1.0.0 -> 1.0.1. For changes that don't affect analytical output
      (logging, refactors, comments).

  python baseline_pin.py --bump minor --reason "added 'gaza_ceasefire' canonical story"
      1.0.0 -> 1.1.0. Forward-compatible (added story, added feed,
      added a metric). Existing artifacts remain valid.

  python baseline_pin.py --bump major --reason "switched embedding model"
      1.0.0 -> 2.0.0. Invalidates longitudinal comparisons. Past data
      stays valid only under its meta-v1.x tag.

After --bump succeeds, tag the repo:
    git tag meta-v$(jq -r .meta_version meta_version.json)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta as M

ROOT = Path(__file__).parent
META_PATH = ROOT / "meta_version.json"

LEVELS = ("patch", "minor", "major")


def bump_version(current: str, level: str) -> str:
    parts = [int(x) for x in current.split(".")]
    while len(parts) < 3:
        parts.append(0)
    if level == "major":
        parts = [parts[0] + 1, 0, 0]
    elif level == "minor":
        parts = [parts[0], parts[1] + 1, 0]
    elif level == "patch":
        parts[2] += 1
    else:
        raise ValueError(f"unknown level: {level}")
    return ".".join(str(p) for p in parts)


def recompute_hashes(meta: dict) -> dict:
    """Update every hash field in meta from the live files."""
    meta["feeds"]["hash"] = M.file_hash(M.FEEDS_PATH)
    meta["tokenizer"]["stopwords_hash"] = M.file_hash(M.STOPWORDS_PATH)
    if M.CANONICAL_STORIES_PATH.exists():
        meta["canonical_stories_hash"] = M.file_hash(M.CANONICAL_STORIES_PATH)
    if M.FRAMES_CODEBOOK_PATH.exists():
        meta["frames_codebook_hash"] = M.file_hash(M.FRAMES_CODEBOOK_PATH)
    if M.BUCKET_QUALITY_PATH.exists():
        meta["bucket_quality_hash"] = M.file_hash(M.BUCKET_QUALITY_PATH)
    if M.BUCKET_WEIGHTS_PATH.exists():
        meta["bucket_weights_hash"] = M.file_hash(M.BUCKET_WEIGHTS_PATH)
    if M.CARD_PICKER_PATH.exists():
        meta["card_picker_hash"] = M.file_hash(M.CARD_PICKER_PATH)
    if M.TODAY_PICKER_PATH.exists():
        meta["today_picker_hash"] = M.file_hash(M.TODAY_PICKER_PATH)
    if M.PROMPTS_DIR.exists():
        meta["claude"]["prompts_hash"] = M.dir_hash(M.PROMPTS_DIR)
    if M.SCHEMAS_DIR.exists():
        meta["schemas_hash"] = M.dir_hash(M.SCHEMAS_DIR, "*.json")

    # Refresh feed counts so the human-readable summary stays accurate.
    feeds_doc = json.loads(M.FEEDS_PATH.read_text(encoding="utf-8"))
    if isinstance(feeds_doc, dict) and "countries" in feeds_doc:
        meta["feeds"]["n_buckets"] = len(feeds_doc["countries"])
        meta["feeds"]["n_feeds"] = sum(
            len(v.get("feeds", [])) for v in feeds_doc["countries"].values()
        )
    # NOTE: pin_self_hash is NOT computed here. It's computed in
    # cmd_bump() AFTER meta_version / pinned_at / pin_reason are
    # written — otherwise the self-hash signs a stale config.
    return meta


def cmd_check() -> int:
    drift = M.assert_pinned(strict=False)
    if not drift:
        print(f"OK: meta_version={M.VERSION}, all pinned inputs match.")
        return 0
    print(f"DRIFT: meta_version={M.VERSION} declares hashes that no longer match:")
    for k, (declared, actual) in drift.items():
        print(f"  {k}:")
        print(f"    declared: {declared}")
        print(f"    actual:   {actual}")
    print("")
    print("If the change was intentional, bump the pin:")
    print("  python baseline_pin.py --bump <patch|minor|major> --reason '...'")
    return 1


def cmd_bump(level: str, reason: str | None) -> int:
    if level == "major" and not reason:
        print("ERROR: major bumps require --reason (it's a longitudinal break).",
              file=sys.stderr)
        return 1

    raw = json.loads(META_PATH.read_text(encoding="utf-8"))
    old_version = raw["meta_version"]
    new_version = bump_version(old_version, level)

    # Re-hash everything against current files.
    raw = recompute_hashes(raw)
    raw["meta_version"] = new_version
    raw["pinned_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if reason:
        raw["pin_reason"] = reason

    # Preserve `_doc` field at the top of the file by re-emitting in the
    # canonical key order.
    canonical_order = [
        "_doc", "meta_version", "pinned_at", "pin_reason",
        "feeds", "tokenizer", "embedding", "clustering", "metrics",
        "extraction", "ingest", "signal_text", "canonical_stories_hash",
        "frames_codebook_hash", "bucket_quality_hash", "bucket_weights_hash",
        "card_picker_hash", "today_picker_hash",
        "schemas_hash", "claude",
    ]
    ordered = {k: raw[k] for k in canonical_order if k in raw}
    for k, v in raw.items():
        if k not in ordered:
            ordered[k] = v

    # Self-hash signs the FINAL ordered dict. Must run after every
    # mutation above (meta_version / pinned_at / pin_reason / hash
    # refreshes) so it covers the actual on-disk content.
    ordered["pin_self_hash"] = M.compute_pin_self_hash(ordered)

    META_PATH.write_text(
        json.dumps(ordered, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"meta_version: {old_version} -> {new_version}")
    if reason:
        print(f"reason: {reason}")
    print("")
    print("Next steps:")
    print(f"  git add meta_version.json")
    print(f"  git commit -m 'meta: bump to {new_version} — {reason or level}'")
    print(f"  git tag meta-v{new_version}")
    print(f"  git push --follow-tags")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="report drift; exit 1 if any. Used by CI.")
    ap.add_argument("--bump", choices=LEVELS,
                    help="bump the version and re-hash all pinned inputs.")
    ap.add_argument("--reason", type=str, default=None,
                    help="why you're bumping. Required for --bump major.")
    args = ap.parse_args()

    if args.check and args.bump:
        ap.error("--check and --bump are mutually exclusive")
    if not (args.check or args.bump):
        ap.error("must pass --check or --bump")

    if args.check:
        return cmd_check()
    return cmd_bump(args.bump, args.reason)


if __name__ == "__main__":
    sys.exit(main())
