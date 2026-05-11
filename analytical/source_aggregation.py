"""source_aggregation.py — per-outlet + per-region rollups of source attribution.

Reads `sources/<DATE>_<story>.json` (produced by the source-attribution
Claude pass) for the given date and rolls up:

- Per outlet: speaker-name distribution, attributive-verb mix
  ("said"/"claimed"/"warned"/etc.), speaker-type distribution
  (official/civilian/expert/journalist/spokesperson).
- Per bucket: same metrics aggregated across feeds.
- Per region (geographic clustering of buckets): top-10 most-quoted
  speakers and the count of distinct outlets that quoted them.

Region grouping is **derived from feeds.json bucket metadata** so it's
consistent with the rest of the pipeline. Regions are coarse:
  - americas (us, canada, brazil, mexico, ...)
  - europe (uk, france, germany, italy, spain, nordic, ...)
  - middle_east (israel, iran_state, iran_opposition, pan_arab, ...)
  - asia_pacific (china, japan, india, ...)
  - africa (...)
  - wire_services (treated as its own region)

Output: `sources/aggregate/<DATE>.json`:

    {
      "date": "...",
      "n_stories": int,
      "n_sources": int,
      "by_outlet": {<outlet>: {n_quotes, top_speakers[], verb_mix, type_mix}},
      "by_bucket": {<bucket>: {...}},
      "by_region": {<region>: {top_speakers[], n_distinct_outlets,
                                 n_sources, type_mix, stance_mix}}
    }

Usage:
  python -m analytical.source_aggregation
  python -m analytical.source_aggregation --date 2026-05-08
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
SOURCES = ROOT / "sources"
AGGREGATE = SOURCES / "aggregate"

# Region grouping. Buckets not listed → region="other". Coarse on purpose;
# downstream consumers can re-aggregate at finer granularity if they want.
BUCKET_TO_REGION: dict[str, str] = {
    # Americas
    "usa": "americas", "canada": "americas", "us_extra": "americas",
    "mexico": "americas", "brazil": "americas",
    "argentina_chile": "americas", "colombia_ven_peru": "americas",
    # Europe
    "uk": "europe", "france_direct": "europe", "germany": "europe",
    "italy": "europe", "spain": "europe", "nordic": "europe",
    "netherlands_belgium": "europe", "poland_balt": "europe",
    "hungary_central": "europe", "balkans": "europe",
    "russia_native": "europe", "russia": "europe",
    "ukraine": "europe", "belarus_caucasus": "europe",
    # Middle East
    "israel": "middle_east", "iran_state": "middle_east",
    "iran_opposition": "middle_east", "iran_state_extra": "middle_east",
    "pan_arab": "middle_east", "qatar": "middle_east",
    "lebanon": "middle_east", "iraq": "middle_east", "syria": "middle_east",
    "jordan": "middle_east", "palestine": "middle_east",
    "turkey": "middle_east", "turkey_extra": "middle_east",
    "egypt": "middle_east", "saudi_arabia": "middle_east",
    # Asia-Pacific
    "china": "asia_pacific", "japan": "asia_pacific",
    "india": "asia_pacific", "pakistan": "asia_pacific",
    "korea_north": "asia_pacific", "korea_south": "asia_pacific",
    "taiwan_hk": "asia_pacific", "indonesia": "asia_pacific",
    "philippines": "asia_pacific", "vietnam_thai_my": "asia_pacific",
    "asia_pacific_regional": "asia_pacific", "australia_nz": "asia_pacific",
    # Africa
    "africa_other": "africa", "south_africa": "africa",
    "kenya": "africa", "nigeria": "africa", "pan_african": "africa",
    # Wire + opinion as their own regions
    "wire_services": "wire", "opinion_magazines": "opinion",
    "religious_press": "opinion",
}


def region_for(bucket: str) -> str:
    return BUCKET_TO_REGION.get(bucket, "other")


def load_sources(date: str, sources_dir: Path = SOURCES) -> list[dict]:
    """Return the flat list of source entries across all stories for `date`,
    each entry annotated with `story_key`."""
    out: list[dict] = []
    for p in sorted(sources_dir.glob(f"{date}_*.json")):
        if p.parent.name == "aggregate":
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
            print(f"FAIL: {p}: {e}", file=sys.stderr)
            continue
        sk = doc.get("story_key")
        for s in (doc.get("sources") or []):
            out.append({**s, "story_key": sk})
    return out


def aggregate(sources: list[dict], top_k: int = 10) -> dict:
    """Compute per-outlet, per-bucket, per-region rollups."""
    by_outlet: dict[str, dict] = defaultdict(lambda: {
        "n_quotes": 0,
        "speakers": Counter(),
        "verb_mix": Counter(),
        "type_mix": Counter(),
        "stance_mix": Counter(),
        "affiliation_mix": Counter(),
    })
    by_bucket: dict[str, dict] = defaultdict(lambda: {
        "n_quotes": 0,
        "speakers": Counter(),
        "verb_mix": Counter(),
        "type_mix": Counter(),
        "stance_mix": Counter(),
        "affiliation_mix": Counter(),
        "outlets": set(),
    })
    by_region: dict[str, dict] = defaultdict(lambda: {
        "n_quotes": 0,
        "speakers": Counter(),
        "outlets_per_speaker": defaultdict(set),
        "type_mix": Counter(),
        "stance_mix": Counter(),
        "affiliation_mix": Counter(),
        "buckets": set(),
    })

    for s in sources:
        outlet = s.get("outlet") or "?"
        bucket = s.get("bucket") or "?"
        region = region_for(bucket)
        speaker = s.get("speaker_name") or f"<unnamed: {s.get('role_or_affiliation', '?')}>"
        verb = (s.get("attributive_verb") or "?").lower()
        stype = s.get("speaker_type") or "unknown"
        stance = s.get("stance_toward_target") or "unclear"
        affil = s.get("speaker_affiliation_bucket") or "unknown"

        by_outlet[outlet]["n_quotes"] += 1
        by_outlet[outlet]["speakers"][speaker] += 1
        by_outlet[outlet]["verb_mix"][verb] += 1
        by_outlet[outlet]["type_mix"][stype] += 1
        by_outlet[outlet]["stance_mix"][stance] += 1
        by_outlet[outlet]["affiliation_mix"][affil] += 1

        by_bucket[bucket]["n_quotes"] += 1
        by_bucket[bucket]["speakers"][speaker] += 1
        by_bucket[bucket]["verb_mix"][verb] += 1
        by_bucket[bucket]["type_mix"][stype] += 1
        by_bucket[bucket]["stance_mix"][stance] += 1
        by_bucket[bucket]["affiliation_mix"][affil] += 1
        by_bucket[bucket]["outlets"].add(outlet)

        by_region[region]["n_quotes"] += 1
        by_region[region]["speakers"][speaker] += 1
        by_region[region]["outlets_per_speaker"][speaker].add(outlet)
        by_region[region]["type_mix"][stype] += 1
        by_region[region]["stance_mix"][stance] += 1
        by_region[region]["affiliation_mix"][affil] += 1
        by_region[region]["buckets"].add(bucket)

    # Serialise (Counters → ordered dicts; sets → lists)
    def _ser_outlet(d: dict) -> dict:
        return {
            "n_quotes": d["n_quotes"],
            "top_speakers": d["speakers"].most_common(top_k),
            "verb_mix": dict(d["verb_mix"].most_common()),
            "type_mix": dict(d["type_mix"].most_common()),
            "stance_mix": dict(d["stance_mix"].most_common()),
            "affiliation_mix": dict(d["affiliation_mix"].most_common()),
        }

    def _ser_bucket(d: dict) -> dict:
        return {
            "n_quotes": d["n_quotes"],
            "n_outlets": len(d["outlets"]),
            "outlets": sorted(d["outlets"]),
            "top_speakers": d["speakers"].most_common(top_k),
            "verb_mix": dict(d["verb_mix"].most_common()),
            "type_mix": dict(d["type_mix"].most_common()),
            "stance_mix": dict(d["stance_mix"].most_common()),
            "affiliation_mix": dict(d["affiliation_mix"].most_common()),
        }

    def _ser_region(d: dict) -> dict:
        top = d["speakers"].most_common(top_k)
        return {
            "n_quotes": d["n_quotes"],
            "n_buckets": len(d["buckets"]),
            "buckets": sorted(d["buckets"]),
            "top_speakers": [
                {
                    "speaker": sp,
                    "n_quotes": n,
                    "n_distinct_outlets": len(d["outlets_per_speaker"][sp]),
                }
                for sp, n in top
            ],
            "type_mix": dict(d["type_mix"].most_common()),
            "stance_mix": dict(d["stance_mix"].most_common()),
            "affiliation_mix": dict(d["affiliation_mix"].most_common()),
        }

    return {
        "by_outlet": {k: _ser_outlet(v) for k, v in by_outlet.items()},
        "by_bucket": {k: _ser_bucket(v) for k, v in by_bucket.items()},
        "by_region": {k: _ser_region(v) for k, v in by_region.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None)
    ap.add_argument("--out-dir", default=str(AGGREGATE))
    ap.add_argument("--top-k", type=int, default=10)
    args = ap.parse_args()

    date = args.date or datetime.now(timezone.utc).date().isoformat()
    sources = load_sources(date)
    if not sources:
        print(f"No sources for {date}. (Source-attribution agent has not run yet, "
              f"or no quotes were extracted.)")
        return 0

    agg = aggregate(sources, top_k=args.top_k)
    out = meta.stamp({
        "date": date,
        "n_stories": len({s.get("story_key") for s in sources}),
        "n_sources": len(sources),
        **agg,
    })
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"  ✓ {out_path.name}: {out['n_sources']} sources across "
          f"{out['n_stories']} stories, {len(agg['by_outlet'])} outlets, "
          f"{len(agg['by_region'])} regions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
