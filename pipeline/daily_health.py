"""Post-ingest daily health snapshot.

Run after each ingest + extract. Emits snapshots/<date>_health.json,
the most-consumed sidecar in the pipeline:
  - daily.yml job-summary step parses it into $GITHUB_STEP_SUMMARY
  - pipeline.feed_rot_check aggregates last-7-day error/stub streaks
  - committed to the repo for human review

Reports:
  - errored feeds (http != 200 or transport error)
  - stub-only feeds (>= stub_pct_min items have the is_stub flag)
  - slow feeds (fetch_ms above slow_fetch_ms)
  - items-per-bucket today vs trailing-7-day mean (with volume-drop alert)
  - per-bucket extraction success rate (with low_extraction alert)
  - aggregate extraction totals + FULL%

Alert thresholds are pinned in meta_version.json under "health".
Output shape is pinned by docs/api/schema/health.schema.json and
validated before write so a typo here can't silently break the
downstream consumers.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

import meta

ROOT = meta.REPO_ROOT
SNAPS = ROOT / "snapshots"

_STUB_PCT_MIN = float(meta.HEALTH["stub_pct_min"])
_SLOW_FETCH_MS = int(meta.HEALTH["slow_fetch_ms"])
_VOLUME_DROP_FACTOR = float(meta.HEALTH["volume_drop_factor"])
_VOLUME_MIN_BASELINE = int(meta.HEALTH["volume_min_baseline"])
_LOW_EXTRACTION_MIN = int(meta.HEALTH["low_extraction_min_attempted"])
_LOW_EXTRACTION_FULL_PCT = float(meta.HEALTH["low_extraction_full_pct"])


# Status keys that count toward "extraction was attempted". SKIPPED
# means the item had no link, so it's excluded from the success-rate
# denominator everywhere it appears.
_ATTEMPTED_STATUSES = ("FULL", "PARTIAL", "STUB", "NONE", "ERROR")
_ALL_STATUSES = _ATTEMPTED_STATUSES + ("SKIPPED",)


def items_per_bucket(snap):
    out = {}
    for ck, cv in snap["countries"].items():
        out[ck] = sum(f.get("item_count", 0) for f in cv.get("feeds", []))
    return out


def trailing_means(date_str: str, n: int = 7):
    """Compute trailing 7-day mean items per bucket from existing snapshots."""
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    by_bucket: dict[str, list[int]] = {}
    for d in range(1, n + 1):
        prev = (target - timedelta(days=d)).isoformat()
        p = SNAPS / f"{prev}.json"
        if not p.exists():
            continue
        try:
            snap = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  trailing_means: skipping {p.name} ({e.__class__.__name__})",
                  file=sys.stderr)
            continue
        for ck, n_items in items_per_bucket(snap).items():
            by_bucket.setdefault(ck, []).append(n_items)
    return {k: round(mean(v), 1) if v else 0 for k, v in by_bucket.items()}


def _full_pct(counts: dict[str, int]) -> float:
    """FULL extraction rate over the attempted denominator (excludes SKIPPED)."""
    attempted = sum(counts.get(k, 0) for k in _ATTEMPTED_STATUSES)
    return 100 * counts.get("FULL", 0) / max(1, attempted)


def health_for(snap_path: Path):
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    date = snap.get("date", snap_path.stem)
    errors, stubs, slow = [], [], []
    extraction_per_bucket: dict[str, dict[str, int]] = {}
    for ck, cv in snap["countries"].items():
        for f in cv.get("feeds", []):
            if f.get("error") or (f.get("http_status") not in (200, None)):
                errors.append({
                    "bucket": ck, "feed": f["name"],
                    "http": f.get("http_status"), "error": f.get("error"),
                })
            items = f.get("items", [])
            if items:
                stub_pct = 100 * sum(1 for i in items if i.get("is_stub")) / len(items)
                if stub_pct >= _STUB_PCT_MIN:
                    stubs.append({"bucket": ck, "feed": f["name"], "stub_pct": round(stub_pct, 1)})
            if (f.get("fetch_ms") or 0) > _SLOW_FETCH_MS:
                slow.append({"bucket": ck, "feed": f["name"], "ms": f["fetch_ms"]})
            # Extraction stats per bucket — accumulate across all feeds in
            # the bucket. Initialise with the full status set so the schema
            # contract holds even when a status never appears.
            ek = extraction_per_bucket.setdefault(ck, {k: 0 for k in _ALL_STATUSES})
            for it in items:
                s = it.get("extraction_status")
                if s in ek:
                    ek[s] += 1

    bucket_now = items_per_bucket(snap)
    bucket_avg7 = trailing_means(date)
    bucket_alerts = []
    for ck, n_now in bucket_now.items():
        avg = bucket_avg7.get(ck, 0)
        # Volume-drop alert (factor + min-baseline pinned under
        # meta.HEALTH): suppress alerts for buckets that are normally tiny.
        if avg >= _VOLUME_MIN_BASELINE and n_now < _VOLUME_DROP_FACTOR * avg:
            bucket_alerts.append({
                "bucket": ck, "alert_type": "volume_drop",
                "now": n_now, "avg7": avg,
                "drop_pct": round(100 * (1 - n_now / max(1, avg)), 1),
            })

    # Per-bucket low-extraction alert: catches "RSS worked but body
    # extraction broke for a whole bucket" — silently loses the
    # editorially-distinct voice unless flagged. Both thresholds pinned.
    for ck, ext in extraction_per_bucket.items():
        attempted = sum(ext.get(k, 0) for k in _ATTEMPTED_STATUSES)
        if attempted < _LOW_EXTRACTION_MIN:
            continue
        full_pct = _full_pct(ext)
        if full_pct < _LOW_EXTRACTION_FULL_PCT:
            bucket_alerts.append({
                "bucket": ck, "alert_type": "low_extraction",
                "attempted": attempted, "full": ext.get("FULL", 0),
                "full_pct": round(full_pct, 1),
                "errors": ext.get("ERROR", 0), "none": ext.get("NONE", 0),
            })

    # Aggregate extraction totals
    extraction_totals = {k: 0 for k in _ALL_STATUSES}
    for v in extraction_per_bucket.values():
        for k in extraction_totals:
            extraction_totals[k] += v.get(k, 0)

    health = meta.stamp({
        "date": date,
        "n_feeds": sum(len(c.get("feeds", [])) for c in snap["countries"].values()),
        "n_items": sum(sum(f.get("item_count", 0) for f in c.get("feeds", []))
                       for c in snap["countries"].values()),
        "n_errors": len(errors),
        "n_stub_feeds": len(stubs),
        "n_slow_feeds": len(slow),
        "errors": errors,
        "stub_feeds": stubs,
        "slow_feeds": slow,
        "items_per_bucket_now": bucket_now,
        "items_per_bucket_avg7": bucket_avg7,
        "bucket_alerts": bucket_alerts,
        "extraction_totals": extraction_totals,
        "extraction_full_pct": round(_full_pct(extraction_totals), 1),
        "extraction_per_bucket": extraction_per_bucket,
    })
    # Fail closed on schema mismatch — the daily.yml job-summary step
    # and feed_rot_check both parse this by field name with no
    # validation of their own.
    meta.validate_schema(health, "health")
    out_path = SNAPS / f"{date}_health.json"
    out_path.write_text(json.dumps(health, indent=2, ensure_ascii=False))
    return health, out_path


def main():
    from pipeline._paths import latest_snapshot
    if len(sys.argv) > 1:
        snap_path = Path(sys.argv[1])
    else:
        snap_path = latest_snapshot(SNAPS)
        if snap_path is None:
            sys.exit(f"No snapshot found in {SNAPS}")
    h, out = health_for(snap_path)
    print(f"Health for {h['date']} -> {out.name}")
    print(f"  feeds: {h['n_feeds']}  items: {h['n_items']}")
    print(f"  errors: {h['n_errors']}  stub: {h['n_stub_feeds']}  slow: {h['n_slow_feeds']}")
    et = h.get("extraction_totals") or {}
    if any(et.values()):
        print(f"  extraction: FULL={et.get('FULL',0)} PARTIAL={et.get('PARTIAL',0)} "
              f"NONE={et.get('NONE',0)} ERROR={et.get('ERROR',0)}  ({h['extraction_full_pct']}% FULL)")
    if h["bucket_alerts"]:
        print(f"  bucket alerts: {len(h['bucket_alerts'])}")
        for a in h["bucket_alerts"]:
            if a.get("alert_type") == "low_extraction":
                print(f"    {a['bucket']}: low_extraction "
                      f"(full={a['full']}/{a['attempted']}={a['full_pct']}%, "
                      f"errors={a['errors']})")
            else:
                print(f"    {a['bucket']}: {a['now']} "
                      f"(avg7={a['avg7']}, -{a['drop_pct']}%)")


if __name__ == "__main__":
    main()
