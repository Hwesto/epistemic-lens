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

## Stage 9 — Render MD

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **9-min-A** | Header field order is `Date / Story key / Coverage / Model / Methodology pin`. The pin is most relevant for longitudinal review and arguably should be more prominent. | Editorial preference; touching it changes every published .md and risks downstream parsers in `build_index.py` / `web/app.js`. | If we ever revisit the public-facing MD format end-to-end. |
| **9-min-B** | The footer template string (L141-145 of render_analysis_md.py) is inline, duplicated on every render. | Only one site; extracting to a constant gains nothing today. | If we ever want to change the wording. |
| **9-min-C** | `render()` is called unconditionally even when `frames` is empty. Schema currently requires `minItems: 2` (Stage 7 tightening), so unreachable today. | Defensive code without a real failure mode. | If schema's `minItems` floor on frames is ever loosened. |
| **9-min-D** | `**Model:** {a['model']}` displays the model name from the analysis JSON. If `restamp_analyses.py` (Stage 7) restamps `meta_version` without also restamping `model`, the two could drift. | Currently restamp only touches meta_version; model stays consistent because restamp leaves it alone. | If restamp ever gains the ability to rewrite other fields. |
| **9-min-E** | The `## Paradox` section header always renders, even when paradox is None (it prints `_No paradox in this corpus._`). | By design — explicit absence is more useful than silent omission for editorial review. | Don't pick up. |

## Stage 10 — Thread + carousel renderers

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **10-min-A** | `MAX_TWEET_CHARS=280`, `MAX_HOOK_CHARS=240`, `MAX_SLIDE_BODY_CHARS=200` hardcoded across renderers. Could move to `meta.PUBLICATION` for consistency with other pinned thresholds. | Stylistic; no consumer reads them. | If we ever add a fourth template renderer that needs the same limits, or want to vary platform limits per surface. |
| **10-min-B** | The `model` field stores `"template:render_thread.py"` / `"template:render_carousel.py"` for templates and the Claude model string for LLM artifacts. Same field name, different semantics. | Defensible — answers "what produced this?" in both cases. Frontend consumers don't currently parse `template:`-prefixed values. | If a downstream consumer ever needs to filter template vs LLM artifacts programmatically. |
| **10-min-C** | Thread `tweets[:8]` trim has the same architectural risk Gap 10-4 fixed in carousel — if a new tweet type is appended after `_outlet_finding_tweet`, the outlet finding (currently the last and most "human" tweet) drops first. | Today's max tweets is exactly 8, so the trim is a no-op. Comment-only risk. | If a 9th tweet type is ever added. |
| **10-min-D** | Carousel pad-to-4 floor logic (L165-178) is unreachable today (frames.minItems=2 guarantees ≥4 slides) AND incomplete (only adds 1 slide, can't pad from <3). | Defensive code without a real failure mode under current schemas. | If `analysis.schema.json` ever loosens `frames.minItems`. |
| **10-min-E** | The original carousel comment ("Silence (only if hook wasn't already a paradox covering similar ground)") contradicted the actual implementation, which added silence in both cases (gated by `len < 9` when hook was paradox). Stage 10's fix preserved the implementation semantics rather than the comment. Worth a deliberate review: should silence be skipped entirely when the hook is a paradox, or kept (as today)? | Editorial — both are defensible. The current behaviour is what we've published; changing it would alter live carousel drafts. | If editorial review decides paradox+silence is redundant on the same carousel. |
| **10-min-F** | `_frame_tweet` / `_frame_slide` only use `frame['evidence'][0]` even when multiple evidence entries exist. | By design — keeps tweets/slides compact. | Don't pick up. |

## Stage 11 — Long-form draft

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **11-min-A** | No verbatim-quote validator for long-form prose (analyses get one via `validate_analysis.check_citations`). A hallucinated `>` block would pass schema + link audit. | Hard to add — long-form is free prose, no `signal_text_idx` to ground against. Would need either prompt agent to emit citation indices, or fuzzy-match scan against briefing corpus. | If a published long-form is ever caught misquoting a source. |
| **11-min-B** | Word count enforcement is prompt-only (600-900 words). Schema's `minLength: 2500` chars enforces a rough floor (~400 words), no ceiling. | Word counts on existing 6 drafts span 590-759 — within range. Adding a `validate_long.py` would be the right mirror to `validate_analysis.py` but is not load-bearing today. | If we ever see drafts drift below 500 or above 1000 words. |
| **11-min-C** | Prompt step 4 (commit+push bash) is markdown-embedded bash, same pattern as Stage 7 Gap 7-min-A. | Working as designed under claude-code-action. | If the runtime context changes. |
| **11-min-D** | `long_link_audit` in `_shared.py` checks body→sources only. Doesn't verify URLs in `sources[]` actually come from the briefing's corpus. Agent could fabricate a URL, put it in both body_md and sources, and pass. | Stage-12 territory (build_index.py is the call site). Adding the briefing-URL check requires plumbing the briefing into the audit signature. | If audit ever fails on a real published draft, or as part of Stage 12's review. |
| **11-min-E** | The 6 backfilled long drafts now carry `meta_version: 2.5.0`, but they were actually written under earlier pins (probably 2.4.0 or lower). The "true" era is lost. | Honest acknowledgement: stamps reflect the pin under which the artifact was last stamped, not the pin under which it was originally written. Same convention as restamp_analyses. | Don't pick up — this is the accepted semantics. |
| **11-min-F** | The validator at `daily.yml:344-368` only validates EXISTING draft files; if the agent writes ZERO long drafts (silent failure), no error trips. | More an analyze-pipeline concern than long-form specifically. | Stage 19 (CI workflows). |

## Stage 12 — build_index.py

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **12-min-A** | Two regexes for parsing the `YYYY-MM-DD_<key>[_kind]` filename pattern (L57 + L88). Could unify. | Stylistic. | If a third caller ever needs the same parse. |
| **12-min-B** | `copy_web()` copies only top-level files in `web/`, silently dropping subdirectories. | `web/` currently has only flat files; not a real failure mode today. | If we ever add `web/img/`, `web/js/`, etc. |
| **12-min-C** | `extract_title` uses `or` chaining; empty string `""` falls through to next fallback. | Probably intentional — empty IS "no title". | Don't pick up. |
| **12-min-D** | `api/latest.json` empty-day fallback omits the `url` field that the happy-path version includes. Frontend may default-handle this, or may crash. | No reported frontend issue; Stage 13 review is the right place to check. | Stage 13 (web). |
| **12-min-E** | `main()` always returns 0 even when no stories were built. Workflow then publishes an empty/stale index instead of failing the deploy. | Defensible — don't break Pages on a bad day. | If editorial decides to fail-loud on empty days. |
| **12-min-F** | No `index.schema.json` exists for `api/<date>/index.json`. Frontend's expected shape is an implicit contract. | Adding a schema is a Stage 14 (schema corpus) item — would also pin the index hash. | Stage 14. |
| **12-min-G** | The api/ tree currently on disk is gitignored, so the stale 2.1.0 stamp on `api/2026-05-09/index.json` was invisible. Only a production rebuild refreshes it. | Working as designed — api/ is a build artifact. | Don't pick up. |

## Stage 13 — Web frontend

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **13-5** | Footer text `235 feeds · 54 buckets · 16+ languages` is hardcoded in `index.html`. Today's pin facts (235 feeds, 54 buckets) coincidentally align, but if feed count moves the footnote silently rots. | Best home is a `meta.json` endpoint exposing pin facts — natural Stage 14 work. | Stage 14 (schema corpus). |
| **13-min-A** | `escape()` in app.js handles only `& < >`. Fine for current text-content usage; risky if ever used inside HTML attribute context. | All current call sites are inside element text, never attributes. | If a future render path interpolates user content into `attr="${...}"`. |
| **13-min-B** | No per-day `<title>` or meta description (static SEO). | MVP-acceptable. | If we ever want indexed-by-date search visibility. |
| **13-min-C** | No cache-busting on `app.js` / `styles.css`. Pages caches aggressively. | Hash-suffixed URLs would force refresh; adds build complexity. | If a frontend change ever ships and users see stale assets. |
| **13-min-D** | `cardLinkUrl` returns `"#"` silently on unknown artifact type. | No caller passes unknown values today. | Defensive only. |
| **13-min-E** | `12-min-D` carry-over: latest.json empty-day shape omits `url` field. Verified handled — JS short-circuits on `!latest?.date` before consulting `url`. | Resolved by Stage 12's empty-day fallback design. | Don't pick up. |
| **13-min-F** | No client-side error reporting / telemetry. If Pages serves a broken latest.json, errors only surface in the UI. | Adds dependency + privacy considerations. | If post-deploy issues become hard to diagnose. |
| **13-min-G** | Frontend has no client-side schema awareness. If `analysis.schema.json` drifts, JS may crash on missing fields. | build_index validator gates writes into api/, so safe in practice; client validation would add a JS dep. | If a schema change ever produces an in-the-wild crash. |

## Stage 14 — Schema corpus

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **14-3** | `additionalProperties: true` on 5 schemas: briefing, canonical_stories, feeds, health, metrics. Strict-by-default catches typos + silent drift. | Tightening requires auditing every existing artifact for stray fields (e.g. legacy `n_articles_total` on briefings). Worth a dedicated pass. | When time allows, or if a stray field is ever discovered in production. |
| **14-6** | Carry-over 13-5: hardcoded footer `235 feeds · 54 buckets · 16+ languages` in index.html. Best home: new `meta.json` endpoint exposing pin facts. Requires meta.schema.json, build_index.write_meta_json(), and web/app.js fetch + render. | Bigger lift than other Stage 14 items. | When we want footer to reflect live pin facts rather than a snapshot. |
| **14-7** | All schemas declare Draft 2020-12 — consistent and good. | Already covered. | Don't pick up. |
| **14-8** | `$id` uses placeholder `https://epistemic-lens/...`. JSON Schema $id is for cross-schema $ref resolution; we don't use $ref across files. | Not load-bearing. | If we ever migrate to real domain or use cross-schema $ref. |
| **14-10** | No automated backward-compat regression test for schema tightenings. Manual verification per stage has sufficed. | Manual verification is OK at this scale; no production drift surfaced. | If a schema-tightening PR ever lands without manual artifact audit. |
| **14-min-A** | 4 legacy 2026-05-06 briefings now carry meta_version: 2.6.0 stamps — the pin under which they were backfilled, not the era they were originally written. Same convention as Stage 11 long-draft backfill. | Accepted convention: stamps reflect when stamping happened. Original era is lost. | Don't pick up. |

## Stage 15 — Weekly rot check

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **15-min-A** | `main()` accepts `n_days` parameter but thresholds (`error_days_min=4`, `stub_days_min=4`, `decline_min_history=4`) were calibrated for `_WINDOW_DAYS=7`. Running with `n_days=14` silently shifts false-positive rate. | Workflow passes 7 explicitly; CLI override is rarely used. | If a manual rot-check run with custom window ever lands a misleading report. |
| **15-min-B** | Summary `print()` counts at end of `main()` go to stdout but not to `GITHUB_STEP_SUMMARY` (only the .md file does). | Recoverable from the report itself. | If future rot dashboards need the counts. |
| **15-min-C** | Inversion of decline detection (Gap 15-1) wasn't caught for several pin eras. A self-check that cross-references this week's flagged feeds against last week's flag list could surface drift in the rot logic itself. | Defensive layer on top of the now-tested logic. | If a similar inversion recurs. |
| **15-min-D** | Workflow runs only on Sundays. A feed that goes dark mid-week isn't surfaced until up to 7 days later. | Designed cadence — rot is intentionally slow-moving review. | If a critical-bucket dark-feed window is ever a problem. |

## Stage 16 — source_audit.py

| ID | Item | Why deferred | Trigger to pick up |
|---|---|---|---|
| **16-min-A** | Section 6 "STORY-RELEVANT GAPS" (L348-369 pre-refactor) hardcodes editorial commentary about Iran/Russia/China narratives ("the 39-day dominant story"). Frozen in the codebase; will rot. | Editorial; not load-bearing. | If a developer updates the narrative focus, refactor to a sidecar `narrative_gaps.md` file the script reads. |
| **16-min-B** | Hardcoded UA string. | Cosmetic. UA strings rot. | If a feed ever rejects this exact UA. |
| **16-min-C** | Section 2 prints a 235-row flat table — no filtering / grouping. | Editorial. | If output becomes unreadable. |
| **16-min-D** | The 6 audit sections aren't pulled into individual top-level functions (`static_audit()`, `snapshot_health()`, etc.). One big `main()` retains the procedural shape — easier to read but harder to unit-test sections independently. | Stage 16 prioritised the import-side-effect fix. Section-level extraction is scope creep. | If we ever want fine-grained test coverage of individual audit sections. |
| **16-min-E** | `REGIONS["present"]` entries use mixed forms — plain bucket keys (`"usa"`) plus editorial annotations (`"wire_services (FR via AFP)"`). The sanity check skips annotation forms. | The annotation form is editorial human context that's useful in stdout. Splitting into separate `present_keys: list[str]` + `present_note: str` would be cleaner but invasive. | If the sanity check ever produces a false negative because an annotation form hid a real stale key. |

## Stages 17 — 21

(Not yet reviewed. Each stage's residue gets appended here as we go.)

## Convention

- New entries use the form `<stage>-<gap-number>` matching the review's gap numbering.
- Closing an entry: ~~strike-through~~ + `(closed in <commit-sha>)`.
- Items that turn out to be larger than expected get promoted to a dedicated commit / PR; remove the entry once the commit lands.
- Ad-hoc items not from a stage review: prefix with `misc-` and add a one-line context note.
