# Operations — Epistemic Lens

## Daily flow (cron)

The 07:00 UTC GitHub Actions cron runs two jobs end-to-end:

```bash
# Job 1: ingest (no secrets needed)
python ingest.py                # 235 feeds → snapshots/<date>.json (~2 min)
python extract_full_text.py     # +body text (top clusters + per-feed sample, ~3 min)
python dedup.py                 # collapse near-dup items
python daily_health.py          # health snapshot + alerts
python build_briefing.py        # per-story corpora → briefings/<date>_<story>.json
python build_metrics.py         # LaBSE cosine + isolation + exclusive vocab
git commit + push               # snapshots/, briefings/

# Job 2: analyze (needs CLAUDE_CODE_OAUTH_TOKEN secret — see setup below)
anthropics/claude-code-action@v1 with .claude/prompts/daily_analysis.md
git commit + push               # analyses/<date>_<story>.md
```

Total runtime: ~15 min for ingest, ~10-20 min for analyze. Each job is
within the 30-min timeout.

Videos are NOT auto-rendered. After the cron lands, a human picks angles
from the day's analyses and writes `video_scripts/<date>_<n>.json`.

## One-time setup: CLAUDE_CODE_OAUTH_TOKEN

The `analyze` job authenticates to Claude Code via your subscription
(no API charges). Set the token once:

```bash
# 1. Generate a long-lived OAuth token from your Claude.ai subscription
claude setup-token

# 2. Copy the printed value, then add it as a repo secret:
#      Settings → Secrets and variables → Actions → New repository secret
#      Name:   CLAUDE_CODE_OAUTH_TOKEN
#      Value:  (paste)
```

Without this secret the `analyze` job fails fast with a clear error
(precheck step in `daily.yml`); the ingest job still runs normally.

## Daily flow (manual / Claude Code)

After the cron commits the snapshot, build the day's videos:

```bash
git pull

# Generate per-story briefings from the latest snapshot
python build_briefing.py
# ⇒ briefings/<date>_hormuz_iran.json
# ⇒ briefings/<date>_turner_cnn.json
# ⇒ briefings/<date>_lebanon_buffer.json
# (and others matching the canonical-story patterns)

# Open Claude Code, paste the top 3 briefings, ask Claude to write
# video scripts in the schema documented in docs/ARCHITECTURE.md.
# Save to video_scripts/<date>_01_<slug>.json etc.

# Or write them by hand from the briefing corpus.

# Synthesize voice — two options:

# OPTION A — Piper (free, local, default)
#   Quality: decent. Some scenes can have audio crackling artefacts
#   even with the v0.6.1 lower-noise settings (noise-scale=0.4).
#   Use for testing; switch to ElevenLabs for final cut.
python synthesize_voiceover.py video_scripts/<date>_*.json
python synthesize_voiceover.py <id>.json --voice en_US-ryan-high  # try other Piper voices

# OPTION B — ElevenLabs free tier (10K chars/month, ~5-7 videos)
#   Production-grade prosody, no crackling, deep broadcaster voice.
#   1. Sign up at elevenlabs.io (free tier)
#   2. Generate an API key at https://elevenlabs.io/app/settings/api-keys
#   3. Set it as an env var:
export ELEVENLABS_API_KEY=sk-...
#   4. Run with --provider elevenlabs
python synthesize_voiceover.py <id>.json --provider elevenlabs            # default voice "Brian"
python synthesize_voiceover.py <id>.json --provider elevenlabs --voice Daniel  # British news-anchor
python synthesize_voiceover.py <id>.json --provider elevenlabs --voice Bill    # older male gravitas

# Available ElevenLabs voices (free tier): Brian, Adam, Bill, Antoni,
# Charlie, Daniel, Sam, George — see synthesize_voiceover.py
# ELEVENLABS_VOICES dict for IDs.
#
# Free tier characters used per video: ~600-900 chars (5-7 videos/month).
# When you exhaust the free quota, upgrade to Creator tier ($22/mo,
# 100K chars) for ~100 videos/month.

# Render the videos
python render_video.py video_scripts/<date>_*.json
# ⇒ videos/<date>_01_<slug>.mp4

# Post to TikTok / IG Reels / YT Shorts manually.
```

## Weekly flow

`weekly_rot.yml` runs Sundays 09:00 UTC:

```bash
python feed_rot_check.py 7      # last 7 days of _health.json
# ⇒ archive/review/rot_report_<date>.md
git commit + push
```

The rot report flags feeds that:
- Errored on ≥4 of the last 7 days
- Have been stub-only for ≥4 of the last 7 days
- Show declining item counts (last < half of first)

Review and either drop the feed or replace with an alternative URL.

## CI flow

`ci.yml` runs on every push to `main` or `claude/**`:

```bash
python -m unittest tests.py tests_edge.py    # 45 tests, ~12 s
# On main only or workflow_dispatch:
python tests_e2e.py                          # full pipeline smoke
```

## Health alerts

After each daily run, `daily_health.py` writes `snapshots/<date>_health.json`
which the GH Actions job summary surfaces. Two alert types:

**`volume_drop`** — bucket items dropped >50% vs trailing 7-day average.
  Usually means a feed broke or returned 0 items. Check the rot report
  next Sunday.

**`low_extraction`** — bucket has ≥5 items attempted but <50% returned FULL
  body extraction. Could mean:
    1. Anti-bot tightened on that outlet (try Wayback fallback or alt URL)
    2. The outlet now returns title-only RSS — analysis will fall back to
       summary signal automatically via `signal_text()`

Neither alert blocks the cron; they're informational.

## Replacing a broken feed

When the rot report flags a feed:

1. Look up the outlet's RSS in `feeds.json`
2. Try the obvious alternatives:
   - `<host>/feed/`, `<host>/rss`, `<host>/rss.xml`, `<host>/feeds/all.xml`
   - Their site-search RSS via Google News: `https://news.google.com/rss/search?q=site:<host>&hl=en`
   - rsshub.app routes: `https://rsshub.app/<outlet>/...` (some unreliable)
   - feedburner mirrors
3. Probe the candidate URL with a quick `requests.get` + xml parse
4. If working, edit `feeds.json` to swap the URL
5. Mark with status `OK` (or `RETRY` if it 403s from your dev machine but
   you expect it to work on GH Actions IPs — check the historical pattern
   in any `_health.json`)

## Adding a new feed

1. Add an entry to `feeds.json` under the appropriate country bucket:
   ```json
   {
     "name": "Outlet Name",
     "url": "https://example.com/rss",
     "lang": "en",
     "lean": "Centre-left, mainstream",
     "status": "OK"
   }
   ```
2. Run `python ingest.py` to verify it pulls
3. Run `python -m unittest tests.py::TestSchemaValidation::test_feeds_json_well_formed`
4. Commit the change

## Adding a new country bucket

1. Add `feeds.json` entry: `"countries": { "newcountry": { "label": "...", "feeds": [...] } }`
2. Add a camera preset in `video_template/src/cameraPresets.ts`:
   ```typescript
   nc: { center: [lon, lat], zoom: 4, flag: "🇨🇨", label: "COUNTRY" }
   ```
3. Add the country code → ISO numeric mapping in `video_template/src/components/WorldMap.tsx`
   if you want the country shape highlighted on the map
4. Add the regex pattern in `video_template/src/FramingVideo.tsx` `COUNTRY_FLAG_MAP`
   so video scripts can auto-detect the country from text

## Cost monitoring

Everything runs at $0/mo on GitHub free tier. If something starts costing
money it's because:
- You added Anthropic API calls (framing_pass.py future)
- You added ElevenLabs (replaces Piper for nicer voice)
- You added Sora/Runway video generation (replaces or augments Remotion)
- Your repo went private (free GH Actions minutes are limited for private repos)

## Manual smoke test

If you're not sure the pipeline still works:

```bash
SKIP_EMBED=1 MAX_ITEMS=5 python ingest.py    # tiny pull
python extract_full_text.py --max-per-feed 1 # one item per feed
python build_briefing.py
ls briefings/ video_scripts/ snapshots/
```

If those produce reasonable output, the pipeline is healthy.

## Posting flow (manual until B4)

1. Render videos via `python render_video.py video_scripts/<date>_*.json`
2. Manually upload each MP4 to:
   - TikTok (1080×1920 vertical, captions burned in)
   - Instagram Reels (same MP4 works)
   - YouTube Shorts (same MP4 works; tag #shorts)
3. Caption each post with the story_one_liner from the script
4. Link to your Substack newsletter in bio for funnel
5. Engage with comments for first 30 min after posting (algo signal)

Cross-post automation via Buffer or Later API is deferred to phase B4.
