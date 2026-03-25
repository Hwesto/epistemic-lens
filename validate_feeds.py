#!/usr/bin/env python3
"""
Feed validator — run this locally to check which RSS feeds are alive.
Outputs a status report and suggests replacements for dead feeds.
"""

import json
import sys
import os

try:
    import feedparser
except ImportError:
    os.system(f"{sys.executable} -m pip install feedparser --break-system-packages -q")
    import feedparser

import urllib.request
import urllib.error
from datetime import datetime


def check_feed(name, url, timeout=10):
    """Check if a feed URL returns valid RSS/Atom content."""
    try:
        # First check HTTP response
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 EpistemicLens/0.2"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        status = resp.getcode()

        # Then try parsing
        d = feedparser.parse(url)
        n_items = len(d.entries)
        has_error = d.bozo and not d.entries

        if n_items > 0:
            latest = d.entries[0].get("title", "")[:80]
            return {"status": "OK", "items": n_items, "latest": latest, "http": status}
        elif has_error:
            return {"status": "PARSE_ERROR", "items": 0, "error": str(d.bozo_exception)[:100], "http": status}
        else:
            return {"status": "EMPTY", "items": 0, "http": status}

    except urllib.error.HTTPError as e:
        return {"status": "HTTP_ERROR", "http": e.code, "error": str(e)[:100]}
    except urllib.error.URLError as e:
        return {"status": "UNREACHABLE", "error": str(e.reason)[:100]}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)[:100]}


def main():
    with open("feeds.json") as f:
        config = json.load(f)

    print("=" * 70)
    print("EPISTEMIC LENS — Feed Validation")
    print(f"Time: {datetime.utcnow().isoformat()}Z")
    print("=" * 70)

    ok, broken, empty = [], [], []

    for ckey, country in config["countries"].items():
        print(f"\n{'─' * 50}")
        print(f"  {country['label']}")
        print(f"{'─' * 50}")

        for feed in country["feeds"]:
            name = feed["name"]
            url = feed["url"]
            print(f"  {name:25s} ", end="", flush=True)

            result = check_feed(name, url)
            status = result["status"]

            if status == "OK":
                print(f"✓ OK  ({result['items']} items)")
                print(f"  {'':25s} Latest: {result['latest']}")
                ok.append({"country": country["label"], "name": name, "items": result["items"]})
            elif status == "EMPTY":
                print(f"⚠ EMPTY  (HTTP {result.get('http', '?')})")
                empty.append({"country": country["label"], "name": name, "url": url})
            else:
                err = result.get("error", "unknown")
                print(f"✗ {status}  {err}")
                broken.append({"country": country["label"], "name": name, "url": url, "error": err})

    # Summary
    total = len(ok) + len(broken) + len(empty)
    print(f"\n{'=' * 70}")
    print(f"RESULTS: {len(ok)}/{total} working, {len(empty)} empty, {len(broken)} broken")
    print(f"{'=' * 70}")

    if broken:
        print(f"\n✗ BROKEN FEEDS — need replacement URLs:")
        for b in broken:
            print(f"  [{b['country']}] {b['name']}")
            print(f"    URL: {b['url']}")
            print(f"    Error: {b['error']}")
            print()

    if empty:
        print(f"\n⚠ EMPTY FEEDS — responding but no items (may need different URL):")
        for e in empty:
            print(f"  [{e['country']}] {e['name']}")
            print(f"    URL: {e['url']}")
            print()

    # Save report
    report = {
        "checked_at": datetime.utcnow().isoformat(),
        "ok": ok, "empty": empty, "broken": broken,
        "summary": {"total": total, "ok": len(ok), "empty": len(empty), "broken": len(broken)},
    }
    with open("feed_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Report saved: feed_report.json")


if __name__ == "__main__":
    main()
