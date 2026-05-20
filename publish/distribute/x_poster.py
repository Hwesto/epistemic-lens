"""x_poster.py — post today's thread drafts to X (Twitter).

Reads `drafts/<DATE>_<story>_thread.json` (produced by
`publication.render_thread`), formats each as a chained X thread, and
posts via the X API v2 free tier (~50 posts/day cap, ample for 3–5
stories/day).

OAuth requirements (4 secrets, all must be present or job skips):
  - X_CONSUMER_KEY
  - X_CONSUMER_SECRET
  - X_ACCESS_TOKEN
  - X_ACCESS_TOKEN_SECRET

When any secret is missing the script exits 0 with `skipped: missing
X_*_TOKEN` so cron continues. See `human.md` and `docs/OPERATIONS.md` for
the one-time auth setup.

`--dry-run` prints the payloads each tweet would carry without posting,
even when tokens are present.

Usage:
  python -m distribution.x_poster                       # post today's threads
  python -m distribution.x_poster --date 2026-05-08
  python -m distribution.x_poster --dry-run             # never posts
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
DRAFTS = ROOT / "drafts"

REQUIRED_SECRETS = (
    "X_CONSUMER_KEY",
    "X_CONSUMER_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
)

X_TWEETS_ENDPOINT = "https://api.twitter.com/2/tweets"


def collect_thread_drafts(date: str, drafts_dir: Path = DRAFTS) -> list[Path]:
    return sorted(drafts_dir.glob(f"{date}_*_thread.json"))


def build_payloads(thread: dict, public_url_base: str | None = None) -> list[dict]:
    """Build the per-tweet payloads in posting order. Each tweet gets the
    `text`; first tweet additionally appends a public link to the per-story
    web page (if `public_url_base` is set)."""
    tweets = thread.get("tweets") or []
    if not tweets:
        return []
    payloads: list[dict] = []
    for i, t in enumerate(tweets):
        text = (t.get("text") or "").strip()
        if not text:
            continue
        if i == 0 and public_url_base:
            url = f"{public_url_base.rstrip('/')}/{thread['date']}/{thread['story_key']}/"
            text = f"{text}\n\n{url}"[:280]
        payloads.append({"text": text})
    return payloads


def post_thread_via_api(payloads: list[dict], oauth: tuple) -> list[dict]:
    """POST a chain of tweets to X. Returns per-tweet response (id + url)."""
    try:
        from requests_oauthlib import OAuth1Session  # type: ignore
    except ImportError:
        raise RuntimeError(
            "requests_oauthlib not installed. Add `requests-oauthlib>=1.3.0` to "
            "requirements.txt to enable live X posting. Without it, only "
            "--dry-run works."
        )

    consumer_key, consumer_secret, access_token, access_secret = oauth
    s = OAuth1Session(consumer_key, client_secret=consumer_secret,
                       resource_owner_key=access_token,
                       resource_owner_secret=access_secret)
    posted: list[dict] = []
    reply_to: str | None = None
    for p in payloads:
        body = dict(p)
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        r = s.post(X_TWEETS_ENDPOINT, json=body, timeout=30)
        if r.status_code != 201:
            raise RuntimeError(f"X API {r.status_code}: {r.text[:200]}")
        data = r.json().get("data") or {}
        tid = data.get("id")
        posted.append({"id": tid, "text": p["text"][:60] + "…" if len(p["text"]) > 60 else p["text"]})
        reply_to = tid
    return posted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None, help="YYYY-MM-DD; default: today UTC.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print payloads; never call X API.")
    ap.add_argument("--public-url-base", default="https://hwesto.github.io/epistemic-lens",
                    help="Base URL for per-story page link in the first tweet.")
    args = ap.parse_args()

    date = args.date or datetime.now(timezone.utc).date().isoformat()
    drafts = collect_thread_drafts(date)
    if not drafts:
        print(f"No thread drafts for {date}.")
        return 0

    # Live-token check (always; even with --dry-run we report what would happen)
    missing = [k for k in REQUIRED_SECRETS if not os.environ.get(k)]
    will_post = (not args.dry_run) and not missing
    if not will_post:
        if args.dry_run:
            print("(dry-run mode; would not post even with tokens)")
        if missing:
            print(f"skipped: missing {', '.join(missing)} — see human.md for auth setup")

    n_threads = 0
    n_tweets_total = 0
    for p in drafts:
        try:
            thread = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  skip {p.name}: {e}")
            continue
        payloads = build_payloads(thread, public_url_base=args.public_url_base)
        if not payloads:
            print(f"  - {p.stem:50s} no tweets")
            continue
        print(f"  ✓ {p.stem:50s} {len(payloads)} tweets")
        for i, pp in enumerate(payloads):
            preview = pp["text"][:80] + ("…" if len(pp["text"]) > 80 else "")
            print(f"      [{i+1}] {preview}")
        n_threads += 1
        n_tweets_total += len(payloads)
        if will_post:
            try:
                oauth = tuple(os.environ[k] for k in REQUIRED_SECRETS)
                posted = post_thread_via_api(payloads, oauth)
                ids = [d.get("id") for d in posted]
                print(f"      → posted: {ids}")
            except Exception as e:
                print(f"      ✗ post failed: {e}", file=sys.stderr)
                return 1

    print(f"\n{n_threads} threads, {n_tweets_total} tweets {'posted' if will_post else 'previewed'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
