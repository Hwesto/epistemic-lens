"""Probe candidate direct-RSS URLs to replace GN-mediated feeds.

For each outlet that's currently routed via Google News, try a list of
known/likely direct-RSS endpoints. Score each:
  OK  — 200 + parseable items + reachable article links
  STUB — 200 but title-only or 0 items
  DEAD — 4xx/5xx/parse-fail

Then verify that a sample article link from each working candidate is
actually fetchable (so trafilatura would extract body text from it).
"""
from __future__ import annotations
import concurrent.futures as cf
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests
import trafilatura

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.5"}

CANDIDATES = [
    # (outlet_label, [list of direct-RSS URLs to try])
    ("Reuters direct (markets/world)", [
        "https://www.reuters.com/world/rss",
        "https://www.reutersagency.com/feed/",
        "https://www.reuters.com/arc/outboundfeeds/v3/category/world/?outputType=xml",
    ]),
    ("AP News direct", [
        "https://apnews.com/index.rss",
        "https://apnews.com/hub/world-news.rss",
        "https://apnews.com/world.rss",
    ]),
    ("Arab News direct", [
        "https://www.arabnews.com/rss.xml",
        "https://www.arabnews.com/taxonomy/term/1/feed",
        "https://arab.news/rss",
    ]),
    ("Al Arabiya English direct", [
        "https://english.alarabiya.net/.mrss/feed.xml",
        "https://english.alarabiya.net/rss",
        "https://english.alarabiya.net/.mrss/en.xml",
    ]),
    ("Korea Herald direct", [
        "https://www.koreaherald.com/common/rss_xml.php?ct=102",
        "https://www.koreaherald.com/rss/020000000000",
        "https://news.koreaherald.com/rss/world.xml",
    ]),
    ("O Globo direct", [
        "https://oglobo.globo.com/rss/oglobo",
        "https://oglobo.globo.com/rss/",
        "https://oglobo.globo.com/rss.xml",
        "https://oglobo.globo.com/rss/mundo.xml",
    ]),
    ("Al Ahram English direct", [
        "https://english.ahram.org.eg/UI/Front/Inner/RssFeed.aspx?CategoryID=1",
        "https://english.ahram.org.eg/rss/world.aspx",
        "https://english.ahram.org.eg/rss.aspx",
    ]),
    ("Ahram Online (Arabic) direct", [
        "https://www.ahram.org.eg/RssFeeds.aspx",
        "https://gate.ahram.org.eg/RssFeeds.aspx",
        "https://www.ahram.org.eg/rss",
    ]),
]


def parse_count_items(body: bytes) -> int:
    try:
        if body.startswith(b"\xef\xbb\xbf"):
            body = body[3:]
        root = ET.fromstring(body)
    except ET.ParseError:
        return 0
    n = 0
    for el in root.iter():
        tag = el.tag.split("}", 1)[-1]
        if tag in ("item", "entry"):
            n += 1
    return n


def first_article_link(body: bytes):
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    for el in root.iter():
        tag = el.tag.split("}", 1)[-1]
        if tag in ("item", "entry"):
            for child in el:
                ctag = child.tag.split("}", 1)[-1]
                if ctag == "link":
                    return (child.get("href") or (child.text or "")).strip()
    return None


def probe(label_url):
    label, urls = label_url
    out = {"label": label, "best_url": None, "best_status": None,
           "best_items": 0, "best_extract_chars": 0,
           "tried": []}
    for url in urls:
        rec = {"url": url, "http": None, "items": 0, "error": None,
               "sample_link": None, "sample_body_chars": 0}
        try:
            r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            rec["http"] = r.status_code
            if r.status_code == 200 and r.content:
                rec["items"] = parse_count_items(r.content)
                if rec["items"] > 0:
                    sample = first_article_link(r.content)
                    if sample and sample.startswith("http"):
                        rec["sample_link"] = sample[:120]
                        try:
                            ar = requests.get(sample, headers=HEADERS, timeout=15)
                            if ar.status_code == 200:
                                body = trafilatura.extract(ar.text, favor_recall=True) or ""
                                rec["sample_body_chars"] = len(body)
                        except Exception as e:
                            rec["sample_body_chars"] = -1
                            rec["error"] = f"sample-fetch: {e.__class__.__name__}"
        except Exception as e:
            rec["error"] = f"{e.__class__.__name__}: {str(e)[:50]}"
        out["tried"].append(rec)
        # Track the best
        if rec["items"] >= max(out["best_items"], 1) and rec["sample_body_chars"] > out["best_extract_chars"]:
            out["best_url"] = url
            out["best_status"] = rec["http"]
            out["best_items"] = rec["items"]
            out["best_extract_chars"] = rec["sample_body_chars"]
    return out


print("Probing direct RSS for GN-mediated outlets...\n")
with cf.ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(probe, CANDIDATES))

print(f"\n{'Outlet':<35} {'Best URL':<55} {'http':>5} {'items':>5} {'body':>6}")
print("=" * 110)
for r in results:
    if r["best_url"]:
        u = r["best_url"][:53]
        print(f"  ✓ {r['label']:<33} {u:<55} {r['best_status']:>5} {r['best_items']:>5} {r['best_extract_chars']:>6}")
    else:
        print(f"  ✗ {r['label']:<33} (no working direct RSS found)")
        for t in r["tried"]:
            print(f"      tried {t['url'][:60]:<60} http={t['http']} items={t['items']} err={t['error']}")
