# Test Report — Epistemic Lens v0.4

**Date:** 2026-05-06
**Result:** ✅ All tests pass

## Summary

| Suite | Tests | Pass | Fail | Time |
|---|---|---|---|---|
| `tests.py` (unit) | 27 | 27 | 0 | 0.6s |
| `tests_edge.py` (stress / edge cases) | 18 | 18 | 0 | 12.1s |
| `tests_e2e.py` (full pipeline smoke) | 42 | 42 | 0 | ~6s |
| Analysis scripts (run end-to-end) | 8 | 8 | 0 | varies |
| **Total** | **95** | **95** | **0** | |

## What was tested

### Unit tests (`tests.py`)
- **Parser** — RSS 2.0, Atom, RDF/RSS 1.0, BOM-prefixed, broken XML, empty, max-N cap, mixed namespaces, CDATA + tag stripping
- **`_strip_html`** — tag stripping, HTML-entity decoding, whitespace collapse
- **`_parse_pub`** — 5 datetime formats + invalid input
- **`_annotate_item`** — `is_stub` (3 paths), `is_google_news`, `published_age_hours`
- **`_wait_for_host`** — per-host rate limiting timing (>=0.5s same host, <0.1s different host)
- **HTTP retry** — 3 retries on 5xx, no retry on 4xx, retry on `ConnectionError`
- **Dedup** — URL canonicalisation (utm strip, www., m./mobile., trailing slash, fragments, Google News special case), title normalisation (lowercase, suffix strip ` - Reuters`/` | CNN`, punctuation stripping, Cyrillic preservation)
- **`dedup_snapshot`** — collapses cross-bucket URL duplicates correctly
- **`daily_health.health_for`** — error/stub/slow detection
- **Schema validation** — latest snapshot has all required fields per item; `feeds.json` has 138 unique URLs, version 0.4.0
- **Sitemap fallback** — parses `sitemap-news.xml` correctly with `news:title` extraction

### Edge cases (`tests_edge.py`)
- **Malformed RSS** — truncated XML, illegal XML chars, items missing title (dropped), items missing optional fields (tolerated), mixed-namespace `content:encoded` + `dc:date`
- **Annotation edge cases** — future-dated published (clock skew), malformed dates, very long summaries (10kB), empty summaries
- **Dedup edge cases** — empty snapshot, one-item snapshot, intra-feed duplicates (the People's Daily 3× pattern), pure-emoji titles, all-punctuation titles, no-scheme URLs
- **Network edge cases** — pull from `*.invalid` domain (graceful error), one-dead-one-alive bucket (alive feed still works, dead feed gracefully recorded)

### End-to-end (`tests_e2e.py`)
Live fetch from 5 real feeds (AFP/F24, DW EN, Dawn, Kommersant, Ukrainska Pravda) → snapshot persist → dedup → daily_health → feed_rot_check, exercising every layer of the pipeline.

42 assertion checks including:
- All 5 feeds returned items (>= 30 total)
- All items carry annotation flags (`is_stub`, `is_google_news`, `summary_chars`, `published_age_hours`, `id`)
- Per-feed metadata present (`fetch_ms`, `http_status`, `bytes`, `error`)
- Dedup didn't over-collapse (>= 70% items retained)
- Health file has all required keys
- Rot check ran without exception
- Snapshot JSON has `max_items` and `config_version`
- Kommersant returned actual Cyrillic titles (the v0.4 multilingual fix)
- Parallel fetch completed in <5s (no rate-limiter deadlock)

### Integration (analysis scripts)
All eight standalone scripts run end-to-end without error:
- `analysis.py` — country pair correlations, silence audit, framing keywords (297 lines of output)
- `analysis2.py` — side-by-side cluster framing comparisons (152 lines)
- `source_audit.py` — full source audit incl. live HTTP probes (618 lines)
- `before_after.py` — v0.2 vs v0.4 validation report
- `baseline_pin.py` — baseline pinning (handles missing convergence files gracefully)
- `daily_health.py` — post-pull health snapshot
- `feed_rot_check.py` — weekly rot detection
- `dedup.py` — snapshot deduplication

## Bugs found and fixed during testing

| # | Where | Symptom | Fix |
|---|---|---|---|
| 1 | `source_audit.py` | Crashes on `KeyError: 'countries'` | Glob filter wasn't excluding new `_health.json`/`_dedup.json` files. Updated exclusion list. |
| 2 | `baseline_pin.py` | Crashes on `FileNotFoundError` for `_convergence` | Same glob issue + assumed every snapshot has companion files. Filter fixed + per-day existence check added. |
| 3 | `dedup.py` | Crashes on `KeyError: 'countries'` | Same glob issue. Updated exclusion list. |

All three were the same class of bug — globs picking up auxiliary output files added in phases 5/6/9 that didn't exist when the original analysis scripts were written. Each fix is one line.

## Known limitations of the test suite

- **No embedding/clustering tests.** `sentence-transformers` and `scikit-learn` aren't installed in this container. The `embed_snapshot` / `cluster_topics` / `compute_convergence` / `compute_similarity_matrix` paths are exercised syntactically only (the e2e test runs with `SKIP_EMBED=1`). Run on prod to verify those.
- **GDELT DOC API not unit-tested** beyond query string construction. Live runs hit rate limits; mocking the JSON response would be straightforward to add.
- **No test of `ingest.py` `--main` path** — the `if __name__ == "__main__"` block. The component functions it calls are all tested individually.
- **Edge case probably worth adding later:** feed that returns very large XML (>10MB) — current code parses it in memory; should validate or stream.

## How to reproduce

```bash
# Unit + edge tests (fast, no network)
python3 -m unittest tests.py tests_edge.py

# Full pipeline smoke (needs network, ~10s)
python3 tests_e2e.py

# Analysis scripts (varies)
python3 analysis.py
python3 source_audit.py
# ...etc
```
