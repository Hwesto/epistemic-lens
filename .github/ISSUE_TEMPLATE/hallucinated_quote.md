---
name: Hallucinated quote
about: Report a quote in the published analyses that isn't in the source article
title: "[correction] "
labels: correction, hallucination
assignees: ''
---

**This is a correction request.** Quote-grounding is supposed to be
verified by `analytical.validate_analysis` before publication, but
validation has gaps. Errors caught here get retracted within 24 hours.

## Where the quote appears

- **Date:**
- **Story key:** (e.g. `hormuz_iran`)
- **Where:**
  - [ ] Body analysis (`analyses/<DATE>_<story>.json`)
  - [ ] Headline analysis (`analyses/<DATE>_<story>_headline.json`)
  - [ ] Source attribution (`sources/<DATE>_<story>.json`)
  - [ ] Long-form draft (`drafts/<DATE>_<story>_long.json`)
  - [ ] Thread / carousel draft (`drafts/<DATE>_<story>_thread.json` etc.)

## The quote in question

(Paste the verbatim quote text as it appears in the published analysis.)

## The source article

- **URL:**
- **Outlet:**
- **Bucket (if known):**

## Why you believe it's hallucinated

- [ ] The exact wording does not appear in the article.
- [ ] The wording appears but is attributed to the wrong speaker.
- [ ] The wording appears but is from a different article entirely.
- [ ] Other (explain):

## Optional: what the article actually says

(If you can paste the closest-matching real quote, that helps.)

---

We retract by editing the canonical JSON, re-rendering MD, and appending
to `corrections.json` with the original claim, the correction, and the
source URL. The correction is timestamped and immutable.
