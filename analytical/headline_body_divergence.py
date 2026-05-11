"""headline_body_divergence.py — sensationalism index per outlet/bucket.

For each story with both a body analysis (`analyses/<DATE>_<story>.json`)
and a headline-only analysis (`analyses/<DATE>_<story>_headline.json`),
compute per-bucket frame agreement: did the headline carry the same
dominant `frame_id` as the body? Per-bucket disagreement = sensationalism.

The "body" frame here is whichever frame's `buckets` list includes that
bucket. If the bucket appears in multiple frames, the dominant body frame
for that bucket is the one with the most evidence entries citing
`signal_text_idx` from that bucket.

The "headline" frame is computed identically against the headline analysis.

Output: `analyses/<DATE>_<story>_divergence.json`, schema:

    {
      "story_key", "date", "meta_version",
      "n_buckets_compared": int,
      "n_bucket_agreements": int,
      "agreement_rate": float,
      "by_bucket": {
        "<bucket>": {
          "body_frame": "frame_id" | null,
          "headline_frame": "frame_id" | null,
          "agree": bool
        }
      },
      "highest_diverging_buckets": [
        {"bucket", "body_frame", "headline_frame"}, ...
      ]
    }

Skips silently with `skipped: no_headline_pass_yet` if the headline JSON
hasn't been produced for that story (e.g. the cron sub-step hasn't run).

Usage:
  python -m analytical.headline_body_divergence
  python -m analytical.headline_body_divergence --date 2026-05-08
  python -m analytical.headline_body_divergence --analysis analyses/<file>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
ANALYSES = ROOT / "analyses"


def _frame_key(frame: dict) -> str:
    return (frame.get("frame_id") or frame.get("label") or "UNLABELED").strip()


def dominant_frame_per_bucket(analysis: dict) -> dict[str, str]:
    """For each bucket, return the frame_id that dominates that bucket's coverage.

    Dominance rule:
      - count evidence entries per (bucket, frame_id);
      - if no evidence overlap, fall back to first frame whose `buckets` list
        contains the bucket;
      - if still nothing, bucket is unmapped.
    """
    if not analysis or not analysis.get("frames"):
        return {}
    # Per-(bucket, frame) evidence count
    by_bucket_frame: dict[tuple[str, str], int] = Counter()
    for f in analysis["frames"]:
        fid = _frame_key(f)
        for ev in (f.get("evidence") or []):
            b = ev.get("bucket")
            if b:
                by_bucket_frame[(b, fid)] += 1
    # Dominant per bucket from evidence
    by_bucket: dict[str, str] = {}
    for (b, fid), n in by_bucket_frame.items():
        prev = by_bucket.get(b)
        if prev is None:
            by_bucket[b] = fid
        else:
            # Compare counts; ties broken by earlier frame_id
            prev_n = by_bucket_frame[(b, prev)]
            if n > prev_n:
                by_bucket[b] = fid
    # Buckets with NO evidence: fall back to first frame listing them
    for f in analysis["frames"]:
        fid = _frame_key(f)
        for b in (f.get("buckets") or []):
            if b not in by_bucket:
                by_bucket[b] = fid
    return by_bucket


def divergence(body: dict, headline: dict) -> dict:
    """Compute per-bucket frame agreement between body and headline analyses."""
    body_dom = dominant_frame_per_bucket(body)
    head_dom = dominant_frame_per_bucket(headline)
    all_buckets = set(body_dom) | set(head_dom)
    by_bucket: dict[str, dict] = {}
    n_compared = 0
    n_agree = 0
    for b in sorted(all_buckets):
        bf = body_dom.get(b)
        hf = head_dom.get(b)
        agree = (bf is not None and hf is not None and bf == hf)
        if bf is not None and hf is not None:
            n_compared += 1
            if agree:
                n_agree += 1
        by_bucket[b] = {
            "body_frame": bf,
            "headline_frame": hf,
            "agree": agree,
        }
    diverging = [
        {"bucket": b, "body_frame": v["body_frame"],
         "headline_frame": v["headline_frame"]}
        for b, v in by_bucket.items()
        if v["body_frame"] is not None and v["headline_frame"] is not None
        and not v["agree"]
    ]
    return {
        "n_buckets_compared": n_compared,
        "n_bucket_agreements": n_agree,
        "agreement_rate": (round(n_agree / n_compared, 3)
                           if n_compared else None),
        "by_bucket": by_bucket,
        "highest_diverging_buckets": diverging,
    }


def process_one(body_path: Path, headline_path: Path | None = None,
                 out_dir: Path = ANALYSES) -> dict:
    """Compute divergence for one story; write `<stem>_divergence.json`."""
    if not body_path.exists():
        return {"skipped": True, "reason": "no_body_analysis", "path": str(body_path)}
    body = json.loads(body_path.read_text(encoding="utf-8"))

    if headline_path is None:
        # Convention: <stem>_headline.json sibling
        headline_path = body_path.with_name(body_path.stem + "_headline.json")
    if not headline_path.exists():
        return {"skipped": True, "reason": "no_headline_pass_yet",
                "expected_at": str(headline_path),
                "story_key": body.get("story_key")}

    headline = json.loads(headline_path.read_text(encoding="utf-8"))
    div = divergence(body, headline)
    out = meta.stamp({
        "story_key": body.get("story_key"),
        "date": body.get("date"),
        "story_title": body.get("story_title"),
        **div,
    })
    out_path = out_dir / f"{body_path.stem}_divergence.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None)
    ap.add_argument("--analysis", default=None,
                    help="Body analysis JSON (default: all today's bodies).")
    ap.add_argument("--out-dir", default=str(ANALYSES))
    args = ap.parse_args()

    if args.analysis:
        targets = [Path(args.analysis)]
    else:
        date = args.date or datetime.now(timezone.utc).date().isoformat()
        targets = [
            p for p in ANALYSES.glob(f"{date}_*.json")
            if not p.stem.endswith(("_headline", "_divergence"))
        ]
    if not targets:
        print("No body analyses to process.", file=sys.stderr)
        return 0

    out_dir = Path(args.out_dir)
    n_done = 0
    n_skipped = 0
    for p in targets:
        r = process_one(p, out_dir=out_dir)
        if r.get("skipped"):
            print(f"  - {p.stem:50s} skipped: {r['reason']}")
            n_skipped += 1
        else:
            rate = r.get("agreement_rate")
            n_compared = r.get("n_buckets_compared", 0)
            n_diverging = len(r.get("highest_diverging_buckets", []))
            print(f"  ✓ {p.stem:50s} compared={n_compared}  agree_rate={rate}  diverging={n_diverging}")
            n_done += 1
    print(f"\n{n_done} done, {n_skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
