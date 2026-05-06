"""Phase 9: post-pull daily health snapshot.

Run after each ingest. Emits snapshots/<date>_health.json describing:
  - errored feeds (http != 200 or had transport error)
  - stub-only feeds (>=80% of items had is_stub flag)
  - slow feeds (>5s fetch_ms)
  - items-per-bucket vs trailing-7-day mean
  - language script distribution
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent
SNAPS = ROOT / "snapshots"


def items_per_bucket(snap):
    out = {}
    for ck, cv in snap["countries"].items():
        out[ck] = sum(f.get("item_count", 0) for f in cv["feeds"])
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
        except Exception:
            continue
        for ck, n_items in items_per_bucket(snap).items():
            by_bucket.setdefault(ck, []).append(n_items)
    return {k: round(mean(v), 1) if v else 0 for k, v in by_bucket.items()}


def health_for(snap_path: Path):
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    date = snap.get("date", snap_path.stem)
    errors, stubs, slow = [], [], []
    for ck, cv in snap["countries"].items():
        for f in cv["feeds"]:
            if f.get("error") or (f.get("http_status") not in (200, None)):
                errors.append({
                    "bucket": ck, "feed": f["name"],
                    "http": f.get("http_status"), "error": f.get("error"),
                })
            items = f.get("items", [])
            if items:
                stub_pct = 100 * sum(1 for i in items if i.get("is_stub")) / len(items)
                if stub_pct >= 80:
                    stubs.append({"bucket": ck, "feed": f["name"], "stub_pct": round(stub_pct, 1)})
            if (f.get("fetch_ms") or 0) > 5000:
                slow.append({"bucket": ck, "feed": f["name"], "ms": f["fetch_ms"]})

    bucket_now = items_per_bucket(snap)
    bucket_avg7 = trailing_means(date)
    bucket_alerts = []
    for ck, n_now in bucket_now.items():
        avg = bucket_avg7.get(ck, 0)
        # Alert if bucket dropped by >50% vs 7-day avg AND avg was non-trivial
        if avg >= 5 and n_now < 0.5 * avg:
            bucket_alerts.append({
                "bucket": ck, "now": n_now, "avg7": avg,
                "drop_pct": round(100 * (1 - n_now / max(1, avg)), 1),
            })

    health = {
        "date": date,
        "n_feeds": sum(len(c["feeds"]) for c in snap["countries"].values()),
        "n_items": sum(sum(f.get("item_count", 0) for f in c["feeds"])
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
    }
    out_path = SNAPS / f"{date}_health.json"
    out_path.write_text(json.dumps(health, indent=2, ensure_ascii=False))
    return health, out_path


def main():
    if len(sys.argv) > 1:
        snap_path = Path(sys.argv[1])
    else:
        cands = sorted(p for p in SNAPS.glob("[0-9]*.json")
                       if not p.stem.endswith(("_convergence", "_similarity",
                                                "_prompt", "_dedup", "_health")))
        snap_path = cands[-1]
    h, out = health_for(snap_path)
    print(f"Health for {h['date']} -> {out.name}")
    print(f"  feeds: {h['n_feeds']}  items: {h['n_items']}")
    print(f"  errors: {h['n_errors']}  stub: {h['n_stub_feeds']}  slow: {h['n_slow_feeds']}")
    if h["bucket_alerts"]:
        print(f"  bucket alerts: {len(h['bucket_alerts'])}")
        for a in h["bucket_alerts"]:
            print(f"    {a['bucket']}: {a['now']} (avg7={a['avg7']}, -{a['drop_pct']}%)")


if __name__ == "__main__":
    main()
