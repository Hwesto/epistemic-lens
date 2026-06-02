# Anchors — the measurement-invariance ruler

> **Plant these first, before anything else.** Anchors are the *only* way to ever
> measure drift, test–retest reliability, and whether an individual's signal is
> stable or noise (the make-or-break question). **Not planted now = lost forever.**
> Anchors cannot be added retroactively (§5, §10).

## What an anchor is

An anchor is a conflict that recurs **unchanged, forever**. Same edge, same fork,
same options, same loadings. Re-run on a cadence (e.g. roughly quarterly) so each
user encounters each anchor multiple times across their history.

Because the fork never changes, an anchor lets us ask: *given the same dilemma
months apart, does this person choose the same way?* That is test–retest
reliability and drift. Nothing else can measure it.

## Hard rules

1. **Immutable.** Once an anchor gate is created it is **never edited**. The DB
   enforces this (`gates_protect_anchors` trigger); the admin tool must also block it.
2. **Stamped.** Every anchor shares an `anchor_id` across its repeated instances.
3. **Stable loadings.** An anchor's `axis_loadings` must not be re-tagged under a
   new framework_version in a way that changes the fork's meaning. (Re-scoring the
   *population* under a new framework is fine — that reads the immutable choice;
   it does not edit the anchor.)
4. **Spread, don't cluster.** Place anchor re-runs on different dates so a user
   meets the same anchor at intervals, not back-to-back.

## The starter anchor set (~3–5 families)

These span the spine's load-bearing trade-offs. Designate them in Phase 0.

| anchor_id            | conflict_edge              | The bind (kept identical every re-run)                          |
|----------------------|----------------------------|-----------------------------------------------------------------|
| `anchor_care_honesty`        | `care__honesty`        | Protect someone from a painful truth, or tell it.               |
| `anchor_equality_proportion` | `equality__proportionality` | Split equally, or by contribution/desert.                  |
| `anchor_loyalty_authority`   | `loyalty__authority`   | Cover for your group, or comply with a legitimate rule.         |
| `anchor_authority_autonomy`  | `authority__autonomy`  | Defer to legitimate authority, or follow your own judgement.    |
| `anchor_care_purity`         | `care__purity`         | Relieve suffering via a means that violates a sanctity norm.    |

> Note: `authority__autonomy` deliberately probes an **unvalidated extra**
> (autonomy). It is included as an anchor so we get *longitudinal* data on whether
> the extra earns its place — but the corpus still must not over-invest in extras
> elsewhere (§3, §5).

## Cadence

- Each anchor re-runs on a fixed rotation. With 5 anchors and a ~quarterly
  rotation, a daily player meets each anchor ~4×/year — enough to estimate
  individual stability within a year.
- Track via the `anchor_health` view (`db/schema.sql`): instances, distinct
  dates, and plays per family.
