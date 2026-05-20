"""youtube_shorts.py — upload today's videos to YouTube Shorts.

Reads `videos/<DATE>_*.mp4` (produced by the Remotion pipeline) and
uploads each as a YouTube Short via YouTube Data API v3 (free tier:
10k units/day; an upload is ~1600 units, so 5/day is comfortable).

OAuth requirements (3 secrets — refresh-token flow):
  - YT_CLIENT_ID
  - YT_CLIENT_SECRET
  - YT_REFRESH_TOKEN

The one-time auth dance (run locally, save the refresh token):
  1. Create a Google Cloud project, enable YouTube Data API v3.
  2. Add OAuth consent screen + create "Desktop app" credentials.
  3. Run a local OAuth flow (e.g. via `google-auth-oauthlib`) to get a
     refresh token granting `youtube.upload` scope.
  4. Add the three values to GitHub repo secrets.

When any secret is missing the script exits 0 with `skipped: missing
YT_*` so cron continues. See `human.md` and `docs/OPERATIONS.md`.

`--dry-run` prints upload metadata each video would carry without
uploading.

Usage:
  python -m distribution.youtube_shorts                       # upload today's
  python -m distribution.youtube_shorts --date 2026-05-08
  python -m distribution.youtube_shorts --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
VIDEOS = ROOT / "videos"
ANALYSES = ROOT / "analyses"

REQUIRED_SECRETS = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")

YT_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
YT_UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"

VIDEO_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d+)_(.+)\.mp4$")


def collect_videos(date: str, videos_dir: Path = VIDEOS) -> list[Path]:
    return sorted(videos_dir.glob(f"{date}_*.mp4"))


def build_metadata(video: Path,
                    analyses_dir: Path = ANALYSES) -> dict:
    """Build YT video resource (title, description, tags) from filename + analysis."""
    m = VIDEO_FILE_RE.match(video.name)
    if not m:
        return {"title": video.stem[:100],
                "description": "",
                "tags": ["epistemic-lens"]}
    date_iso, _ord, story_key = m.group(1), m.group(2), m.group(3)
    # Pull title + tldr from analysis if present
    a_path = analyses_dir / f"{date_iso}_{story_key}.json"
    title = story_key.replace("_", " ").title()
    description = ""
    tags: list[str] = ["epistemic-lens", "framing-analysis", date_iso]
    if a_path.exists():
        try:
            a = json.loads(a_path.read_text(encoding="utf-8"))
            title = (a.get("story_title") or title)[:100]
            description = (
                (a.get("tldr") or "")
                + "\n\nFull data: https://hwesto.github.io/epistemic-lens/"
                + f"{date_iso}/{story_key}/\n\n"
                + "Daily cross-country news framing analysis. 235 outlets, "
                + "54 buckets, 16+ languages."
            )[:5000]
            for t in (a.get("tags") or []):
                if t and t not in tags:
                    tags.append(str(t)[:30])
        except Exception:
            pass
    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags[:30],
            "categoryId": "25",  # News & Politics
        },
        "status": {
            "privacyStatus": "unlisted",  # default unlisted; user flips to public after review
            "selfDeclaredMadeForKids": False,
        },
    }


def refresh_access_token(client_id: str, client_secret: str,
                          refresh_token: str) -> str:
    """Exchange refresh token for a short-lived access token."""
    import requests  # standard
    r = requests.post(
        YT_TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"YT token refresh {r.status_code}: {r.text[:200]}")
    return r.json()["access_token"]


def upload_one(video_path: Path, metadata: dict, access_token: str) -> dict:
    """Resumable upload to YT Shorts. Returns the API response."""
    import requests  # standard
    # Step 1: initiate resumable upload
    init = requests.post(
        f"{YT_UPLOAD_ENDPOINT}?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(video_path.stat().st_size),
        },
        json=metadata,
        timeout=30,
    )
    if init.status_code != 200:
        raise RuntimeError(f"YT init {init.status_code}: {init.text[:200]}")
    upload_url = init.headers.get("Location")
    if not upload_url:
        raise RuntimeError("YT init: no Location header")
    # Step 2: PUT bytes
    with video_path.open("rb") as fh:
        put = requests.put(
            upload_url,
            data=fh,
            headers={"Content-Type": "video/mp4"},
            timeout=600,
        )
    if put.status_code not in (200, 201):
        raise RuntimeError(f"YT upload {put.status_code}: {put.text[:200]}")
    return put.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    date = args.date or datetime.now(timezone.utc).date().isoformat()
    videos = collect_videos(date)
    if not videos:
        print(f"No videos for {date}.")
        return 0

    missing = [k for k in REQUIRED_SECRETS if not os.environ.get(k)]
    will_upload = (not args.dry_run) and not missing
    if not will_upload:
        if args.dry_run:
            print("(dry-run mode; would not upload even with tokens)")
        if missing:
            print(f"skipped: missing {', '.join(missing)} — see human.md for auth setup")

    access_token: str | None = None
    if will_upload:
        access_token = refresh_access_token(
            os.environ["YT_CLIENT_ID"],
            os.environ["YT_CLIENT_SECRET"],
            os.environ["YT_REFRESH_TOKEN"],
        )

    n_uploaded = 0
    for v in videos:
        meta_payload = build_metadata(v)
        title = meta_payload["snippet"]["title"][:60]
        size_mb = v.stat().st_size / (1024 * 1024)
        print(f"  ✓ {v.name:40s} {size_mb:>5.1f} MB  {title}")
        if will_upload:
            try:
                resp = upload_one(v, meta_payload, access_token)  # type: ignore
                vid = resp.get("id", "?")
                print(f"      → uploaded: https://youtube.com/shorts/{vid}")
                n_uploaded += 1
            except Exception as e:
                print(f"      ✗ upload failed: {e}", file=sys.stderr)
                return 1

    print(f"\n{n_uploaded if will_upload else len(videos)} "
          f"{'uploaded' if will_upload else 'previewed'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
