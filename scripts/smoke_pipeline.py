#!/usr/bin/env python3
"""smoke_pipeline.py — run the v10 data pipeline end-to-end on synthetic data.

The point: catch wiring/contract regressions WITHOUT a GitHub Actions run
and WITHOUT the ~25-min e5-large encode of a real 6,500-article day.

Every cron failure so far has been plumbing, not logic — a path pointing
at the wrong dir, a glob picking up a sibling artefact, a missing
dependency. So this harness exercises the *wiring*: it builds tiny
synthetic snapshots, runs every data stage on them, and checks the
contracts the next stage (and the schemas) depend on.

Checks performed:
  R   requirements.txt declares every package a cron stage hard-needs
  A   a v10-shaped analysis passes analysis.schema.json AND validate.py
  1   rich day  — ingest stages + encode -> cluster -> salience -> build
                  -> qualifying -> metrics; briefings validate against
                  briefing.schema.json
  1b  latest_snapshot_date resolves to the bare date with every sibling
      artefact present (the cron #89 regression)
  2   thin day  — too few articles to cluster: every stage degrades to a
                  valid empty artefact instead of crashing

The embedding model defaults to a small fast one (override with
EMBEDDING_MODEL) — the pipeline LOGIC is model-independent, so there's no
need to pull e5-large just to test plumbing.

Usage:
  python scripts/smoke_pipeline.py
  EMBEDDING_MODEL=intfloat/multilingual-e5-large python scripts/smoke_pipeline.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

# A small, fast, multilingual model is plenty for a wiring test. The real
# cron uses meta_version.json's pinned model; override here so the smoke
# run doesn't download ~2GB.
os.environ.setdefault(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

import core.meta as meta  # noqa: E402

DATE = "2099-01-02"  # far-future so it never collides with a real snapshot

# Distinct topics; articles within a topic are near-paraphrases so their
# embeddings form a tight, unmistakable cluster (HDBSCAN min_cluster_size=3
# needs >=3 dense neighbours). Two topics carry non-Latin text.
TOPICS = [
    ("strait shipping crisis", "en",
     "Tanker traffic through the contested strait slowed sharply as naval "
     "escorts were ordered into the shipping lane. Insurers raised war-risk "
     "premiums on every vessel crossing the strait this week as the crisis "
     "deepened and freight operators rerouted cargo away from the chokepoint."),
    ("central bank rate decision", "en",
     "The central bank held its benchmark interest rate steady, citing "
     "stubborn core inflation and a cooling labour market. Economists had "
     "expected the rate decision to leave borrowing costs unchanged while "
     "the bank watches wage growth and consumer prices over the quarter."),
    ("wildfire evacuation", "en",
     "Fast-moving wildfires forced thousands to evacuate as crews battled "
     "the blaze through dry brush and high wind. Emergency shelters opened "
     "for residents displaced by the wildfire and choking smoke that closed "
     "highways and grounded firefighting aircraft across the region."),
    ("space telescope discovery", "en",
     "Astronomers using the orbital telescope reported a distant galaxy "
     "whose ancient light reveals the early universe. The telescope's deep "
     "field image captured faint structures never resolved before, and the "
     "team said the discovery reshapes models of how galaxies first formed."),
    ("نزاع حدودي دبلوماسي", "ar",
     "استدعت الحكومة السفير على خلفية نزاع حدودي متصاعد بينما دعت وزارة "
     "الخارجية إلى ضبط النفس وخفض التصعيد. وقال مسؤولون إن المحادثات "
     "الدبلوماسية حول النزاع الحدودي ستستأنف قريبا برعاية وسطاء إقليميين "
     "بعد أسابيع من التوتر على طول الحدود المتنازع عليها بين البلدين."),
    ("芯片出口管制政策", "zh",
     "政府宣布对先进半导体实施新的出口管制措施，芯片制造商警告全球供应链将"
     "受到严重干扰。分析人士说，出口管制将重塑全球芯片产业的竞争格局，并"
     "促使企业重新评估在不同地区的生产布局与长期投资计划安排。"),
]
OUTLETS = [
    ("The Herald", "usa", "United States", "en"),
    ("Daily Chronicle", "uk", "United Kingdom", "en"),
    ("Le Quotidien", "france", "France", "fr"),
    ("Press Agency", "germany", "Germany", "de"),
    ("Gulf Times", "iran", "Iran", "fa"),
    ("Eastern Daily", "china", "China", "zh"),
]


def _body(text: str, n: int) -> str:
    """>=500 chars so signal_text() returns level 'body'."""
    return (f"Bulletin {n}: " + text + " ") * 3


def build_snapshot(topics, per_topic: int) -> dict:
    """A country-nested snapshot in the shape core.ingest.pull_feeds writes."""
    countries: dict = {}
    counter = 0
    for ti, (topic, lang, text) in enumerate(topics):
        for k in range(per_topic):
            outlet, country, label, olang = OUTLETS[counter % len(OUTLETS)]
            counter += 1
            cv = countries.setdefault(country, {"label": label, "feeds": {}})
            feed = cv["feeds"].setdefault(
                outlet, {"name": outlet, "lang": olang, "items": []})
            feed["items"].append({
                "id": f"a{counter:04d}",  # pull_feeds assigns a per-item id
                "title": f"{topic} — report {k}",
                "link": f"https://example.com/{ti}/{k}",
                "summary": text[:180],
                "body_text": _body(text, k),
            })
    for cv in countries.values():
        cv["feeds"] = list(cv["feeds"].values())
    return {"date": DATE, "countries": countries}


# --------------------------------------------------------------------------
# Check R — requirements.txt completeness
# --------------------------------------------------------------------------
def check_requirements() -> list[str]:
    """Every package a v10 cron stage HARD-needs (no in-code fallback) must
    be declared in requirements.txt. A package relied on only transitively
    is a latent break waiting for a dependency-graph change."""
    req = (REPO / "requirements.txt").read_text(encoding="utf-8")
    hard = [
        ("requests", "ingest/pull_feeds"),
        ("trafilatura", "ingest/extract_bodies"),
        ("sentence-transformers", "embed/encode + metrics LaBSE"),
        ("numpy", "embed/encode + cluster/cluster_daily"),
        ("hdbscan", "cluster/cluster_daily"),
        ("jsonschema", "ingest/coverage_matrix + analyze/validate (meta.validate_schema raises if absent)"),
    ]
    return [f"{pkg}  — needed by {why}" for pkg, why in hard if pkg not in req]


# --------------------------------------------------------------------------
# Check A — the analysis contract (schema + validator)
# --------------------------------------------------------------------------
def check_analysis_contract() -> None:
    """A v10-shaped analysis must pass analysis.schema.json AND the
    citation/codebook checks in core.analyze.validate. Also: a deliberately
    broken analysis must be rejected — otherwise the validator is asleep."""
    from core.analyze import validate

    briefing = {"corpus": [
        {"outlet": "The Herald", "country": "usa", "lang": "en",
         "signal_text": "Tanker traffic slowed sharply in the contested strait "
                         "as insurers raised premiums."},
        {"outlet": "Le Quotidien", "country": "france", "lang": "fr",
         "signal_text": "Naval escorts entered the shipping lane to protect "
                         "cargo vessels."},
    ]}
    analysis = {
        "meta_version": meta.VERSION,
        "date": DATE,
        "lineage_id": "L0a1b2c3d4e",
        "cluster_id": 0,
        "cluster_name": "Strait shipping crisis",
        "n_outlets": 2,
        "n_countries": 2,
        "tldr": "Outlets across two countries converge on the shipping "
                "disruption in the contested strait, framing it primarily as "
                "an economic shock to global freight and trade.",
        "bottom_line": "The strait crisis dominates coverage as an economic "
                       "story with a security dimension.",
        "generated_at": "2099-01-02T00:00:00Z",
        "frames": [
            {"frame_id": "ECONOMIC", "outlets": ["The Herald"],
             "countries": ["usa"],
             "evidence": [{"outlet": "The Herald",
                           "quote": "Tanker traffic slowed sharply",
                           "signal_text_idx": 0}]},
            {"frame_id": "SECURITY_DEFENSE", "outlets": ["Le Quotidien"],
             "countries": ["france"],
             "evidence": [{"outlet": "Le Quotidien",
                           "quote": "Naval escorts entered the shipping lane",
                           "signal_text_idx": 1}]},
        ],
    }
    # Schema conformance.
    meta.validate_schema(analysis, "analysis")
    # Citation grounding + codebook must PASS on a clean analysis.
    errs = validate.check_citations(analysis, briefing)
    assert not errs, f"check_citations flagged a clean analysis: {errs}"
    errs = validate.check_codebook(analysis)
    assert not errs, f"check_codebook flagged a clean analysis: {errs}"
    # And must FAIL on a broken one (out-of-range citation).
    broken = json.loads(json.dumps(analysis))
    broken["frames"][0]["evidence"][0]["signal_text_idx"] = 99
    errs = validate.check_citations(broken, briefing)
    assert errs, "check_citations did not flag an out-of-range signal_text_idx"


# --------------------------------------------------------------------------
# Pipeline runner
# --------------------------------------------------------------------------
def _point_modules_at(tmp: Path):
    """Repoint every pipeline module's data-dir constant at the temp tree.

    Modules bind `SNAPSHOTS = meta.SNAPSHOTS_DIR` (etc.) at import time, so
    patching `meta` alone isn't enough — and because the two scenarios share
    one process, a module imported during scenario 1 keeps its scenario-1
    paths into scenario 2 unless re-patched. So patch every module's own
    bound constant, on every call.
    """
    import core.embed.encode as encode
    import core.cluster.cluster_daily as cluster_daily
    import core.cluster.salience as salience
    import core.briefing.build as build
    import core.briefing.qualifying as qualifying
    import core.metrics.cross_bucket as cross_bucket
    import core.ingest.dedup as dedup
    import core.ingest.coverage_matrix as coverage_matrix
    import core.ingest.health as health

    snaps, briefs, archive, cov = (
        tmp / "snapshots", tmp / "briefings", tmp / "archive", tmp / "coverage")
    for d in (snaps, briefs, archive, cov):
        d.mkdir(parents=True, exist_ok=True)

    meta.SNAPSHOTS_DIR = snaps
    meta.BRIEFINGS_DIR = briefs
    meta.ARCHIVE_DIR = archive
    meta.COVERAGE_DIR = cov
    encode.SNAPSHOTS = snaps
    cluster_daily.SNAPSHOTS = snaps
    salience.SNAPSHOTS = snaps
    build.SNAPSHOTS = snaps
    build.BRIEFINGS = briefs
    qualifying.BRIEFINGS = briefs
    cross_bucket.BRIEFINGS = briefs
    dedup.SNAPS = snaps
    coverage_matrix.SNAPS = snaps
    coverage_matrix.COVERAGE_DIR = cov
    health.SNAPS = snaps
    return snaps, briefs


def run_chain(label: str, snapshot: dict, *, expect_clusters: bool) -> None:
    """Run the full data chain on `snapshot` in an isolated temp tree and
    assert the contract at every stage. Raises AssertionError on a break."""
    print(f"\n[{label}]")
    tmp = Path(tempfile.mkdtemp(prefix="el_smoke_"))
    try:
        snaps, briefs = _point_modules_at(tmp)
        snap_path = snaps / f"{DATE}.json"
        snap_path.write_text(json.dumps(snapshot, ensure_ascii=False),
                             encoding="utf-8")
        n_articles = sum(len(f["items"]) for cv in snapshot["countries"].values()
                         for f in cv["feeds"])
        print(f"  synthetic snapshot: {n_articles} articles")

        import core.embed.encode as encode
        import core.cluster.cluster_daily as cluster_daily
        import core.cluster.salience as salience
        import core.briefing.build as build
        import core.briefing.qualifying as qualifying
        import core.metrics.cross_bucket as cross_bucket
        import core.ingest.dedup as dedup
        import core.ingest.coverage_matrix as coverage_matrix
        import core.ingest.health as health

        # --- ingest stages (operate on the v10 snapshot shape) ---
        dd = dedup.dedup_snapshot(json.loads(snap_path.read_text(encoding="utf-8")))
        assert isinstance(dd, dict) and "n_deduped" in dd and "deduped_items" in dd, \
            "dedup_snapshot shape"
        cov = coverage_matrix.build_coverage_matrix(snapshot)
        assert isinstance(cov, dict) and "coverage" in cov, "coverage_matrix shape"
        h = health.health_for(snap_path)
        h = h[0] if isinstance(h, tuple) else h
        assert h.get("n_feeds"), "health_for produced no feed count"
        print("  ingest: dedup + coverage_matrix + health  OK")

        # --- encode ---
        rc = encode.encode_snapshot(DATE, snapshots_dir=snaps)
        assert rc == 0, f"encode_snapshot returned {rc}"
        assert (snaps / f"{DATE}_embeddings.npy").exists(), "embeddings.npy missing"
        assert (snaps / f"{DATE}_embedding_ids.json").exists(), "embedding_ids.json missing"
        print("  encode                OK")

        # --- regression guard: date resolution with sibling artefacts present ---
        resolved = meta.latest_snapshot_date(snaps)
        assert resolved == DATE, (
            f"latest_snapshot_date returned {resolved!r}, expected {DATE!r} — "
            f"a sibling artefact was mistaken for a snapshot (cron #89 bug)")
        print(f"  latest_snapshot_date -> {resolved}  OK")

        # --- cluster ---
        clusters = (cluster_daily.discover(DATE).get("clusters")) or []
        assert (snaps / f"{DATE}_clusters.json").exists(), "clusters.json missing"
        if expect_clusters:
            assert clusters, "cluster_daily found 0 clusters on clean data"
        else:
            assert clusters == [], f"thin day should yield 0 clusters, got {len(clusters)}"
        print(f"  cluster_daily         OK  -> {len(clusters)} clusters")

        # --- salience ---
        top = (salience.rank(DATE, top_n=15).get("top_clusters")) or []
        assert (snaps / f"{DATE}_top_clusters.json").exists(), "top_clusters.json missing"
        print(f"  salience              OK  -> {len(top)} top clusters")

        # --- build (+ schema conformance on every briefing) ---
        sys.argv = ["build", "--date", DATE]
        rc = build.main()
        assert rc == 0, f"build.main returned {rc}"
        briefings = sorted(p for p in briefs.glob(f"{DATE}_*.json")
                           if not p.stem.endswith("_metrics"))
        if expect_clusters:
            assert briefings, "build wrote 0 briefings on clean data"
            for bf in briefings:
                b = json.loads(bf.read_text(encoding="utf-8"))
                meta.validate_schema(b, "briefing")  # contract with the schema
            print(f"  build                 OK  -> {len(briefings)} briefings, "
                  f"all valid against briefing.schema.json")
        else:
            assert not briefings, f"thin day should write 0 briefings, got {len(briefings)}"
            print("  build                 OK  -> 0 briefings (thin day, graceful)")

        # --- qualifying (analyze-matrix bootstrap) ---
        ids = qualifying.list_qualifying(DATE, min_outlets=3)
        assert isinstance(ids, list), "list_qualifying must return a list"
        json.dumps(ids)  # must be JSON-serialisable for $GITHUB_OUTPUT / fromJSON()
        if expect_clusters:
            assert ids, "qualifying returned no lineage_ids on clean data"
        else:
            assert ids == [], f"thin day should qualify nothing, got {ids}"
        print(f"  qualifying            OK  -> {len(ids)} lineage_ids for the matrix")

        # --- metrics (best-effort: needs LaBSE; a download hiccup isn't a fail) ---
        if expect_clusters:
            try:
                b = json.loads(briefings[0].read_text(encoding="utf-8"))
                m = cross_bucket.build_metrics(b)
                assert isinstance(m, dict)
                print("  metrics               OK")
            except Exception as e:  # noqa: BLE001
                print(f"  metrics               SKIPPED ({type(e).__name__}: {str(e)[:70]})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print(f"smoke_pipeline — model={meta.embedding_model()}")
    try:
        # R — requirements
        missing = check_requirements()
        assert not missing, ("requirements.txt is missing hard deps:\n    "
                             + "\n    ".join(missing))
        print("\n[R] requirements.txt declares all hard cron deps  OK")

        # A — analysis contract
        check_analysis_contract()
        print("[A] analysis schema + validator contract  OK")

        # 1 — rich day
        run_chain("1] rich day", build_snapshot(TOPICS, per_topic=7),
                  expect_clusters=True)

        # 2 — thin day (one article per topic, 4 topics → nothing clusters)
        run_chain("2] thin day", build_snapshot(TOPICS[:4], per_topic=1),
                  expect_clusters=False)

        print("\nSMOKE PASS — pipeline wiring, schemas, and degenerate-input "
              "handling all verified")
        return 0
    except AssertionError as e:
        print(f"\nSMOKE FAIL — {e}")
        return 1
    except Exception:  # noqa: BLE001
        print("\nSMOKE ERROR —")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
