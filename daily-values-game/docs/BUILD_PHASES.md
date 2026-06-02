# Build phases

## Phase 0 — Validate (days–2 weeks, near-zero infra)

- Bare daily web page: today's story, tap choices, see the split, get a share
  card. **No accounts.**
- Share with a small circle (the Wordle "WhatsApp group" move).
- Hand-write ~15–30 stories **to the coverage plan, anchors planted from day one.**
- Track: do people return? share? does the read feel true **vs the mis-scored
  control**?
- Infra: one static page + one serverless function + a couple of tables. Free tier.

## Phase 1 — The web product (this scaffold's target)

- PWA: installable, offline shell, responsive.
- Accounts, **append-only choice log (richly tagged)**, private profile, periodic
  reveal, **share card** (server-rendered PNG), basic friend-diff.
- Daily email reminder (Resend). Admin/content tool + coverage tracker + 30–90
  story buffer.
- Privacy: policy, consent, account + data deletion, private-by-default.
- Analytics wired to the funnel: open → complete → share → return.

## Phase 2 — Depth & moat (quarters, data-gated)

- Real calibration (IRT/factor analysis) over the log, **replacing the prior
  loadings**; profiles re-scored under new `framework_versions`.
- Longitudinal "year in values", drift, consistency map (powered by the anchors).
- Recurring characters, the live moment, richer genres/mysteries.
- B2B/team layer on the same engine.
- Native app **if/when** push-retention and discoverability become the bottleneck.

## The one-line build order (§12)

> Plant the anchors and a coverage-planned story set → bare web page for friends →
> measure retention, sharing, and "does it feel true" vs a mis-scored control →
> PWA with accounts, the richly-tagged append-only log, private profile, and the
> share card → run confirmatory + exploratory analysis as data accrues → only then
> native, only when push/discovery demand it.
