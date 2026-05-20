#!/usr/bin/env python3
"""smoke_pipeline.py — run the v10 data pipeline end-to-end on synthetic data.

The point: verify the wiring of encode -> cluster_daily -> salience -> build
-> metrics WITHOUT a GitHub Actions run and WITHOUT the ~25-min e5-large
encode of a real 6,500-article day. It builds a tiny synthetic snapshot
(a few dozen articles in obvious topic clusters) in a throwaway temp dir,
points the pipeline modules at it, runs every stage, and asserts each one
produced the artefact the next stage needs.

This is what catches wiring regressions like the `<date>_embedding_ids.json`
being mistaken for a snapshot file — the kind of bug a unit test of pure
functions misses but a real run surfaces immediately.

The embedding model defaults to a small fast one (override-able) — the
pipeline LOGIC is model-independent, so there's no need to pull e5-large
just to test plumbing.

Usage:
  python scripts/smoke_pipeline.py
  EMBEDDING_MODEL=intfloat/multilingual-e5-large python scripts/smoke_pipeline.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# A small, fast, multilingual model is plenty for a wiring test. Real cron
# uses meta_version.json's pinned model; override here so the smoke run
# doesn't download ~2GB. Set before importing the pipeline so meta picks
# it up (meta.embedding_model() reads the env at call time anyway).
os.environ.setdefault(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

import core.meta as meta  # noqa: E402

DATE = "2099-01-02"  # far-future so it never collides with a real snapshot

# Six obviously-distinct topics. Articles within a topic are near-paraphrases
# so their embeddings form a tight, unmistakable cluster (HDBSCAN
# min_cluster_size=3 needs >=3 dense neighbours). A couple of topics carry
# non-Latin text to exercise the multilingual path.
TOPICS = [
    ("strait shipping crisis", "en",
     "Tanker traffic through the contested strait slowed sharply as naval "
     "escorts were ordered into the shipping lane. Insurers raised war-risk "
     "premiums on every vessel crossing the strait this week."),
    ("central bank rate decision", "en",
     "The central bank held its benchmark interest rate steady, citing "
     "stubborn core inflation and a cooling labour market. Economists had "
     "expected the rate decision to leave borrowing costs unchanged."),
    ("wildfire evacuation", "en",
     "Fast-moving wildfires forced thousands to evacuate as crews battled "
     "the blaze through dry brush. Emergency shelters opened for residents "
     "displaced by the wildfire and choking smoke."),
    ("space telescope discovery", "en",
     "Astronomers using the orbital telescope reported a distant galaxy "
     "whose light reveals the early universe. The telescope's deep-field "
     "image captured faint structures never resolved before."),
    ("نزاع حدودي دبلوماسي", "ar",
     "استدعت الحكومة السفير على خلفية نزاع حدودي متصاعد بينما دعت "
     "وزارة الخارجية إلى ضبط النفس. وقال مسؤولون إن المحادثات الدبلوماسية "
     "حول النزاع الحدودي ستستأنف قريبا."),
    ("芯片出口管制", "zh",
     "政府宣布对先进半导体实施新的出口管制措施，芯片制造商警告供应链将受到 "
     "干扰。分析人士说，出口管制将重塑全球芯片产业的格局。"),
]
OUTLETS = [
    ("The Herald", "usa", "United States", "en"),
    ("Daily Chronicle", "uk", "United Kingdom", "en"),
    ("Le Quotidien", "france", "France", "fr"),
    ("Press Agency", "germany", "Germany", "de"),
    ("Gulf Times", "iran", "Iran", "fa"),
    ("Eastern Daily", "china", "China", "zh"),
]
ARTICLES_PER_TOPIC = 7


def _body(topic_text: str, n: int) -> str:
    """~600+ char body so signal_text() returns level 'body'."""
    return (f"Update {n}. " + topic_text + " ") * 4


def build_synthetic_snapshot() -> dict:
    """A country-nested snapshot in the shape core.ingest.pull_feeds writes."""
    countries: dict = {}
    counter = 0
    for topic_i, (topic, lang, text) in enumerate(TOPICS):
        for k in range(ARTICLES_PER_TOPIC):
            outlet_name, country, country_label, _olang = OUTLETS[counter % len(OUTLETS)]
            counter += 1
            item = {
                "title": f"{topic} — report {k}",
                "link": f"https://example.com/{topic_i}/{k}",
                "summary": text[:200],
                "body_text": _body(text, k),
            }
            cv = countries.setdefault(
                country, {"label": country_label, "feeds": {}})
            feeds = cv["feeds"]
            feed = feeds.setdefault(outlet_name, {
                "name": outlet_name, "lang": _olang, "items": []})
            feed["items"].append(item)
    # feeds: dict -> list (snapshot shape)
    for cv in countries.values():
        cv["feeds"] = list(cv["feeds"].values())
    return {"date": DATE, "countries": countries}


def _point_modules_at(tmp: Path) -> None:
    """Repoint every pipeline module's data-dir constant at the temp tree.

    The modules bind `SNAPSHOTS = meta.SNAPSHOTS_DIR` at import, so patching
    meta alone isn't enough — patch each module's own bound constant too.
    """
    import core.embed.encode as encode
    import core.cluster.cluster_daily as cluster_daily
    import core.cluster.salience as salience
    import core.briefing.build as build

    snaps = tmp / "snapshots"
    briefs = tmp / "briefings"
    archive = tmp / "archive"
    for d in (snaps, briefs, archive):
        d.mkdir(parents=True, exist_ok=True)

    meta.SNAPSHOTS_DIR = snaps
    meta.BRIEFINGS_DIR = briefs
    meta.ARCHIVE_DIR = archive
    encode.SNAPSHOTS = snaps
    cluster_daily.SNAPSHOTS = snaps
    salience.SNAPSHOTS = snaps
    build.SNAPSHOTS = snaps
    build.BRIEFINGS = briefs
    return snaps, briefs


def main() -> int:
    print(f"smoke_pipeline — model={meta.embedding_model()}")
    tmp = Path(tempfile.mkdtemp(prefix="el_smoke_"))
    try:
        snaps, briefs = _point_modules_at(tmp)

        # Stage 0: write the synthetic snapshot
        (snaps / f"{DATE}.json").write_text(
            json.dumps(build_synthetic_snapshot(), ensure_ascii=False))
        n_articles = len(TOPICS) * ARTICLES_PER_TOPIC
        print(f"  [0] synthetic snapshot: {n_articles} articles, "
              f"{len(TOPICS)} topics")

        import core.embed.encode as encode
        import core.cluster.cluster_daily as cluster_daily
        import core.cluster.salience as salience
        import core.briefing.build as build
        import core.metrics.cross_bucket as cross_bucket

        # Stage 1: encode
        rc = encode.encode_snapshot(DATE, snapshots_dir=snaps)
        assert rc == 0, f"encode_snapshot returned {rc}"
        assert (snaps / f"{DATE}_embeddings.npy").exists(), "embeddings.npy missing"
        assert (snaps / f"{DATE}_embedding_ids.json").exists(), "embedding_ids.json missing"
        print("  [1] encode            OK  -> embeddings.npy + embedding_ids.json")

        # Stage 1b: the regression guard — latest_snapshot_date must still
        # resolve to the bare date even though sibling artefacts now exist.
        resolved = meta.latest_snapshot_date(snaps)
        assert resolved == DATE, (
            f"latest_snapshot_date returned {resolved!r}, expected {DATE!r} "
            f"— a sibling artefact (e.g. _embedding_ids.json) was mistaken "
            f"for a snapshot")
        print(f"  [1b] latest_snapshot_date resolves to {resolved}  OK")

        # Stage 2: cluster_daily
        clusters_doc = cluster_daily.discover(DATE)
        clusters = clusters_doc.get("clusters") or []
        assert (snaps / f"{DATE}_clusters.json").exists(), "clusters.json missing"
        assert clusters, "cluster_daily found 0 clusters on clean synthetic data"
        print(f"  [2] cluster_daily     OK  -> {len(clusters)} clusters")

        # Stage 3: salience
        top_doc = salience.rank(DATE, top_n=15)
        top = top_doc.get("top_clusters") or []
        assert (snaps / f"{DATE}_top_clusters.json").exists(), "top_clusters.json missing"
        assert top, "salience selected 0 top clusters"
        print(f"  [3] salience          OK  -> {len(top)} top clusters")

        # Stage 4: build briefings
        sys.argv = ["build", "--date", DATE]
        rc = build.main()
        assert rc == 0, f"build.main returned {rc}"
        briefing_files = sorted(
            p for p in briefs.glob(f"{DATE}_*.json")
            if not p.stem.endswith("_metrics"))
        assert briefing_files, "build wrote 0 briefings"
        sample = json.loads(briefing_files[0].read_text(encoding="utf-8"))
        assert sample.get("lineage_id"), "briefing missing lineage_id"
        assert sample.get("corpus"), "briefing has empty corpus"
        for entry in sample["corpus"]:
            assert "outlet" in entry and "country" in entry, \
                "corpus entry missing outlet/country (v10 shape)"
        print(f"  [4] build             OK  -> {len(briefing_files)} briefings, "
              f"corpus is outlet-keyed")

        # Stage 5: metrics (best-effort — needs LaBSE; don't fail the smoke
        # test on a model-download hiccup, just report).
        try:
            m = cross_bucket.build_metrics(sample)
            assert isinstance(m, dict)
            print("  [5] metrics           OK  -> cross-outlet metrics computed")
        except Exception as e:  # noqa: BLE001
            print(f"  [5] metrics           SKIPPED ({type(e).__name__}: "
                  f"{str(e)[:80]})")

        print("\nSMOKE PASS — encode -> cluster -> salience -> build wired correctly")
        return 0
    except AssertionError as e:
        print(f"\nSMOKE FAIL — {e}")
        return 1
    except Exception:  # noqa: BLE001
        print("\nSMOKE ERROR —")
        traceback.print_exc()
        return 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
