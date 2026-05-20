# Archived scripts

These scripts are kept for reference but are not part of the active daily
pipeline.  Nothing in the cron, CI, or current code paths imports them.

  analysis.py    — 39-day cross-snapshot aggregation (one-off exploratory).
  analysis2.py   — side-by-side framing comparison (one-off exploratory).
  gdelt_pull.py  — GDELT 2.0 GKG firehose + DOC API breadth supplement.
                   Last live use: phase 7 of v0.4 build-out. DOC API path
                   was rate-limited in testing; bulk-GKG path works but
                   is not wired into the cron.

If you want to revive one, move it back to the repo root and re-add it
to the relevant workflow / docs.
