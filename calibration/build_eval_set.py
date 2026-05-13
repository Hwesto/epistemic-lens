"""build_eval_set.py — assemble the candidate pool for silver labeling.

PR2 Phase A. Reads `snapshots/<date>.json` over a date window, pools
articles per canonical story across four tiers, and writes a single
JSONL with one row per candidate for Opus to label.

Tiers (so the eval set isn't dominated by easy regex positives):

  Tier 1 — regex_positive
    Articles that the existing v8 regex matcher would assign to this
    story. Cheap to verify; tests that the embedding matcher
    reproduces existing behaviour on easy cases.

  Tier 2 — near_neighbor
    Articles regex-matched to an ADJACENT story (e.g. iran_nuclear vs
    hormuz_iran). The whole reason exclude-anchors doesn't scale is
    that disambiguating these is hard; this tier is where the new
    softmax-argmax assignment earns its keep.

  Tier 3 — non_latin_candidate
    Articles in Persian / Arabic / Hindi / Chinese / Japanese / Korean
    / Hebrew / Greek / Russian whose titles or signal_text mention
    proper nouns or entities related to the story (e.g. transliterated
    'Hormuz' or 'Lebanon'). Regex didn't match (it can't read these
    scripts) — these are the false negatives PR2 is built to fix.

  Tier 4 — true_negative
    Articles that don't match this story under any plausible reading
    (sport, weather, local crime, etc.). Sampled at random from the
    snapshot's non-matched pool. Tests that the embedding matcher
    doesn't over-claim.

Each row carries `article_id`, `title`, `signal_text` (first 500
chars), `lang`, `feed`, `link`, `bucket`, `tier`,
`regex_matched_story` (or null), and `candidate_story` (the story
this row is being evaluated FOR). The labeling script consumes this
JSONL and emits `eval_set.jsonl` with each row augmented by a
silver_label field.

Usage:
  python calibration/build_eval_set.py --start 2026-04-01 --end 2026-05-12
  python calibration/build_eval_set.py --target-per-story 30
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from datetime import date as date_cls, timedelta
from pathlib import Path

import meta

ROOT = meta.REPO_ROOT
SNAPSHOTS = ROOT / "snapshots"
CALIBRATION = ROOT / "calibration"
CANONICAL = meta.canonical_stories()

NON_LATIN_LANGS = {"fa", "ar", "hi", "zh", "ja", "ko", "he",
                    "th", "el", "ru", "uk", "bg", "sr", "ka"}

# Curated proper-noun hints per story for Tier 3 non-Latin discovery.
# These are transliterated entities the embedding matcher should pick up
# even when the article is in a non-Latin script. Loose substring match
# inside non-Latin headlines is the heuristic; the silver label is the
# final arbiter.
NON_LATIN_HINTS: dict[str, list[str]] = {
    "hormuz_iran":     ["هرمز", "خلیج", "خلیج فارس", "ایران", "霍尔木兹",
                         "伊朗", "イラン", "이란", "Ормуз"],
    "iran_nuclear":    ["نووي", "هسته‌ای", "هسته ای", "تخصیب", "اورانیوم",
                         "核", "イラン核", "이란 핵", "ядерн"],
    "lebanon_buffer":  ["لبنان", "حزب الله", "جنوب لبنان", "黎巴嫩",
                         "レバノン", "레바논", "Ливан"],
    "israel_palestine": ["غزة", "حماس", "اسرائيل", "إسرائيل", "الضفة",
                          "加沙", "ガザ", "가자", "Газа", "Израиль"],
    "ukraine_war":     ["украин", "україн", "русск", "путин", "путін",
                         "зеленский", "зеленський", "ウクライナ",
                         "우크라이나", "乌克兰"],
    "china_taiwan":    ["台湾", "台灣", "tayvan", "تایوان", "타이완", "대만"],
    "india_pakistan":  ["भारत", "पाकिस्तान", "कश्मीर", "بھارت", "باكستان",
                         "كشمير", "印度", "巴基斯坦", "克什米尔"],
    "climate_policy":  ["مناخ", "اقلیم", "气候", "気候", "기후"],
    "ai_regulation":   ["ذكاء اصطناعي", "هوش مصنوعی", "人工智能", "人工知能",
                         "인공지능"],
    "africa_political_transitions": ["انقلاب", "السودان", "النيجر",
                                       "苏丹", "尼日尔"],
    "eu_expansion":    ["انضمام", "الاتحاد الأوروبي", "歐盟", "欧盟", "EU"],
    "us_election_cycle": ["انتخابات", "2028", "选举", "選挙", "선거"],
    "vietnam_china_visit": ["越南", "ベトナム", "베트남"],
    "turner_cnn":      ["تيد تورنر", "特纳", "ターナー", "터너"],
    "hantavirus_cruise": ["هانتا", "هانتاویروس", "汉坦", "ハンタウイルス",
                            "한타바이러스"],
}


def _hash_id(feed: str, link: str) -> str:
    return hashlib.sha256(f"{feed}|{link}".encode("utf-8")).hexdigest()[:12]


def _regex_match(item: dict, story_key: str) -> bool:
    story = CANONICAL[story_key]
    txt = (item.get("title", "") + " "
           + item.get("summary", "") + " "
           + item.get("body_text", "")[:1500]).lower()
    for ex in story.get("exclude") or []:
        if re.search(ex, txt):
            return False
    return any(re.search(p, txt, re.I) for p in story["patterns"])


def _regex_match_any(item: dict) -> list[str]:
    """Returns ALL canonical stories this article regex-matches."""
    return [k for k in CANONICAL if _regex_match(item, k)]


def _non_latin_hint_match(item: dict, story_key: str) -> bool:
    hints = NON_LATIN_HINTS.get(story_key) or []
    if not hints:
        return False
    txt = (item.get("title", "") + " "
           + (item.get("summary") or "")[:500] + " "
           + (item.get("body_text") or "")[:500])
    return any(h.lower() in txt.lower() for h in hints)


def _signal_excerpt(item: dict, n: int = 500) -> str:
    body = item.get("body_text") or ""
    if len(body) >= 100:
        return body[:n]
    summary = item.get("summary") or ""
    if len(summary) >= 60:
        return summary[:n]
    return (item.get("title") or "")[:n]


def gather_candidates(start: str, end: str,
                       target_per_story: int = 30) -> list[dict]:
    """Walk snapshots in [start, end], return one labeled-candidate row
    per (article, candidate_story, tier) hit. Caller writes JSONL."""
    rng = random.Random(42)
    rows: list[dict] = []
    seen_ids: set[tuple[str, str]] = set()

    d = date_cls.fromisoformat(start)
    d_end = date_cls.fromisoformat(end)
    available_dates: list[str] = []
    while d <= d_end:
        p = SNAPSHOTS / f"{d.isoformat()}.json"
        if p.exists():
            available_dates.append(d.isoformat())
        d += timedelta(days=1)

    # Build per-story candidate pools in one pass.
    pools_by_story: dict[str, dict[str, list[dict]]] = {
        sk: {"tier1": [], "tier2": [], "tier3": [], "tier4": []}
        for sk in CANONICAL
    }
    # For Tier 4 random sampling: pool of articles that match NOTHING.
    tier4_global_pool: list[dict] = []

    for date_iso in available_dates:
        snap = json.loads((SNAPSHOTS / f"{date_iso}.json")
                          .read_text(encoding="utf-8"))
        for bucket_key, bucket in (snap.get("countries") or {}).items():
            for feed in bucket.get("feeds") or []:
                feed_name = feed.get("name") or ""
                lang = feed.get("lang") or "en"
                for item in feed.get("items") or []:
                    link = item.get("link") or ""
                    if not link:
                        continue
                    art_id = _hash_id(feed_name, link)
                    if art_id in {x[0] for x in seen_ids}:
                        continue
                    seen_ids.add((art_id, date_iso))

                    matches = _regex_match_any(item)
                    base = {
                        "article_id": art_id,
                        "date": date_iso,
                        "feed": feed_name,
                        "lang": lang,
                        "bucket": bucket_key,
                        "title": (item.get("title") or "")[:240],
                        "signal_text": _signal_excerpt(item, 500),
                        "link": link,
                        "regex_matched_stories": matches,
                    }

                    if matches:
                        for sk in matches:
                            pools_by_story[sk]["tier1"].append(base)
                        if len(matches) > 1:
                            # An article matching multiple canonical
                            # stories simultaneously is by definition a
                            # near-neighbor case for ALL of them.
                            for sk in matches:
                                pools_by_story[sk]["tier2"].append(base)
                    else:
                        # Regex-miss: check non-Latin hint match per story
                        if lang in NON_LATIN_LANGS:
                            for sk in CANONICAL:
                                if _non_latin_hint_match(item, sk):
                                    pools_by_story[sk]["tier3"].append(base)
                        tier4_global_pool.append(base)

    # Sample target_per_story rows across the four tiers per story.
    # Default mix: 30% tier1, 30% tier2, 30% tier3, 10% tier4.
    mix = {"tier1": int(target_per_story * 0.30),
           "tier2": int(target_per_story * 0.30),
           "tier3": int(target_per_story * 0.30),
           "tier4": max(1, target_per_story - 3 * int(target_per_story * 0.30))}

    for sk in CANONICAL:
        pools = pools_by_story[sk]
        for tier, count in mix.items():
            pool = list(pools[tier])
            if tier == "tier4":
                # Story-specific tier-4: random sample from the global
                # non-matched pool; we still ask "is this article about
                # `sk`?" of each one to validate true-negative behaviour.
                pool = tier4_global_pool
            rng.shuffle(pool)
            chosen = pool[:count]
            for row in chosen:
                rows.append({
                    **row,
                    "candidate_story": sk,
                    "tier": tier,
                })

    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-05-11",
                    help="Inclusive. May 12 reserved as held-out parity test.")
    ap.add_argument("--target-per-story", type=int, default=30,
                    help="Approximate row count per story across all tiers.")
    ap.add_argument("--out", type=Path,
                    default=CALIBRATION / "eval_set_candidates.jsonl")
    args = ap.parse_args()

    rows = gather_candidates(args.start, args.end, args.target_per_story)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Summary
    by_story = defaultdict(lambda: defaultdict(int))
    by_lang_per_story = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_story[r["candidate_story"]][r["tier"]] += 1
        by_lang_per_story[r["candidate_story"]][r["lang"]] += 1
    print(f"wrote {len(rows)} candidate rows to {args.out}")
    for sk in CANONICAL:
        t = by_story[sk]
        langs = by_lang_per_story[sk]
        non_lat = sum(n for l, n in langs.items() if l in NON_LATIN_LANGS)
        total = sum(t.values())
        print(f"  {sk:<32} total={total:>3} "
              f"t1={t['tier1']:>2} t2={t['tier2']:>2} "
              f"t3={t['tier3']:>2} t4={t['tier4']:>2} "
              f"non_latin={non_lat:>2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
