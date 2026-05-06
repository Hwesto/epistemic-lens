"""Phase 2b: try alternate URLs for the high-priority rejected feeds.

Acts as the human reviewer — known RSS paths for outlets where the
first guess returned 404. Re-probes only the alternates and merges
accepted ones back into review/probe_results.json.
"""
from __future__ import annotations
import concurrent.futures as cf
import json
from pathlib import Path

from candidate_probe import probe, REVIEW

ROOT = Path(__file__).parent

# (bucket, name, alt_url, lang, lean)
ALTERNATES = [
    # Lebanon
    ("lebanon", "L'Orient Today", "https://today.lorientlejour.com/feed", "en", "Centrist Francophone EN edition"),
    ("lebanon", "Naharnet", "https://www.naharnet.com/feeds/rss", "en", "Centrist independent"),
    # Iraq
    ("iraq", "Rudaw English", "https://www.rudaw.net/rss/english", "en", "Iraqi Kurdish — Erbil-based"),
    ("iraq", "Shafaq News English", "https://shafaq.com/en/rss", "en", "Independent Sunni-leaning"),
    ("iraq", "Kurdistan24 English", "https://www.kurdistan24.net/en/feed/rss", "en", "Kurdish independent"),
    # UAE
    ("uae", "The National", "https://www.thenationalnews.com/news/rss.xml", "en", "Abu Dhabi state-aligned flagship"),
    ("uae", "The National World", "https://www.thenationalnews.com/world/rss.xml", "en", "Abu Dhabi — world section"),
    ("uae", "Khaleej Times", "https://www.khaleejtimes.com/rss?cat=world", "en", "Dubai centrist"),
    ("uae", "Gulf News", "https://gulfnews.com/world/rss.xml", "en", "UAE establishment"),
    # Jordan
    ("jordan", "Roya News English", "https://en.royanews.tv/feed", "en", "Mainstream broadcaster"),
    # Palestine
    ("palestine", "WAFA English", "https://english.wafa.ps/RSS", "en", "PA news agency"),
    # Turkey
    ("turkey_extra", "Bianet English", "https://bianet.org/english/rss", "en", "Independent leftist"),
    ("turkey_extra", "Hurriyet Daily News", "https://www.hurriyetdailynews.com/index/rss", "en", "Secular establishment EN"),
    ("turkey_extra", "Duvar English", "https://www.duvarenglish.com/feed", "en", "Independent critical"),
    # Iran state
    ("iran_state_extra", "ISNA English", "https://en.isna.ir/Service/3/RSS", "en", "Iranian Students News Agency"),
    # Ukraine
    ("ukraine", "Kyiv Independent", "https://kyivindependent.com/feed/", "en", "Independent flagship"),
    ("ukraine", "Ukrinform English", "https://www.ukrinform.net/rss/block-lastnews", "en", "State news agency"),
    # Russia native
    ("russia_native", "Novaya Gazeta Europe", "https://novayagazeta.eu/rss/all.xml", "ru", "Exiled independent"),
    # Italy
    ("italy", "ANSA English", "https://www.ansa.it/english/english_rss.xml", "en", "Wire EN"),
    # Belgium
    ("netherlands_belgium", "Brussels Times", "https://www.brusselstimes.com/feed/", "en", "EN-language Belgian"),
    # Poland / Baltics
    ("poland_balt", "TVP World", "https://tvpworld.com/rss/news.xml", "en", "State EN-language"),
    ("poland_balt", "LRT English", "https://www.lrt.lt/en/news-in-english/rss", "en", "Lithuanian public broadcaster EN"),
    # Caucasus
    ("belarus_caucasus", "Eurasianet", "https://eurasianet.org/feeds/all.xml", "en", "Caucasus / Central Asia"),
    ("belarus_caucasus", "Belsat English", "https://belsat.eu/en/feed", "en", "Belarusian opposition"),
    # Indonesia
    ("indonesia", "Jakarta Post", "https://www.thejakartapost.com/rss", "en", "Centrist establishment EN"),
    ("indonesia", "Tempo English", "https://en.tempo.co/rss", "en", "Independent investigative"),
    # Philippines
    ("philippines", "Manila Times", "https://www.manilatimes.net/rss", "en", "Conservative establishment"),
    # Taiwan / NK
    ("taiwan_hk", "Focus Taiwan", "https://focustaiwan.tw/rss/aALL", "en", "State-affiliated EN"),
    ("korea_north", "KCNA Watch", "https://kcnawatch.org/feed/?type=rss", "en", "KCNA mirror"),
    # NZ
    ("australia_nz", "NZ Herald World", "https://www.nzherald.co.nz/arc/outboundfeeds/rss/section/world/", "en", "NZ centrist establishment"),
    # Canada
    ("canada", "Globe and Mail", "https://www.theglobeandmail.com/world/rss/", "en", "Centre establishment"),
    ("canada", "CTV News World", "https://www.ctvnews.ca/rss/ctvnews-ca-world-public-rss-1.822289", "en", "Centrist commercial"),
    # Mexico
    ("mexico", "El Universal MX", "https://www.eluniversal.com.mx/rss/web/seccion-mundo.xml", "es", "Mainstream centrist"),
    ("mexico", "Animal Politico", "https://animalpolitico.com/feed", "es", "Independent investigative"),
    # Chile / Colombia / Venezuela
    ("argentina_chile", "BioBio Chile", "https://www.biobiochile.cl/static/rss/internacional.xml", "es", "Independent CL"),
    ("colombia_ven_peru", "Semana Colombia", "https://www.semana.com/rss/news.xml", "es", "Right-leaning weekly"),
    # SA / Kenya / Africa
    ("south_africa", "News24 World", "https://feeds.24.com/articles/news24/world/rss", "en", "Mainstream commercial"),
    ("kenya", "Daily Nation Kenya", "https://nation.africa/kenya/world/rss.xml", "en", "Mainstream — Aga Khan"),
    ("kenya", "The Star Kenya", "https://www.the-star.co.ke/rss/", "en", "Mainstream commercial"),
    ("africa_other", "Daily Monitor Uganda", "https://www.monitor.co.ug/rss/world", "en", "Centrist UG"),
    ("africa_other", "The Citizen Tanzania", "https://www.thecitizen.co.tz/news/rss", "en", "Mainstream TZ"),
    # USA extra
    ("us_extra", "Axios World", "https://www.axios.com/feeds/feed.rss", "en", "Centrist explainer"),
    # Wire
    ("wire_extra", "Kyodo News English", "https://english.kyodonews.net/rss/all.xml", "en", "Japanese wire EN"),
    # Iran (replace dead Press TV via different rsshub route)
    ("iran_state_extra", "Press TV (alt rsshub)", "https://rsshub.app/presstv/iran", "en", "State broadcaster — Iran section"),
]

flat = [(b, {"name": n, "url": u, "lang": l, "lean": ln}) for b, n, u, l, ln in ALTERNATES]
print(f"Probing {len(flat)} alternate URLs...")
results = []
with cf.ThreadPoolExecutor(max_workers=15) as ex:
    for r in ex.map(probe, flat):
        results.append(r)
        marker = {"ACCEPT": "+", "ACCEPT_STUB": "~", "RETRY_FROM_PROD": "?", "REJECT": "-"}.get(r["decision"], " ")
        print(f"  {marker} [{r['decision']:<16}] {r['bucket']}/{r['name']:<35} {str(r['status'] or '-'):<4} items={r['items_count']:>2}  {r['reason'][:50]}")

# Merge into existing probe_results.json — keep best URL per (bucket, name)
existing = json.loads((REVIEW / "probe_results.json").read_text(encoding="utf-8"))
key_of = lambda r: (r["bucket"], r["name"])
existing_map = {key_of(r): r for r in existing}

for r in results:
    k = key_of(r)
    prev = existing_map.get(k)
    if prev is None:
        existing.append(r)
        existing_map[k] = r
        continue
    # Replace if alternate did better
    new_ok = r["decision"] in ("ACCEPT", "ACCEPT_STUB", "RETRY_FROM_PROD")
    prev_ok = prev["decision"] in ("ACCEPT", "ACCEPT_STUB", "RETRY_FROM_PROD")
    if new_ok and (not prev_ok or r["items_count"] > prev["items_count"]):
        for k2, v in r.items():
            prev[k2] = v

(REVIEW / "probe_results.json").write_text(
    json.dumps(existing, indent=2, ensure_ascii=False)
)

# Re-emit decisions.tsv
with (REVIEW / "decisions.tsv").open("w", encoding="utf-8") as f:
    f.write("decision\tbucket\tname\turl\tstatus\titems\tstub_pct\tfreshness_h\treason\n")
    for r in sorted(existing, key=lambda x: (x["decision"], x["bucket"], x["name"])):
        f.write("\t".join([
            r["decision"] or "",
            r["bucket"], r["name"], r["url"],
            str(r["status"] or ""), str(r["items_count"]),
            str(r["stub_pct"]), str(r.get("freshness_hours") or ""),
            (r["reason"] or "")[:120],
        ]) + "\n")

# Final tally
counts = {}
for r in existing:
    counts[r["decision"]] = counts.get(r["decision"], 0) + 1
print()
print("Updated tallies:")
for d, n in sorted(counts.items()):
    print(f"  {d:<18} {n}")
