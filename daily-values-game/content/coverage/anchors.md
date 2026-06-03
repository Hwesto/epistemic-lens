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

## The locked anchor set (MIRROR v2)

The four anchors are now **locked** and bound to specific story beats. They span
the spine's load-bearing trade-offs (with two probing the unvalidated extras,
Honesty/Autonomy, for longitudinal data on whether they earn their place).

| anchor_id            | conflict_edge              | beat | The bind (kept identical every re-run)                          |
|----------------------|----------------------------|------|-----------------------------------------------------------------|
| `anchor_equality_proportion` | `equality__proportionality` | Baker — split the tip jar | Split equally, or by contribution/desert.        |
| `anchor_honesty_autonomy`    | `honesty__autonomy`         | Baker — the letter about his daughter | Tell the truth, or respect his autonomy to not know. |
| `anchor_authority_honesty`   | `authority__honesty`        | Whistle — report it up, or sit on it | Comply with the chain, or disclose.       |
| `anchor_authority_care`      | `authority__care`           | Verdict — convict as the law demands, or refuse | Apply the rule, or protect the person.    |

> **Two anchors double as `[PROCESS]` beats** (Whistle memo, Verdict law-vs-gut).
> That is fine, but they must stay *identical forever* and **defection-free** — a
> costed temptation would shift their meaning and break both drift measurement and
> CNI matching. The DB enforces no-defection-on-anchor
> (`choices_no_defection_on_anchor`) and immutability (`gates_protect_anchors`).

## Cadence

- Each anchor re-runs on a fixed rotation. With 4 anchors and a ~quarterly
  rotation, a daily player meets each anchor ~4×/year — enough to estimate
  individual stability within a year. Crossed (norm/outcome) re-runs of these
  same anchors over time are what eventually enable true C/N/I extraction.
- Track via the `anchor_health` view (`db/schema.sql`): instances, distinct
  dates, and plays per family.
