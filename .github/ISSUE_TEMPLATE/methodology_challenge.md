---
name: Methodology challenge
about: Disagree with a framing call or analytical choice
title: "[methodology] "
labels: methodology
---

## What's the analytical call you disagree with?

- **Date:**
- **Story key:** (e.g. `hormuz_iran`)
- **Frame ID or section:** (e.g. `ECONOMIC_BLOCKADE_EFFICACY`, "isolation_top", "Voices")
- **Specific claim or numeric value:**

(Link to the published analysis if helpful: `https://hwesto.github.io/epistemic-lens/<DATE>/<story>/`.)

## Which methodology element do you think is at fault?

- [ ] **Codebook** — the 15-frame Boydstun/Card categories don't accommodate the right reading.
- [ ] **Prompt** — `.claude/prompts/daily_analysis.md` instructs the analyzer in a way that produces this systematic mistake.
- [ ] **Bucket grouping** — feeds aggregated incorrectly in `feeds.json`.
- [ ] **Signal-text cap** — 1500-char body cap loses the framing-relevant content.
- [ ] **Source weighting** — `bucket_weights.json` over- or under-weights the relevant outlet.
- [ ] **Section operationalisation** — opinion / wire / news classification missed this item.
- [ ] **Other (explain):**

## What would the correct call have been?

(Be specific. "Frame X should have been Y because Z.")

## Is this one-off or systemic?

- [ ] **One-off** — this specific story / day. The methodology is fine in general.
- [ ] **Systemic** — the methodology will reproduce this mistake on similar stories.

## Evidence (optional but valued)

- Are there other dates / stories where the same mistake recurs?
- Have you hand-coded against the codebook? If yes, attach.
- Is there published academic critique of the codebook for this kind of case?

---

By filing this, you're contributing to the methodology audit trail. The
project does **not** retract published analyses based on framing
disagreement — the analyses are stamped to `meta_version` and read as
"what the system said on that day." But systemic challenges become
candidates for the next major pin bump's codebook + prompt revision.

See `web/methodology-challenge.html` and `docs/METHODOLOGY.md` for the
project's resolution policy.
