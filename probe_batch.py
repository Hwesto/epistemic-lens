"""Probe runner for arbitrary candidate files. Self-contained.

Usage: python3 probe_batch.py <candidates_file.json> [<output_results.json>]
"""
import concurrent.futures as cf
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.5"}


def strip_html(s):
    if not s: return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", unescape(s))).strip()


def parse_feed_items(body, max_n=10):
    if not body: return []
    if body.startswith(b"\xef\xbb\xbf"): body = body[3:]
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        tag = el.tag.split("}", 1)[-1]
        if tag not in ("item", "entry"): continue
        title = link = summary = published = ""
        for c in el:
            ct = c.tag.split("}", 1)[-1]
            text = (c.text or "").strip()
            if ct == "title": title = strip_html(text)
            elif ct == "link": link = (c.get("href") or text).strip()
            elif ct in ("description", "summary"): summary = strip_html(text)
            elif ct == "encoded" and not summary: summary = strip_html(text)
            elif ct in ("pubDate", "published", "updated", "date"): published = text
        if title:
            out.append({"title": title[:200], "link": link[:300], "summary": summary[:500], "published": published[:50]})
        if len(out) >= max_n: break
    return out


def parse_pub(s):
    if not s: return None
    s = s.strip().replace("GMT", "+0000").replace("UTC", "+0000")
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None


def probe(payload):
    bucket, feed = payload
    url = feed["url"]
    out = {
        "bucket": bucket, "name": feed["name"], "url": url,
        "lang_declared": feed.get("lang"), "lean": feed.get("lean", ""),
        "status": None, "ctype": None, "bytes": 0, "elapsed_s": None,
        "items": [], "items_count": 0, "error": None,
        "summary_avg_chars": 0, "stub_pct": 0, "is_google_news": False,
        "freshness_hours": None, "newest_published": None,
        "decision": None, "reason": None,
    }
    t0 = time.time()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        out["status"] = r.status_code
        out["ctype"] = (r.headers.get("content-type") or "")[:80]
        out["bytes"] = len(r.content)
        if r.status_code == 200 and r.content:
            items = parse_feed_items(r.content, max_n=10)
            out["items_count"] = len(items)
            out["items"] = items
            if items:
                lens = [len(i["summary"]) for i in items]
                out["summary_avg_chars"] = round(sum(lens) / len(lens), 1)
                stubs = 0
                for i in items:
                    s = re.sub(r"\s+", " ", i["summary"]).strip()
                    t = re.sub(r"\s+", " ", i["title"]).strip()
                    if not s or (s.startswith(t[:60]) and len(s) - len(t) < 40):
                        stubs += 1
                out["stub_pct"] = round(100 * stubs / len(items), 1)
                gn = sum(1 for i in items if "news.google.com" in i["link"])
                out["is_google_news"] = gn >= len(items) // 2
                ages = []
                for i in items:
                    dt = parse_pub(i["published"])
                    if dt:
                        ages.append((datetime.now(timezone.utc) - dt).total_seconds() / 3600)
                if ages:
                    out["freshness_hours"] = round(min(ages), 1)
    except requests.exceptions.SSLError as e:
        out["error"] = f"SSL: {str(e)[:60]}"
    except requests.exceptions.ConnectionError as e:
        out["error"] = f"CONN: {str(e)[:60]}"
    except requests.exceptions.Timeout:
        out["error"] = "TIMEOUT"
    except Exception as e:
        out["error"] = f"{e.__class__.__name__}: {str(e)[:60]}"
    out["elapsed_s"] = round(time.time() - t0, 2)

    if out["status"] == 200 and out["items_count"] >= 3:
        if out["stub_pct"] >= 80 and not out["is_google_news"]:
            out["decision"] = "ACCEPT_STUB"
            out["reason"] = f"stub_pct={out['stub_pct']}% — titles only, no body"
        elif out["freshness_hours"] is not None and out["freshness_hours"] > 24 * 14:
            out["decision"] = "REJECT"
            out["reason"] = f"stale: newest item {out['freshness_hours']:.0f}h old"
        else:
            out["decision"] = "ACCEPT"
            out["reason"] = f"items={out['items_count']}, summary={out['summary_avg_chars']}c, stub={out['stub_pct']}%, fresh={out['freshness_hours']}h"
    elif out["status"] in (403, 429):
        out["decision"] = "RETRY_FROM_PROD"
        out["reason"] = f"{out['status']} from container — likely UA/IP block"
    elif out["status"] == 200 and out["items_count"] == 0:
        out["decision"] = "REJECT"
        out["reason"] = "200 but no parseable items"
    else:
        out["decision"] = "REJECT"
        out["reason"] = out["error"] or f"http {out['status']}"
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: probe_batch.py <candidates.json> [output.json]")
    cand_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else cand_path.with_suffix(".probed.json")
    cands = json.loads(cand_path.read_text(encoding="utf-8"))
    flat = [(b, f) for b, cv in cands["countries"].items() for f in cv["feeds"]]
    print(f"Probing {len(flat)} candidates from {cand_path.name}...")
    results = []
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        for r in ex.map(probe, flat):
            results.append(r)
            m = {"ACCEPT": "+", "ACCEPT_STUB": "~", "RETRY_FROM_PROD": "?", "REJECT": "-"}.get(r["decision"], " ")
            print(f"  {m} [{r['decision']:<16}] {r['bucket']:<22}/{r['name']:<32} {str(r['status'] or '-'):>4} items={r['items_count']:>2}  {r['reason'][:50]}")
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    cnt = Counter(r["decision"] for r in results)
    print(f"\nTallies: {dict(cnt)}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
