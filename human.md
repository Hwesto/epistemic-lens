# Human-only requirements

Items the project genuinely needs a person to handle. AI assistants cannot
complete these from inside the harness. Maintained alongside the roadmap
(`/root/.claude/plans/review-my-project-stress-delightful-sunrise.md`).

## Pending now (post Phase 0 + Phase 1)

- [ ] **Push tags from a real client.** The harness's git relay returns HTTP
  403 on tag push. Tags exist locally on `claude/review-stress-test-06asX`.
  ```
  git push origin meta-v7.0.0 meta-v7.0.1 meta-v7.1.0
  ```
  After this session finishes, the list extends to `meta-v7.2.0` and
  `meta-v7.3.0` — push all five together.
- [ ] **Wait for / observe the next 07:00 UTC cron** on
  `claude/review-stress-test-06asX`. The cron is the live verification of
  every Phase 0 / Phase 1 / this-session change. The `mcp__github__*` tools
  available to me here don't expose `workflow_run` methods, so I cannot
  trigger or observe it from inside the harness.

## Distribution OAuth (Phase 2 — added this session)

The cron steps `distribution.x_poster` and `distribution.youtube_shorts`
exit cleanly with `skipped: no token` until the secrets land. Code is
shipped and tested without live tokens.

- [ ] **X / Twitter OAuth.**
  1. https://developer.x.com → create app (free tier — ~50 posts/day cap).
  2. Generate user-context OAuth 1.0a credentials (consumer key/secret +
     access token/secret).
  3. Add to GitHub repo secrets:
     - `X_CONSUMER_KEY`
     - `X_CONSUMER_SECRET`
     - `X_ACCESS_TOKEN`
     - `X_ACCESS_TOKEN_SECRET`
  4. See `docs/OPERATIONS.md` "X poster auth" section for screen-by-screen.
- [ ] **YouTube Data API v3 OAuth.**
  1. Google Cloud project → enable YT Data API v3.
  2. OAuth consent screen → desktop app credentials.
  3. Run the one-time auth flow locally (instructions in
     `docs/OPERATIONS.md` "YouTube Shorts auth").
  4. Add resulting refresh token + client_id + client_secret to repo
     secrets:
     - `YT_CLIENT_ID`
     - `YT_CLIENT_SECRET`
     - `YT_REFRESH_TOKEN`

## Branch + merge (after live-cron verification of Phase 2 + Phase 3a-c)

- [ ] **Merge to main.** From a real client or GitHub UI: open a PR from
  `claude/review-stress-test-06asX` → `main`, review the cumulative diff
  (Phase 0 + Phase 1 + this session's Phase 2 + Phase 3a-c), merge.
- [ ] **Tag `meta-v7.3.0` on main** after the merge.

## Tilt index public-claim commitment (Phase 4g — gate for v9.0.0)

The tilt-index machinery shipped in `meta-v7.4.0` (`analytical/tilt_index.py`,
`analytical/wire_baseline.py`) emits per-outlet log-odds vs the wire
baseline. The output today is **descriptive**: "outlet X uses bigram Y at
Z times the wire rate."

Turning that into a public claim ("outlet X tilts toward / away from
neutral") requires you to **commit publicly to defending the wire
baseline as your neutral anchor**. Three paths:

- [ ] **(A) Wire-as-neutral.** Adopt the existing `wire_services` bucket
      (Reuters + AP + AFP + Google News wires) as the neutral anchor.
      Document the choice in `docs/METHODOLOGY.md` with a rebuttal
      stanza addressing "why wire is descriptively the most low-frame
      copy in news." Pre-empts the obvious critique. This is the
      cheapest path; it's also the one most aligned with prior academic
      tilt-index work (Gentzkow-Shapiro).
- [ ] **(B) Anchor poles.** Pick two opposing-pole outlets per major
      story (e.g. FT vs Jacobin for English political coverage; Le Monde
      vs Russia Today for European geopolitics) and report tilt as
      distance from the midpoint of those poles. More principled but
      needs N anchors per region.
- [ ] **(C) Decline to publish tilt as a public claim.** Keep the
      machinery as internal data; publish bigram statistics without the
      "tilt vs neutral" framing.

Whichever path you choose, the renderer and methodology doc need an
update to match. After the commitment lands, the next pin bump is the
`9.0.0` major (the bump-rules call this longitudinal-comparability-
breaking because the public claim direction changes).

## Future-session prerequisites (listed for awareness, not yet actionable)

- **Phase 3d–3f distribution channels.** Telegram bot token, Buttondown
  newsletter API key, TikTok for Developers credentials, Meta Graph API
  (Reels, requires Business account + linked Facebook Page).
- **Phase 3g ElevenLabs Starter** (~$5/mo). User authorises and adds
  `ELEVENLABS_API_KEY` to repo secrets.
- **Phase 3h Anthropic vision metered budget** (~$5–15/mo). User authorises
  and adds an API key to repo secrets.
- **Phase 4a hand-code 100 articles.** The whole point is human ground
  truth; this cannot be delegated.
- **Phase 4d paid Krippendorff coders.** Payment + Upwork/Prolific
  contracting + coordination.
- **Phase 4g wire-baseline neutrality commitment.** Editorial / positioning
  decision the project owner alone can make.

## Operational notes

- **GitHub Actions free-tier minutes** (~2000 min/mo on free plan) — watch
  consumption. Phase 1 added ~3 min/day; Phase 2 + 3a-c will add another
  ~2 min/day. Comfortably within budget through Phase 3.
- **OAuth Claude Pro rate limits** (~5 messages / 5h) — current daily cron
  uses ~8 calls/day; Phase 2 headline-body adds ~3-5; Phase 3a source
  attribution adds another ~3-5. Total ~14-18 calls/day, still under Pro
  limits. If hits become frequent, escalate to metered Anthropic API
  (~$5-10/mo) per the roadmap.
