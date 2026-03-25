#!/usr/bin/env python3
"""
epistemic-lens v0.2: RSS ingestion + multilingual embedding + clustering.
No translation. All languages embed into the same vector space.
"""

import json, os, sys, re, hashlib, ssl
from datetime import datetime, timezone
from pathlib import Path

# Fix SSL certificate issues on Windows
ssl._create_default_https_context = ssl._create_unverified_context

import feedparser
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_similarity

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Translation setup
try:
    import argostranslate.translate
    TRANSLATE_AVAILABLE = True
except ImportError:
    TRANSLATE_AVAILABLE = False


def translate_to_english(text, from_lang):
    """Translate text to English using argostranslate. Returns None if unavailable."""
    if not TRANSLATE_AVAILABLE or not text or from_lang == "en":
        return None
    try:
        return argostranslate.translate.translate(text, from_lang, "en")
    except Exception:
        return None
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "10"))
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "snapshots")
FEEDS_CONFIG = os.environ.get("FEEDS_CONFIG", "feeds.json")


def pull_feed(feed_info):
    url = feed_info["url"]
    try:
        d = feedparser.parse(url)
        if d.bozo and not d.entries:
            return {"name": feed_info["name"], "error": str(d.bozo_exception)[:100], "items": []}
        items = []
        for entry in d.entries[:MAX_ITEMS]:
            title = entry.get("title", "").strip()
            if not title:
                continue
            summary = entry.get("summary", entry.get("description", ""))
            if summary:
                summary = re.sub(r"<[^>]+>", "", summary).strip()[:500]
            items.append({
                "title": title,
                "link": entry.get("link", ""),
                "published": entry.get("published", entry.get("updated", "")),
                "summary": summary,
                "id": hashlib.md5(title.encode()).hexdigest()[:8],
                "_embed_text": f"{title}. {summary}" if summary else title,
            })
        # Translate non-English items
        lang = feed_info.get("lang", "en")
        if lang != "en" and TRANSLATE_AVAILABLE:
            for item in items:
                t_title = translate_to_english(item["title"], lang)
                t_summary = translate_to_english(item.get("summary", ""), lang)
                if t_title:
                    item["translation"] = {"title": t_title, "summary": t_summary or ""}
        return {"name": feed_info["name"], "lang": lang,
                "lean": feed_info.get("lean", ""), "item_count": len(items), "items": items}
    except Exception as e:
        return {"name": feed_info["name"], "error": str(e)[:200], "items": []}


def pull_all(config):
    now = datetime.now(timezone.utc)
    snapshot = {"pulled_at": now.isoformat(), "date": now.strftime("%Y-%m-%d"), "countries": {}}
    for key, country in config["countries"].items():
        print(f"  {country['label']}...")
        feeds = []
        for fi in country["feeds"]:
            print(f"    {fi['name']}...", end=" ")
            result = pull_feed(fi)
            print(f"{result.get('item_count', 0)} items" if result["items"] else "EMPTY")
            feeds.append(result)
        snapshot["countries"][key] = {"label": country["label"], "feeds": feeds}
    return snapshot


def embed_snapshot(snapshot, model):
    all_texts, all_meta = [], []
    for ckey, cdata in snapshot["countries"].items():
        for feed in cdata["feeds"]:
            for item in feed.get("items", []):
                all_texts.append(item["_embed_text"])
                all_meta.append({
                    "country": ckey, "country_label": cdata["label"],
                    "feed": feed["name"], "lang": feed.get("lang", "en"),
                    "lean": feed.get("lean", ""), "title": item["title"], "id": item["id"],
                })
    if not all_texts:
        return None
    vectors = model.encode(all_texts, show_progress_bar=True, batch_size=64)
    print(f"Embedded {len(vectors)} articles into {vectors.shape[1]}-dim space")
    return vectors, all_meta


def cluster_topics(vectors, eps=0.35, min_samples=3):
    dist = 1 - cosine_similarity(vectors)
    # Clamp floating-point noise to zero
    dist = np.maximum(dist, 0)
    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="precomputed").fit_predict(dist)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    print(f"Found {n_clusters} topic clusters, {list(labels).count(-1)} noise articles")
    return labels


def compute_convergence(labels, vectors, all_meta):
    clusters = {}
    for idx, label in enumerate(labels):
        if label == -1:
            continue
        clusters.setdefault(label, []).append({**all_meta[idx], "vector_idx": idx})

    results = []
    for label, articles in clusters.items():
        idxs = [a["vector_idx"] for a in articles]
        cluster_vecs = vectors[idxs]
        mean_sim = float(np.mean(cosine_similarity(cluster_vecs)))
        countries = set(a["country"] for a in articles)
        wire = [a for a in articles if a["country"] == "wire_services"]
        rep = wire[0]["title"] if wire else articles[0]["title"]
        results.append({
            "cluster_id": int(label), "representative_title": rep,
            "article_count": len(articles), "country_count": len(countries),
            "countries_present": list(countries), "feeds_present": list(set(a["feed"] for a in articles)),
            "mean_similarity": round(mean_sim, 3),
            "articles": [{"feed": a["feed"], "country": a["country_label"],
                          "lang": a["lang"], "title": a["title"]} for a in articles],
        })
    results.sort(key=lambda x: x["country_count"], reverse=True)
    return results


def compute_similarity_matrix(vectors, all_meta):
    feed_vecs = {}
    for idx, m in enumerate(all_meta):
        key = f"{m['country_label']} | {m['feed']}"
        feed_vecs.setdefault(key, []).append(vectors[idx])
    names = sorted(feed_vecs.keys())
    centroids = np.array([np.mean(feed_vecs[k], axis=0) for k in names])
    sim = cosine_similarity(centroids)
    return {"feeds": names, "matrix": [[round(float(v), 3) for v in row] for row in sim]}


def generate_prompt(snapshot, convergence, similarity):
    date = snapshot["date"]
    lines = [f"# Epistemic Lens - {date}\n"]

    lines.append("## HEADLINES BY COUNTRY\n")
    for cdata in snapshot["countries"].values():
        lines.append(f"### {cdata['label']}")
        for feed in cdata["feeds"]:
            lines.append(f"**{feed['name']}** ({feed.get('lang','en')}) - {feed.get('lean','')}")
            for item in feed.get("items", [])[:7]:
                lines.append(f"- {item['title']}")
            lines.append("")

    if convergence:
        lines.append("## SHARED STORIES (auto-detected cross-lingual clusters)\n")
        for c in convergence[:10]:
            lines.append(f"### {c['representative_title']}")
            lines.append(f"{c['country_count']} countries, {c['article_count']} articles, similarity: {c['mean_similarity']}")
            for a in c["articles"]:
                lines.append(f"  - [{a['lang']}] {a['feed']}: {a['title']}")
            lines.append("")

    if similarity:
        lines.append("## NEWSPAPER SIMILARITY (top pairs)\n")
        feeds = similarity["feeds"]
        pairs = []
        for i in range(len(feeds)):
            for j in range(i + 1, len(feeds)):
                pairs.append((feeds[i], feeds[j], similarity["matrix"][i][j]))
        pairs.sort(key=lambda x: x[2], reverse=True)
        lines.append("Most similar (echo chambers):")
        for a, b, s in pairs[:10]:
            lines.append(f"  {s:.3f} | {a} <-> {b}")
        lines.append("\nMost different (epistemic gaps):")
        pairs.sort(key=lambda x: x[2])
        for a, b, s in pairs[:10]:
            lines.append(f"  {s:.3f} | {a} <-> {b}")

    lines.extend([
        "\n## ANALYSIS TASK",
        "1. For shared stories: how does each outlet frame it?",
        "2. What does each outlet CALL the event?",
        "3. Which countries ABSENT from major stories?",
        "4. Claims converging across adversarial sources = likely facts",
        "5. Claims in only one bloc = likely spin",
        "6. Any outlet behaving unusually?",
        "7. Produce: Claim | Sources agree | Sources contradict | Confidence",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    print("=" * 60)
    print("EPISTEMIC LENS v0.2")
    print(f"{datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    with open(FEEDS_CONFIG) as f:
        config = json.load(f)

    snapshot = pull_all(config)

    print(f"\nLoading {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)

    convergence, similarity = None, None
    result = embed_snapshot(snapshot, model)
    if result:
        vectors, meta = result
        labels = cluster_topics(vectors)
        convergence = compute_convergence(labels, vectors, meta)
        similarity = compute_similarity_matrix(vectors, meta)

    # Clean and save
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    d = snapshot["date"]
    for c in snapshot["countries"].values():
        for f in c["feeds"]:
            for item in f.get("items", []):
                item.pop("_embed_text", None)

    for name, data in [("", snapshot), ("_convergence", convergence), ("_similarity", similarity)]:
        if data:
            with open(f"{OUTPUT_DIR}/{d}{name}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    prompt = generate_prompt(snapshot, convergence, similarity)
    with open(f"{OUTPUT_DIR}/{d}_prompt.md", "w", encoding="utf-8") as f:
        f.write(prompt)

    total = sum(sum(f.get("item_count", 0) for f in c["feeds"]) for c in snapshot["countries"].values())
    feeds = sum(len(c["feeds"]) for c in snapshot["countries"].values())
    print(f"\nDone: {feeds} feeds, {total} headlines")
    if convergence:
        print(f"Clusters: {len(convergence)}")
