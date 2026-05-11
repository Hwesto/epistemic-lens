"""Distribution channels.

Each module here reads a generated draft (thread / carousel / long / video)
and posts it to an external channel via that channel's API. Modules are
secret-gated: if the required OAuth tokens aren't present in the
environment, the module exits cleanly with `skipped: no token` so the cron
doesn't fail.

Channels (Phase 2):
  - x_poster.py        — X / Twitter, reads drafts/<DATE>_*_thread.json
  - youtube_shorts.py  — YouTube Shorts, reads videos/<DATE>_*.mp4

Channels (Phase 3, deferred):
  - telegram_bot.py    — Telegram daily digest
  - newsletter.py      — Buttondown weekly digest
  - tiktok_uploader.py — TikTok video posts
  - ig_reels.py        — Instagram Reels
"""
