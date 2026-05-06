"""Try rsshub.app routes for the GN-mediated outlets where direct RSS failed."""
from __future__ import annotations
import concurrent.futures as cf
import xml.etree.ElementTree as ET
import requests
import trafilatura

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "application/rss+xml,application/xml,*/*;q=0.5"}

CANDIDATES = [
    ("Reuters world (rsshub)", "https://rsshub.app/reuters/world/all"),
    ("Reuters world v2 (rsshub)", "https://rsshub.app/reuters/world"),
    ("AP world (rsshub)", "https://rsshub.app/ap/topics/world-news"),
    ("AP top stories (rsshub)", "https://rsshub.app/ap/topics/apf-topnews"),
    ("Arab News (rsshub)", "https://rsshub.app/arabnews"),
    ("Al Arabiya EN (rsshub)", "https://rsshub.app/alarabiya/english"),
    ("Korea Herald (rsshub)", "https://rsshub.app/koreaherald"),
    ("Al Ahram English (rsshub)", "https://rsshub.app/ahram/english"),
    # Alternatives via "feedburner-style" or feedx mirrors
    ("Reuters via feedx", "https://feedx.net/rss/reuters.xml"),
    ("Arab News via feedx", "https://feedx.net/rss/arabnews.xml"),
    ("Al Arabiya via feedx", "https://feedx.net/rss/alarabiya.xml"),
]


def parse_first_link(body):
    if body.startswith(b"\xef\xbb\xbf"): body = body[3:]
    try:
        root = ET.fromstring(body)
    except Exception:
        return 0, None
    n = 0
    first_link = None
    for el in root.iter():
        tag = el.tag.split("}", 1)[-1]
        if tag in ("item", "entry"):
            n += 1
            if first_link is None:
                for c in el:
                    if c.tag.split("}", 1)[-1] == "link":
                        first_link = (c.get("href") or (c.text or "")).strip()
                        break
    return n, first_link


def probe(label_url):
    label, url = label_url
    out = {"label": label, "url": url, "http": None, "items": 0,
           "sample_link": None, "sample_body": 0, "error": None}
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        out["http"] = r.status_code
        if r.status_code == 200 and r.content:
            out["items"], out["sample_link"] = parse_first_link(r.content)
            if out["sample_link"] and out["sample_link"].startswith("http"):
                try:
                    ar = requests.get(out["sample_link"], headers=HEADERS, timeout=15)
                    if ar.status_code == 200:
                        body = trafilatura.extract(ar.text, favor_recall=True) or ""
                        out["sample_body"] = len(body)
                except Exception as e:
                    out["error"] = f"sample: {e.__class__.__name__}"
    except Exception as e:
        out["error"] = f"{e.__class__.__name__}: {str(e)[:50]}"
    return out


print("Probing rsshub + feedx routes...\n")
with cf.ThreadPoolExecutor(max_workers=6) as ex:
    results = list(ex.map(probe, CANDIDATES))

print(f"{'Label':<32} {'http':>5} {'items':>5} {'body':>6}  notes")
print("=" * 100)
for r in results:
    flag = "✓" if (r["items"] > 0 and r["sample_body"] > 500) else ("·" if r["items"] > 0 else "✗")
    note = r["error"] or (r["url"] if not r["items"] else "")
    print(f"  {flag} {r['label']:<30} {r['http']:>5} {r['items']:>5} {r['sample_body']:>6}  {note[:50]}")
