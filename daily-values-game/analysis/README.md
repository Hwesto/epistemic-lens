# Analysis — turning the prior into a finding

A **separate, offline operation** (a notebook, not the live app — §1, §7). It
reads the immutable `choice_events` log and runs the psychometrics that decide
whether the framework prior survives contact with real behaviour.

> The single easiest self-deception here is overfitting noisy small-n data into
> spurious "data-derived" axes. The borrowed MFQ-2 framework is the guardrail.
> **Data-derived ≠ from-scratch.** A psychometrician runs this (§7).

## What you get, by data volume (§7)

| Data | What becomes answerable |
|------|-------------------------|
| Dozens of plays | Does the loop work (retention, completion, sharing)? Run a **mis-scored control reveal** to separate genuine accuracy from the Forer effect. |
| Hundreds on shared items | Which items **discriminate** (~50/50) vs are **dead** (95/5 → cut). A real **number** on the framing confound by comparing one edge across framings. |
| Hundreds–thousands, repeat plays | The **factor structure**: confirmatory (does MFQ-2 fit?) *and* exploratory (what emerges freely?). Do Care and Fairness separate? Do the extras earn their place? Does the Schwartz network appear? **The prior→finding moment.** |
| Longitudinal + anchors | **Test–retest reliability** (is individual signal stable or noise — make-or-break), consistency-vs-context, predictive check (does week-1 predict week-3). |

## The recalibration loop

1. Pull the raw log + gate tags (edge/scope/framing/process/response_ms).
2. Run confirmatory + exploratory factor analysis / IRT.
3. If the structure shifts, write a **new `framework_versions` row** with new loadings.
4. Re-score every profile from the immutable log under the new version.
   Old profiles are not edited in place — they are recomputed. Frameworks remain
   comparable because the log never changed.

## Setup

```bash
cd analysis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
jupyter lab   # notebooks/ (add your own; keep them out of the live app)
```

Connect read-only to the production replica via `DATABASE_URL`. **Read-only** —
the analysis layer never writes to `choice_events`.
