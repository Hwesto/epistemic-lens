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
| ~~**0-3**~~ | ~~Two different token-normalisation pipelines (`meta.tokenize` / `analytical.build_briefing._title_tokens`) share the stopword set but not the regex / plural-strip pipeline.~~ | Closed in `ac703c2` (meta-v2.4.0 Stage 5 part B): `_title_tokens` now `return set(meta.tokenize(s))`. New test `test_title_tokens_plural_stripped` pins the contract. | — |
| **0-4** | `meta.dir_hash(PROMPTS_DIR)` defaults `glob="*.md"`. New `.json` / `.yaml` / `.j2` prompt assets in `.claude/prompts/` would not be hashed and could drift silently. | No non-`.md` files exist in `.claude/prompts/` today. | When the first non-`.md` file is added under `.claude/prompts/`. Fix: pass `glob="*"` and skip hidden files / dirs explicitly. |
| ~~**0-5**~~ | ~~`canonical_stories.json` has no JSON Schema.~~ | Closed in `ba93c80` (Stage 5 part A): `docs/api/schema/canonical_stories.schema.json` added; `meta.canonical_stories()` validates against it on load so a typo in a regex pattern fails fast instead of silently never matching. | — |

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

## Stage 3 — Dedup

Stage deleted entirely — see commit "Stage 3: delete unused dedup
stage". Production audit found `pipeline/dedup.py`'s output was written
but never read by any downstream consumer. Gaps 3-1 through 3-11 from
the Stage 3 review are all moot. The only outstanding item that
references the deleted stage:

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **3-residue** | `feeds.json:meta.notes` still includes "dedup" in the pipeline-step list. Updating it requires a methodology pin bump (feeds.json content is hashed). | Documentation-only and inside a hashed file; not worth a bump on its own. | Bundle with the next intentional `feeds.json` edit (e.g. adding a feed). |

## Stage 4 — Daily health

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **4-min-A** | `trailing_means` reads full daily snapshots (~5 MB each × 7 days = ~35 MB IO + parse) just to recompute `items_per_bucket`, but the prior `_health.json` files already carry `items_per_bucket_now`. Reading the lighter sidecars would be ~50× faster. | At today's scale (once daily, ~5s wall time), the cost is rounding error. | When feed count expands enough that the trailing-mean read becomes a hot spot, or whenever `trailing_means` is next touched. |
| **4-min-B** | No top-level "ingest produced nothing today" alert. Per-bucket `volume_drop` fires if everything fails uniformly, producing N alerts but no concise summary signal. | Operationally the per-bucket alerts already surface the failure; an extra rollup adds noise more than signal. | If the cron starts having silent total-ingest failures that the per-bucket alerts don't make obvious. Add `n_items_zero` boolean or similar. |
| **4-min-C** | `extraction_per_bucket` is built even for buckets where every feed has zero items — fills the dict with all-zero status counts. | Cosmetic; downstream consumers handle zero counts fine. | Whenever `health_for` is next refactored. Skip the `setdefault` if `items` is empty. |
| **4-min-D** | Field-name asymmetry — `extraction_per_bucket` (singular) vs `items_per_bucket_now` / `items_per_bucket_avg7` (plural+suffix). Pinned by the schema now (Gap 4-1) so renaming requires a schema bump + downstream coordination. | Pure aesthetics; renaming costs more than the inconsistency. | Don't pick up unless renaming for another reason. |
| **4-min-E** | "Phase 9" stale historical naming was in the docstring (corrected in Stage 4 commit). Same pattern still appears in other modules ("v0.4" in ingest.py, etc). | Cosmetic; doesn't affect behaviour. | Whenever a module's docstring is rewritten for any other reason. |
| **4-min-F** | Test coverage of `health_for` is now 5 tests (Stage 4 added 4) but `trailing_means` itself has no direct tests. Currently exercised only indirectly via the live snapshot path. | Trailing-mean logic is simple and the e2e implicitly exercises it. | When `trailing_means` next changes. |

## Stage 5 — Build per-story briefings

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **5-min-A** | `fresh_pull/` directory references in `build_briefing.py` (lines 30, 195) — local-dev convention from an earlier era; no production code writes there. | Harmless preference; falling through to `snapshots/` when `fresh_pull/` is absent. | Whenever `build_briefing` is next refactored, drop the `fresh_pull` preference unless someone documents an active use. |
| **5-min-B** | `signal_breakdown` is computed from kept corpus only, not from candidates. Documents what made it through dedup, not what was tried. | By design — kept-counts match what every downstream consumer sees. | Don't pick up unless a "candidates pre-dedup" report becomes useful. |
| **5-min-C** | `extraction_status` and `via_wayback` are stamped on every corpus entry but no downstream consumer reads them today. | Provenance breadcrumbs — kept because cheap and potentially useful for future debugging. | If `briefing.schema.json` ever moves to `additionalProperties: false` and these need explicit declaration, decide then whether to keep or drop. |
| **5-min-D** | `matches_story` lowercases the search text once, then `re.search(p, txt, re.I)` adds case-insensitive flag — the flag is redundant since `txt` is already lowercase. The flag is kept because canonical_stories patterns may include character classes meant to be case-insensitive even after the text is normalised. | Cosmetic; code comment in Stage 5 part A explains the choice. | Don't pick up. |
| **5-residue** | Existing briefings on disk still use the old `n_articles_total` field (Gap 5-1's pre-rename name). `publication.build_index` falls back per-field so they continue producing correct api/ output, but the on-disk artifacts are stale. | Briefings are immutable historical artifacts; rewriting them under a new pin would be back-dating. The fallback makes the field-rename graceful. | Don't pick up. |

## Stage 6 — Compute metrics

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **6-min-A** | `bucket_isolation` silently omits buckets with no pairs (when only one bucket has vocab in the briefing). Edge case for tiny corpora; not documented. | Real corpora always have ≥2 buckets (build_briefing's `min_buckets` default is 4), so this can't fire in production today. | If the analytical pipeline is ever exercised on a single-bucket corpus, document the omission or emit `mean_jaccard: null`. |
| **6-min-B** | `bucket_exclusive_vocab` returns empty lists for buckets with no exclusive terms. Schema-friendly, but adds noise to the JSON. | Empty-list handling is uniform; pruning would require special-casing readers. | Don't pick up unless metrics file size becomes a concern. |
| **6-min-C** | Loop pattern `for term in c: df[term] += 1` (build_metrics.py, doc-frequency build) could be `df.update(c.keys())`. | Cosmetic; current form is unambiguous. | Whenever the function is next refactored. |
| **6-min-D** | The `method` string is computed at runtime from pinned values (`meta.TOKENIZER`, `meta.METRICS`). Useful for human-eyeball reading; could just point at `meta.METRICS` instead. | Documentation choice. | Don't pick up. |
| **6-min-E** | Implicit precision: `pairwise_jaccard` and `mean_jaccard` round to 3 decimal places at write time. Every consumer (LLM, validate_analysis, the analyses on disk) assumes 3 decimals. Load-bearing implicit; could pin as `meta.METRICS.jaccard_precision`. | Today consistent because all callers happen to use 3; not biting. | If a future consumer writes a Jaccard at different precision, pin then. |
| **6-min-F** | `briefings_for_date` uses an ad-hoc glob with `_metrics` suffix exclusion. Stage 2 factored a similar helper into `pipeline._paths` for canonical snapshot date globs; briefings have their own naming convention so the helper doesn't apply directly. | Only one caller; low value. | If a second module starts globbing briefings (e.g. a re-render utility), factor `analytical/_paths.py`. |

## Stage 7 — LLM analysis

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **7-2-followup** | Stage 7 part B aligned the prompt's `n_buckets >= 4` threshold with build_briefing's `--min-buckets=4` default, but the value still lives in two places (the prompt and the CLI default). A future change to one without the other re-opens the original drift. | Pinning `meta.BRIEFING.min_buckets_for_analysis` requires either (a) prompt-time substitution (templating breaks the static prompt + hashed-prompt model) or (b) accepting that the prompt holds it as plain text and a tooling check ensures equality. Neither is cheap. | If the threshold ever changes, pin it in `meta.BRIEFING` and add a `tests.py` assertion that the prompt's literal threshold matches. |
| **7-min-A** | Prompt step 6 (commit + push) is bash logic embedded in markdown. Works because claude-code-action runs in bash; brittle if the runtime context changes. | The agent has been reliable; replacing with a Python helper would mean teaching the prompt to call a helper, which it currently doesn't need. | If claude-code-action ever changes shell behaviour, lift the bash into `analytical/_agent_commit.py`. |
| **7-min-B** | No iteration bound on the validate-fix-retry loop in prompt step 3i. Worst-case pathological agent behaviour caught by `daily.yml: timeout-minutes: 30`. | Real LLM iterations resolve in 1-3 passes. The 30-minute job ceiling is the safety net. | If we ever see runaway iteration in production logs, add a `--max-attempts` flag to `validate_analysis` and reference from the prompt. |
| **7-min-C** | `--permission-mode bypassPermissions` is maximally permissive — agent can write any file, run any shell command. Necessary for autonomous analyze + draft + commit; risk concentration if a prompt is hijacked. | Tightening to a tool allowlist (e.g. `--allow-tools=Read,Write,Edit,Bash` only) requires testing that all current analyze + draft behaviours still complete. | Before any external/untrusted prompt content is loaded into the agent's context. |
| **7-min-D** | Three layers of schema validation (in-prompt agent, post-commit workflow, render-time). Defensive depth is good; not documented in one place. | Each layer's purpose is clear from the workflow comments; a single doc would help a new contributor. | Whenever `docs/ARCHITECTURE.md` is next refreshed. |
| **7-min-E** | Prompt step 5 ("print one summary line per story written") relies on the agent's stdout reaching the workflow log. Works today via `show_full_output: true`; coupled. | Working as designed. | Don't pick up. |

## Stage 8 — Validate analysis

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **8-min-A** | `_load_briefing` / `_load_metrics` don't re-validate loaded JSON shape against the briefing/metrics schemas. | Stage 5 + 6 enforce these schemas at write time; re-validating at read time would be belt-and-braces. | If a non-pipeline source ever writes briefings/metrics files. |
| **8-min-B** | `check_numbers` exclusive_vocab term comparison is exact-string + case-sensitive. | The pinned tokenizer lowercases; matches today. | If a future tokenizer change introduces case variation. |
| **8-min-C** | `check_citations` quote check is a *substring* match, not full quote match. Agent could legitimately cite a 3-word verbatim fragment that misrepresents surrounding context. | By design — a verbatim slice is "verbatim". Editorial review catches semantic distortion; the validator catches fabrication. | Don't pick up — it's a feature, not a bug. |
| **8-min-D** | check_schema uses `jsonschema.Draft202012Validator.iter_errors` (collect-all) where `meta.validate_schema` uses single-error raise. | Intentionally different — validate_analysis is a report-all-errors tool. Code comment added. | Don't pick up. |
| **8-min-E** | `main()` --date default uses inline `datetime.now(timezone.utc).strftime('%Y-%m-%d')`. Same pattern as other CLIs; could be a `meta.today()` helper. | Trivial; not worth a helper for one site. | Whenever a second CLI ever needs the same expression and we haven't already DRYed it. |

## Stages 9 — 21

(Not yet reviewed. Each stage's residue gets appended here as we go.)

## Convention

- New entries use the form `<stage>-<gap-number>` matching the review's gap numbering.
- Closing an entry: ~~strike-through~~ + `(closed in <commit-sha>)`.
- Items that turn out to be larger than expected get promoted to a dedicated commit / PR; remove the entry once the commit lands.
- Ad-hoc items not from a stage review: prefix with `misc-` and add a one-line context note.
