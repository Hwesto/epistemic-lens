"""pipeline/commoncrawl_fallback.py — body extraction via Common Crawl News.

Trafilatura + Wayback fail systematically on outlets with aggressive paywalls
or anti-bot defenses (NYT, WaPo, WSJ, FT, Le Monde, Bild). The CC-NEWS
dataset crawls these legitimately as a public archive, and exposes a CDX
index API that maps URLs to WARC records.

This module is the **third-tier fallback**, called from
`pipeline/extract_full_text.py` only when:
  - the source feed is flagged `paywalled: true` in feeds.json, AND
  - trafilatura returned `extraction_status == "ERROR"`, AND
  - the Wayback fallback also failed.

Latency: CC-NEWS has a 1–2 week ingestion lag, so this fallback only helps
articles older than that. The daily pipeline still misses today's
paywalled coverage — that's a coverage limitation documented in
`docs/COVERAGE.md`, not a bug. Retroactive replays
(`python -m analytical.translate --date <past_date>` or running
`build_metrics` against historical briefings) DO benefit.

Network deps: `requests` (already in requirements.txt) plus `warcio` for
WARC parsing if available; gracefully skipped otherwise.

Usage (called automatically by extract_full_text):
  from pipeline.commoncrawl_fallback import fetch_body_via_cc
  text, status = fetch_body_via_cc(url, within_days=14)

Standalone (for one-off retroactive enrichment):
  python -m pipeline.commoncrawl_fallback https://example.com/article
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

CC_INDEX_API = "https://index.commoncrawl.org"
CC_NEWS_INDEX_PATTERN = "CC-NEWS-{year}-{week:02d}"  # weekly indices
DEFAULT_TIMEOUT = 20
DEFAULT_USER_AGENT = (
    "epistemic-lens/cc-fallback (https://github.com/hwesto/epistemic-lens)"
)


def _list_recent_news_indices(within_days: int = 21) -> list[str]:
    """Return CC-NEWS index names covering the last `within_days` days.

    CC-NEWS publishes new indices roughly weekly. We list the index
    catalogue and filter by date range.
    """
    try:
        r = requests.get(
            f"{CC_INDEX_API}/collinfo.json",
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        r.raise_for_status()
    except (requests.RequestException, ValueError):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[str] = []
    for entry in r.json():
        cdx_api = entry.get("cdx-api") or ""
        name = entry.get("id") or ""
        if not name.startswith("CC-NEWS"):
            continue
        # Index ids look like CC-NEWS-2026-15. Try to parse a date:
        try:
            # Older format: CC-NEWS-YYYY-MM-DD
            parts = name.replace("CC-NEWS-", "").split("-")
            if len(parts) == 3:
                d = datetime(int(parts[0]), int(parts[1]), int(parts[2]),
                             tzinfo=timezone.utc)
                if d >= cutoff:
                    out.append(cdx_api)
            # Newer format: CC-NEWS-YYYY-WW (week)
            elif len(parts) == 2:
                year = int(parts[0])
                week = int(parts[1])
                # ISO week -> approximate date
                d = datetime.fromisocalendar(year, week, 1).replace(
                    tzinfo=timezone.utc
                )
                if d >= cutoff:
                    out.append(cdx_api)
        except (ValueError, IndexError):
            continue
    return out


def _query_cdx(cdx_api: str, url: str) -> Optional[dict]:
    """Look up a URL in a single CC-NEWS CDX index. Returns first record."""
    try:
        r = requests.get(
            cdx_api,
            params={"url": url, "output": "json", "limit": 1},
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
    except (requests.RequestException, ValueError):
        return None
    body = r.text.strip()
    if not body:
        return None
    # CDX returns one JSON object per line.
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _fetch_warc_record(record: dict) -> Optional[bytes]:
    """Download a WARC range from CC's S3-hosted archive."""
    filename = record.get("filename")
    offset = record.get("offset")
    length = record.get("length")
    if not (filename and offset and length):
        return None
    url = f"https://data.commoncrawl.org/{filename}"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Range": f"bytes={int(offset)}-{int(offset) + int(length) - 1}",
    }
    try:
        r = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT * 2)
        r.raise_for_status()
        return r.content
    except (requests.RequestException, ValueError):
        return None


def _extract_body_from_warc(warc_gz_bytes: bytes) -> Optional[str]:
    """Parse the gzipped WARC fragment and return the response body's text.

    Uses warcio if available; falls back to a tolerant gzip+split parse.
    """
    try:
        import gzip
        import io
    except ImportError:  # standard library — should always be present
        return None
    try:
        decompressed = gzip.decompress(warc_gz_bytes)
    except OSError:
        return None
    # Try warcio for a clean parse:
    try:
        from warcio.archiveiterator import ArchiveIterator  # type: ignore
        for record in ArchiveIterator(io.BytesIO(warc_gz_bytes)):
            if record.rec_type == "response":
                payload = record.content_stream().read()
                try:
                    text = payload.decode("utf-8", errors="replace")
                except (LookupError, UnicodeError):
                    text = ""
                if text:
                    return _strip_html(text)
    except ImportError:
        pass

    # Fallback: split decompressed bytes on the WARC \r\n\r\n header boundary.
    sep = b"\r\n\r\n"
    if sep not in decompressed:
        return None
    parts = decompressed.split(sep, 2)
    if len(parts) < 3:
        return None
    body = parts[2].decode("utf-8", errors="replace")
    return _strip_html(body)


def _strip_html(text: str) -> str:
    """Use trafilatura if available; otherwise a simple tag strip.

    The daily pipeline already runs trafilatura at the primary tier; if
    we got here trafilatura is installed.
    """
    try:
        import trafilatura  # type: ignore
        out = trafilatura.extract(text, include_comments=False, include_tables=False)
        if out:
            return out
    except ImportError:
        pass
    import re
    return re.sub(r"<[^>]+>", " ", text)


def fetch_body_via_cc(
    url: str, within_days: int = 21
) -> tuple[Optional[str], str]:
    """Try Common Crawl News for the article body.

    Returns (text, status) where status is one of:
      - "ok"        body extracted successfully
      - "no_index"  CC-NEWS catalogue returned no matching indices
      - "no_record" indices found but URL not in any of them
      - "warc_failed" record found but WARC download/parse failed
      - "skipped"   network call deliberately skipped (e.g. dependency missing)
    """
    indices = _list_recent_news_indices(within_days)
    if not indices:
        return None, "no_index"
    record: Optional[dict] = None
    for cdx_api in indices:
        record = _query_cdx(cdx_api, url)
        if record:
            break
    if record is None:
        return None, "no_record"
    raw = _fetch_warc_record(record)
    if not raw:
        return None, "warc_failed"
    body = _extract_body_from_warc(raw)
    if not body:
        return None, "warc_failed"
    return body, "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url", help="URL to look up in CC-NEWS")
    ap.add_argument("--within-days", type=int, default=21)
    args = ap.parse_args()

    body, status = fetch_body_via_cc(args.url, args.within_days)
    print(f"Status: {status}")
    if body:
        print(f"Body length: {len(body)} chars")
        print()
        print(body[:1000])
        if len(body) > 1000:
            print("...")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
