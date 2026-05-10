# Audit backlog

Items surfaced during the stage-by-stage code review that we deliberately
**did not** fix immediately — either because they're cheap to defer, low
risk, or best bundled with a future change to the same area. Each entry
notes the **trigger** that should prompt picking it up. Strike through
entries when fixed; reference the closing commit.

The high-leverage gaps for each stage have already landed on
`claude/review-branch-commercial-MFTEU` (see commits tagged Phase 1–6
and `meta-v2.1.0` / `2.1.1` / `2.2.0`). This file tracks only the
**residue** — items the review surfaced, weighed, and intentionally
parked.

## Stage 0 — Methodology pin

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **0-3** | Three different token-normalisation pipelines (`meta.tokenize` / `analytical.build_briefing._title_tokens` / `pipeline.dedup.normalise_title`) share the stopword set but not the regex / plural / casing pipeline. A future addition to `meta.tokenize` (e.g. stemming) won't propagate. | Each does the right thing for its own job today; collapsing them is a real refactor with surface area in three modules. | Stage 5 review (when looking at `analytical.build_briefing`). Factor `meta.normalise_token(t)` and have `_title_tokens` use it. Keep `dedup.normalise_title` as a separately-documented whole-string canonicaliser. |
| **0-4** | `meta.dir_hash(PROMPTS_DIR)` defaults `glob="*.md"`. New `.json` / `.yaml` / `.j2` prompt assets in `.claude/prompts/` would not be hashed and could drift silently. | No non-`.md` files exist in `.claude/prompts/` today. | When the first non-`.md` file is added under `.claude/prompts/`. Fix: pass `glob="*"` and skip hidden files / dirs explicitly. |
| **0-5** | `canonical_stories.json` has no JSON Schema. A typo in a regex pattern silently never matches; an `exclude` typo skips the wrong things. Pattern quality varies (`\bvietnam.*\bbeijing\b` is greedy; `\biran\b.{0,40}\bdeal\b` is bounded). | `build_briefing.matches_story` is defensive (`exclude or []`), so failures are silent rather than crashes. | Stage 5 review. Add `docs/api/schema/canonical_stories.schema.json` (per-story `title` + `patterns: [string]` + optional `exclude: [string]`); validate in `tests.py`. Patch bump. |

## Stage 1 — Ingest

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **1-7** | `pipeline.ingest._parse_pub` calls `datetime.strptime` with `%a` / `%b` formats — locale-dependent. Today GH Actions runs `C.UTF-8` so English forms parse; on a non-English locale runner it would silently drop publication dates. | Not biting today; latent fragility only. | Next time touching ingest's date handling, or when adding a non-Linux runner. Fix: `os.environ.setdefault("LC_TIME", "C")` at module load, or replace with `email.utils.parsedate_to_datetime` (locale-independent, RFC 2822-aware). Add a test pinning the behaviour. |
| **1-8** | `pipeline.ingest._parse_feed(body, max_n: int = MAX_ITEMS)` — `MAX_ITEMS` binds at function-def time, not call time. Programmatic mutation of the global won't be picked up. | Tests pass `max_n` explicitly; nothing in production mutates the global mid-run. | Whenever `_parse_feed` is next touched. Trivial: `def _parse_feed(body, max_n=None): max_n = max_n or MAX_ITEMS`. |
| **1-9** | `_embed_text` is computed in `_annotate_item` and stripped before the snapshot is persisted (lines 261 & 547–550). The "skip stubs" decision and title-fallback rule live only inline; nothing documents the contract or asserts it on a frozen snapshot. | Behaviour is correct today; the cost is cognitive (a future maintainer wonders why `_embed_text` exists in memory but not on disk). | When re-clustering an old snapshot becomes a feature, or whenever `_annotate_item` is next touched. Fix: one-line module docstring describing the ephemeral contract, plus a test fixing the rule on a known item. |
| **1-min** | `feeds.json:meta.version` (currently `"0.5.0"`) is stamped onto each snapshot as `config_version`, separate from `meta_version`. Two version fields with similar names; easy to confuse. | Both are real and serve different jobs (feeds-roster version vs methodology version), so renaming is non-trivial. | Whenever the feeds roster is next significantly restructured. Consider renaming `config_version` → `feeds_version` on snapshots; methodology bump if it changes the snapshot contract. |

## Stage 2 — Extract full text

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **2-min-A** | `trafilatura.extract` has no per-call timeout. The HTTP fetch is bounded by `EXTRACT_TIMEOUT=15s`, but the body parser itself can in principle deadlock on pathological HTML. Today the only ceiling is daily.yml's `timeout-minutes: 30`. | Cheap mitigation isn't obvious — would need `signal.alarm` (Unix-only, fragile under threads) or a `ProcessPoolExecutor` (heavy). Hasn't bitten in production. | If the cron starts hitting the 30-min wall, or if a runaway `trafilatura.extract` is suspected. Fix: per-task `Future.result(timeout=…)` cancel + thread-kill is unreliable; switching to a `ProcessPoolExecutor` is the real fix. |
| **2-min-B** | No way to force re-extraction of an item already classified `FULL` / `PARTIAL` / `STUB` / `SKIPPED`. The idempotent skip is correct daily-flow behaviour but blocks "refresh yesterday's bodies" workflows. | Not a daily-flow concern. | When backfill becomes a feature. Fix: `EXTRACT_FORCE=1` env (or `--force-status FULL,PARTIAL`) that clears `extraction_status` before `select_items` runs. |
| **2-min-C** | `body_chars` records the full extracted body length while `body_text` is truncated to `max_body_chars=4000`. Two consumers reading the snapshot could get inconsistent results if they assume `len(body_text) == body_chars`. | Working as designed (we cap storage but want the true length for `classify`). Today nothing assumes equality. | When a downstream consumer needs the full body. Fix: bump `max_body_chars` (storage cost) or add a separate `body_text_full` field gated behind a flag. Not urgent. |
| **2-min-D** | The 8 per-item annotation fields written by `extract_one` (`extraction_status`, `body_text`, `body_chars`, `extraction_ms`, `extraction_http`, `extraction_final_url`, `extraction_via_wayback`, `extraction_error`) have no JSON Schema. Stage 4 / Stage 5 read them by name. A typo anywhere surfaces as a silent default. | Same root cause as the snapshot's overall lack of a schema; fixing one annotation set alone would be inconsistent. | When a snapshot-shape schema is added (likely as part of a broader Stage 1 / Stage 2 hand-off contract review). |

## Stages 3 — 21

(Not yet reviewed. Each stage's residue gets appended here as we go.)

## Convention

- New entries use the form `<stage>-<gap-number>` matching the review's gap numbering.
- Closing an entry: ~~strike-through~~ + `(closed in <commit-sha>)`.
- Items that turn out to be larger than expected get promoted to a dedicated commit / PR; remove the entry once the commit lands.
- Ad-hoc items not from a stage review: prefix with `misc-` and add a one-line context note.
