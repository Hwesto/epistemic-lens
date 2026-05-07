"""Phase 7: GDELT 2.0 bolt-on — global breadth supplement.

Two integrations:

A. Single GKG slot pull (raw firehose snapshot)
   Pulls the most recent 15-minute GDELT GKG file, summarises:
     - Total articles processed by GDELT in that window
     - Top source countries
     - Top themes (V2THEMES) and locations (V2LOCATIONS)
     - Languages observed
   Writes snapshots/gdelt/<timestamp>_gkg_summary.json

B. Per-cluster breadth check via GDELT DOC 2.0 API
   For each cluster in today's convergence.json, query the GDELT DOC
   API for matching coverage in the last 24h and record:
     - global_article_count
     - countries_covering   (GDELT-detected source countries)
     - languages
     - sample_titles
   Writes snapshots/gdelt/<date>_cluster_breadth.json

This is a *breadth backstop*, not a replacement for the curated feeds.
Use it to answer "did anyone, anywhere cover X" beyond our 138-feed list.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).parent
SNAPS = ROOT / "snapshots"
OUT = SNAPS / "gdelt"
OUT.mkdir(parents=True, exist_ok=True)

UA = "epistemic-lens/0.4 (+https://github.com/Hwesto/epistemic-lens)"

# ---------------------------------------------------------------------------
# A. Single GKG slot pull
# ---------------------------------------------------------------------------
LAST_UPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"

GKG_COLUMNS = [
    "GKGRECORDID","DATE","SourceCollectionIdentifier","SourceCommonName",
    "DocumentIdentifier","Counts","V2Counts","Themes","V2Themes","Locations",
    "V2Locations","Persons","V2Persons","Organizations","V2Organizations",
    "V2Tone","Dates","GCAM","SharingImage","RelatedImages","SocialImageEmbeds",
    "SocialVideoEmbeds","Quotations","AllNames","Amounts","TranslationInfo",
    "Extras",
]

def fetch_latest_gkg_summary():
    print("Fetching GDELT lastupdate index...")
    r = requests.get(LAST_UPDATE_URL, timeout=15, headers={"User-Agent": UA})
    r.raise_for_status()
    gkg_url = None
    for line in r.text.strip().splitlines():
        # Each line: <size> <md5> <url>
        parts = line.split()
        if len(parts) == 3 and parts[2].endswith(".gkg.csv.zip"):
            gkg_url = parts[2]
            break
    if not gkg_url:
        print("  no GKG URL found in index"); return None
    print(f"  pulling {gkg_url}")
    r = requests.get(gkg_url, timeout=60, headers={"User-Agent": UA})
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = z.namelist()[0]
    data = z.read(name)
    # GDELT GKG is tab-separated, latin-1 encoded
    text = data.decode("utf-8", errors="replace")
    rows = list(csv.reader(text.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    print(f"  parsed {len(rows)} GKG rows")

    # Aggregate
    countries = Counter()
    themes = Counter()
    sources = Counter()
    languages = Counter()
    for row in rows:
        if len(row) < len(GKG_COLUMNS):
            continue
        rec = dict(zip(GKG_COLUMNS, row))
        sources[rec["SourceCommonName"][:60]] += 1
        # Extract source-country from V2Locations: "1#United States#US#..."
        v2loc = rec.get("V2Locations", "")
        for piece in v2loc.split(";"):
            parts = piece.split("#")
            if len(parts) >= 4 and parts[0] == "1":  # ADM1 type=country
                countries[parts[2]] += 1
                break
        # Top V2Themes
        v2t = rec.get("V2Themes", "")
        for theme in v2t.split(";"):
            theme = theme.split(",", 1)[0]
            if theme:
                themes[theme] += 1
        # TranslationInfo: srclc:eng;
        tinfo = rec.get("TranslationInfo", "")
        m = re.search(r"srclc:([a-z]{3})", tinfo)
        if m:
            languages[m.group(1)] += 1
        else:
            languages["eng"] += 1

    summary = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "gkg_url": gkg_url,
        "n_rows": len(rows),
        "top_source_countries": countries.most_common(25),
        "top_sources": sources.most_common(30),
        "top_themes": themes.most_common(30),
        "languages": languages.most_common(20),
    }
    ts = re.search(r"(\d{14})", gkg_url).group(1)
    out_path = OUT / f"{ts}_gkg_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"  wrote {out_path.name}")
    print(f"  top countries: {[c for c,_ in summary['top_source_countries'][:10]]}")
    print(f"  top themes:    {[t for t,_ in summary['top_themes'][:8]]}")
    print(f"  languages:     {[l for l,_ in summary['languages'][:8]]}")
    return summary

# ---------------------------------------------------------------------------
# B. Per-cluster breadth check via GDELT DOC API
# ---------------------------------------------------------------------------
DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

def query_breadth(query: str, hours: int = 24, max_results: int = 50):
    params = {
        "query": query, "mode": "ArtList", "format": "JSON",
        "maxrecords": max_results, "timespan": f"{hours}h",
    }
    url = DOC_API + "?" + urlencode(params)
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": UA})
        if r.status_code != 200:
            return {"error": f"http {r.status_code}", "n": 0, "articles": []}
        data = r.json()
        arts = data.get("articles", [])
        return {
            "n": len(arts),
            "countries": list(Counter(a.get("sourcecountry", "?") for a in arts).items()),
            "languages": list(Counter(a.get("language", "?") for a in arts).items()),
            "sample_titles": [a.get("title", "")[:120] for a in arts[:5]],
        }
    except Exception as e:
        return {"error": f"{e.__class__.__name__}: {str(e)[:60]}", "n": 0, "articles": []}


def cluster_breadth_check(date_str: str | None = None):
    if date_str is None:
        cands = sorted(p for p in SNAPS.glob("[0-9]*_convergence.json"))
        if not cands:
            print("No convergence files found.")
            return
        date_str = cands[-1].stem.replace("_convergence", "")
    conv_path = SNAPS / f"{date_str}_convergence.json"
    if not conv_path.exists():
        print(f"No convergence file for {date_str}")
        return
    conv = json.loads(conv_path.read_text(encoding="utf-8"))
    print(f"Querying GDELT breadth for {len(conv)} clusters from {date_str}...")
    out = []
    for i, cl in enumerate(conv[:20], 1):  # top 20 clusters
        rep = cl["representative_title"]
        # Take first 5 keywords longer than 3 chars
        kws = [w for w in re.findall(r"[A-Za-z]{4,}", rep) if w.lower() not in
               {"says","that","with","from","this","their","have","after","over"}][:5]
        if not kws:
            continue
        q = " ".join(kws)
        print(f"  [{i}/20] {q[:60]}")
        res = query_breadth(q)
        out.append({
            "cluster_id": cl["cluster_id"],
            "representative_title": rep,
            "epistemic_lens_country_count": cl["country_count"],
            "epistemic_lens_article_count": cl["article_count"],
            "gdelt_query": q,
            "gdelt_global_article_count": res.get("n", 0),
            "gdelt_top_countries": res.get("countries", [])[:10],
            "gdelt_top_languages": res.get("languages", [])[:5],
            "gdelt_sample_titles": res.get("sample_titles", []),
            "gdelt_error": res.get("error"),
        })
        time.sleep(1.0)  # polite to GDELT
    out_path = OUT / f"{date_str}_cluster_breadth.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Wrote {out_path}")
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "gkg"
    if mode == "gkg":
        fetch_latest_gkg_summary()
    elif mode == "breadth":
        date = sys.argv[2] if len(sys.argv) > 2 else None
        cluster_breadth_check(date)
    elif mode == "all":
        fetch_latest_gkg_summary()
        cluster_breadth_check()
    else:
        print(f"Usage: {sys.argv[0]} [gkg|breadth|all] [date]")
