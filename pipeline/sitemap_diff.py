"""pipeline/sitemap_diff.py — RSS-vs-sitemap selection-bias audit.

Closes the open question raised by red-team Flaw F9: how big is the gap
between an outlet's RSS feed and what it actually publishes? The methodology
report says "RSS is what RSS is" — this script lets us put a number on it.

For a given outlet's (rss_url, sitemap_url) pair, fetch one week's items from
each, normalize URLs, and compute:

  - n_rss             items in RSS this week
  - n_sitemap         items in sitemap this week
  - n_intersection    URLs in both
  - rss_in_sitemap    fraction of RSS items that appear in sitemap (target: ~1.0)
  - sitemap_in_rss    fraction of sitemap items that appear in RSS (this is the
                       "selection bias" — what % of published output the RSS
                       feed actually emits)
  - missing_categories distribution of URL-path components for items present in
                       sitemap but absent from RSS (e.g. /opinion/, /sports/)

Output: stdout JSON or markdown table.

Usage:
  python -m pipeline.sitemap_diff \\
      https://www.bbc.co.uk/news/world/rss.xml \\
      https://www.bbc.co.uk/sitemaps/https-sitemap-com-news-1.xml

  python -m pipeline.sitemap_diff --batch outlets.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

DEFAULT_TIMEOUT = 25
DEFAULT_USER_AGENT = "epistemic-lens/sitemap-diff (audit; https://github.com/hwesto/epistemic-lens)"


def _fetch(url: str) -> bytes | None:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        return r.content
    except (requests.RequestException, ValueError):
        return None


def _parse_rss(body: bytes) -> list[dict]:
    """Tolerant RSS/Atom parse: return list of {url, pub_date_iso}."""
    out: list[dict] = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return out
    # RSS 2.0
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if link:
            out.append({"url": link, "raw_date": pub})
    # Atom
    if not out:
        # Strip namespace for tolerance
        for entry in root.iter():
            if entry.tag.endswith("entry"):
                link_el = next(
                    (e for e in entry if e.tag.endswith("link")), None
                )
                published = next(
                    (e for e in entry if e.tag.endswith("published") or e.tag.endswith("updated")),
                    None,
                )
                href = (
                    link_el.attrib.get("href") if link_el is not None else None
                )
                if href:
                    out.append({"url": href, "raw_date": (published.text if published is not None else "") or ""})
    return out


def _parse_sitemap(body: bytes) -> list[dict]:
    """Sitemap XML parse: return list of {url, raw_date}.

    Tolerant to nested sitemap-index files (returns child URLs to be
    fetched in a follow-up pass; left to the caller).
    """
    out: list[dict] = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return out
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "url":
            loc = next(
                (e.text for e in el if e.tag.endswith("loc")), None
            )
            lastmod = next(
                (e.text for e in el if e.tag.endswith("lastmod")), None
            )
            if loc:
                out.append({"url": loc.strip(), "raw_date": (lastmod or "").strip()})
        elif tag == "sitemap":
            # Index file — record loc but mark as nested
            loc = next(
                (e.text for e in el if e.tag.endswith("loc")), None
            )
            if loc:
                out.append({"url": loc.strip(), "raw_date": "", "_is_nested": True})
    return out


def _within_window(raw_date: str, days: int = 7) -> bool:
    """True if raw_date parses to within the last `days` days. Empty → True."""
    if not raw_date:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            d = datetime.strptime(raw_date.strip(), fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d >= cutoff
        except ValueError:
            continue
    return True  # parsable failure -> include


def _canonicalize(url: str) -> str:
    """Lower-case host + strip query params for comparable URL keys."""
    try:
        u = urlparse(url)
    except ValueError:
        return url
    netloc = u.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc.startswith("m."):
        netloc = netloc[2:]
    path = u.path.rstrip("/")
    return f"{u.scheme}://{netloc}{path}"


def _category_of(url: str) -> str:
    """First path component, e.g. /world/europe/x → /world."""
    try:
        u = urlparse(url)
    except ValueError:
        return ""
    parts = [p for p in u.path.split("/") if p]
    if not parts:
        return "/"
    return "/" + parts[0]


def diff_outlet(
    rss_url: str, sitemap_url: str, window_days: int = 7
) -> dict:
    """Compute the RSS-vs-sitemap diff for one outlet."""
    rss_body = _fetch(rss_url)
    sm_body = _fetch(sitemap_url)
    if rss_body is None and sm_body is None:
        return {"error": "both fetches failed", "rss_url": rss_url, "sitemap_url": sitemap_url}
    rss_items = _parse_rss(rss_body) if rss_body else []
    sm_items = _parse_sitemap(sm_body) if sm_body else []

    # If sitemap is an index, follow up to 3 child sitemaps
    nested = [s for s in sm_items if s.get("_is_nested")]
    if nested and not [s for s in sm_items if not s.get("_is_nested")]:
        for n in nested[:3]:
            child = _fetch(n["url"])
            if child:
                sm_items.extend(_parse_sitemap(child))
        sm_items = [s for s in sm_items if not s.get("_is_nested")]

    rss_recent = [i for i in rss_items if _within_window(i.get("raw_date", ""), window_days)]
    sm_recent = [i for i in sm_items if _within_window(i.get("raw_date", ""), window_days)]

    rss_urls = {_canonicalize(i["url"]) for i in rss_recent}
    sm_urls = {_canonicalize(i["url"]) for i in sm_recent}

    intersect = rss_urls & sm_urls
    missing_from_rss = sm_urls - rss_urls
    missing_categories = Counter(_category_of(u) for u in missing_from_rss)

    return {
        "rss_url": rss_url,
        "sitemap_url": sitemap_url,
        "window_days": window_days,
        "n_rss": len(rss_urls),
        "n_sitemap": len(sm_urls),
        "n_intersection": len(intersect),
        "rss_in_sitemap": (round(len(intersect) / len(rss_urls), 3) if rss_urls else None),
        "sitemap_in_rss": (round(len(intersect) / len(sm_urls), 3) if sm_urls else None),
        "missing_categories": missing_categories.most_common(10),
    }


def render_markdown(results: list[dict]) -> str:
    out: list[str] = []
    out.append("# RSS-vs-sitemap selection-bias audit")
    out.append("")
    out.append(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}Z")
    out.append("")
    out.append(
        "`sitemap_in_rss` is the fraction of items the outlet published in its "
        "sitemap during the window that also appeared in its RSS feed. "
        "Lower numbers mean larger selection bias — "
        "the RSS feed is a smaller and more curated slice of what the outlet "
        "actually publishes."
    )
    out.append("")
    out.append("| Outlet | RSS items | Sitemap items | Overlap | sitemap_in_rss | Top missing categories |")
    out.append("|---|---:|---:|---:|---:|---|")
    for r in results:
        if "error" in r:
            out.append(f"| `{r.get('rss_url','?')}` | ERROR | ERROR | ERROR | ERROR | {r['error']} |")
            continue
        cats = ", ".join(f"{c}({n})" for c, n in r["missing_categories"][:3])
        out.append(
            f"| `{r['rss_url']}` | {r['n_rss']} | {r['n_sitemap']} "
            f"| {r['n_intersection']} | {r['sitemap_in_rss']} | {cats} |"
        )
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rss_url", nargs="?", help="RSS feed URL")
    ap.add_argument("sitemap_url", nargs="?", help="Sitemap XML URL")
    ap.add_argument("--batch", type=Path,
                    help="JSON file of {outlet: {rss_url, sitemap_url}} pairs")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--md", action="store_true", help="Emit Markdown not JSON")
    args = ap.parse_args()

    pairs: list[tuple[str, str]] = []
    if args.batch and args.batch.exists():
        for outlet, urls in json.loads(args.batch.read_text(encoding="utf-8")).items():
            pairs.append((urls["rss_url"], urls["sitemap_url"]))
    elif args.rss_url and args.sitemap_url:
        pairs.append((args.rss_url, args.sitemap_url))
    else:
        ap.error("provide either --batch FILE or RSS_URL SITEMAP_URL")

    results = [diff_outlet(rss, sm, args.window_days) for rss, sm in pairs]
    if args.md:
        print(render_markdown(results))
    else:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
