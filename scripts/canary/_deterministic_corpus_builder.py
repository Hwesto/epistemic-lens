"""Builds canary/deterministic_corpus.json from inline templates.

Run once to (re)generate the fixed corpus. The corpus itself is the
load-bearing artifact; this script just constructs it deterministically
so the contents are reviewable as code rather than as a 4KB JSON blob.
"""
import json
from pathlib import Path

CORPUS = Path(__file__).parent / "deterministic_corpus.json"

# 4 buckets × 4 articles = 16 items. 2 languages (en, es), 2 buckets each
# (en→{usa, uk}; es→{spain, mexico}). This shape lets within_language_llr
# compare distinctive vocab across paired same-language buckets.

BUCKETS = [
    ("usa",    "en", "Reuters US"),
    ("uk",     "en", "Guardian UK"),
    ("spain",  "es", "El Pais"),
    ("mexico", "es", "Reforma"),
]

# Per-bucket distinctive vocabulary, four sentences each (~80 words). The
# vocab is deliberately divergent within a language so within_language_llr
# finds distinctive terms (us:WALL STREET vs uk:WESTMINSTER, es:MADRID vs
# mx:CHIHUAHUA, etc).
BODIES = {
    "usa": [
        "Wall Street trading volumes climbed sharply Tuesday as Treasury "
        "yields retreated following softer-than-expected Federal Reserve "
        "commentary. Bond markets repriced rate expectations across the "
        "curve. Wall Street strategists revised year-end S&P targets upward "
        "even as investors expressed caution about consumer discretionary "
        "earnings exposure ahead.",
        "Pentagon procurement officials briefed Congressional appropriators "
        "Wednesday about supply chain pressures affecting weapons system "
        "delivery timelines. Pentagon spokespeople declined to confirm "
        "specific program delays but acknowledged that industrial base "
        "constraints had complicated forward planning across multiple "
        "fiscal years.",
        "Wall Street consensus shifted markedly after Treasury auction "
        "results revealed stronger foreign demand for thirty-year paper. "
        "Pentagon analysts separately briefed lawmakers about strategic "
        "petroleum reserve drawdown timing options. Wall Street equity "
        "strategists characterised the macro backdrop as constructively "
        "uncertain rather than directional.",
        "Federal Reserve regional bank presidents speaking Thursday "
        "diverged sharply on appropriate policy paths through year-end. "
        "Wall Street economists noted that dissent within the policy "
        "committee had reached its highest level in eighteen months, "
        "complicating market expectations for the December meeting.",
    ],
    "uk": [
        "Westminster lobby correspondents reported Thursday that Treasury "
        "officials had begun preparing contingency scenarios for autumn "
        "fiscal event delivery. Westminster veterans noted that such "
        "preparations typically signal substantive policy revisions rather "
        "than cosmetic adjustments to existing announcements.",
        "Whitehall procurement teams briefed Commons select committee "
        "members about defence equipment procurement delays. Whitehall "
        "spokespeople emphasised that programme management reforms were "
        "ongoing. Westminster opposition figures pressed ministers for "
        "specific delivery timelines that officials declined to provide.",
        "Westminster political correspondents observed that backbench "
        "Conservative MPs had grown increasingly restive about polling "
        "trajectories ahead of expected local elections. Whitehall "
        "officials separately confirmed that civil service contingency "
        "planning for a possible general election had quietly commenced.",
        "Bank of England rate-setters speaking Thursday expressed "
        "divergent views about the persistence of services inflation. "
        "Westminster Treasury officials welcomed the variation as evidence "
        "of independent monetary judgement. Whitehall economists privately "
        "expressed concerns about credibility costs of further dissent.",
    ],
    "spain": [
        "Madrid manifestaciones del jueves reunieron a decenas de miles "
        "de trabajadores sanitarios protestando recortes presupuestarios "
        "autonómicos. Madrid sindicatos coordinaron acciones simultáneas "
        "en otras capitales autonómicas. Funcionarios del Ministerio de "
        "Sanidad declinaron comentar específicamente sobre las cifras "
        "alegadas de personal.",
        "La Moncloa confirmó miércoles que el Consejo de Ministros "
        "aprobaría próximamente un decreto-ley sobre vivienda. Madrid "
        "promotores inmobiliarios expresaron preocupación sobre "
        "potenciales restricciones al alquiler turístico. La Moncloa "
        "portavoces enfatizaron que cualquier medida sería temporal "
        "y revisable.",
        "Madrid analistas políticos observaron que las encuestas "
        "preelectorales sugerían volatilidad inusual en intención de "
        "voto. La Moncloa estrategas electorales preparaban escenarios "
        "alternativos. Madrid comentaristas señalaron que abstención "
        "joven podía resultar decisiva en circunscripciones marginales.",
        "Madrid Banco de España publicó martes proyecciones revisadas "
        "sobre crecimiento del PIB. La Moncloa economistas describieron "
        "la revisión a la baja como consecuencia de debilidad externa. "
        "Madrid analistas privados cuestionaron supuestos sobre consumo "
        "doméstico subyacente.",
    ],
    "mexico": [
        "Chihuahua autoridades estatales reportaron miércoles operativos "
        "conjuntos con fuerzas federales contra grupos criminales en la "
        "frontera norte. Chihuahua portavoces militares confirmaron "
        "detenciones múltiples sin proporcionar identidades específicas. "
        "Sonora autoridades vecinas coordinaron operativos paralelos en "
        "municipios fronterizos.",
        "Palacio Nacional jueves confirmó que la conferencia matutina "
        "presidencial abordaría reformas constitucionales pendientes. "
        "Chihuahua gobernadores opositores anunciaron una reunión "
        "preparatoria. Palacio Nacional voceros enfatizaron que el "
        "diálogo federal con entidades opositoras permanecía abierto.",
        "Chihuahua productores agrícolas presentaron quejas formales "
        "sobre asignaciones de agua transfronterizas con Texas. Sonora "
        "representantes apoyaron las demandas chihuahuenses. Palacio "
        "Nacional Secretaría de Relaciones Exteriores indicó que "
        "discusiones bilaterales con Washington proseguían discretamente.",
        "Chihuahua economistas regionales destacaron martes que la "
        "actividad maquiladora había mostrado resiliencia inesperada. "
        "Sonora analistas paralelos describieron tendencias similares en "
        "el sector minero. Palacio Nacional Secretaría de Economía citó "
        "los datos como evidencia de fortaleza nearshoring.",
    ],
}


def build() -> dict:
    snapshot_countries: dict = {}
    briefing_corpus: list[dict] = []

    for bucket, lang, feed_name in BUCKETS:
        items_snap: list[dict] = []
        for i, body in enumerate(BODIES[bucket]):
            article_id = f"canary_{bucket}_{i}"
            title = body.split(".")[0].strip()[:80]
            link = f"https://canary.example/{bucket}/{i}"
            items_snap.append({
                "id": article_id,
                "title": title,
                "link": link,
                "published": "2026-05-11T08:00:00Z",
                "summary": title,
            })
            briefing_corpus.append({
                "bucket": bucket,
                "feed": feed_name,
                "lang": lang,
                "title": title,
                "link": link,
                "signal_level": "body",
                "signal_text": body,
                "extraction_status": "ok",
                "via_wayback": False,
            })
        snapshot_countries[bucket] = {
            "label": bucket.upper(),
            "feeds": [{
                "name": feed_name,
                "lang": lang,
                "lean": "center",
                "item_count": len(items_snap),
                "items": items_snap,
            }],
        }

    # One intra-day duplicate so dedup has something to find: clone
    # usa[0] into uk's feed.
    dup = dict(snapshot_countries["usa"]["feeds"][0]["items"][0])
    dup["id"] = "canary_uk_DUP"
    snapshot_countries["uk"]["feeds"][0]["items"].append(dup)

    return {
        "snapshot": {
            "pulled_at": "2026-05-11T09:00:00Z",
            "date": "2026-05-11",
            "countries": snapshot_countries,
        },
        "briefing": {
            "date": "2026-05-11",
            "story_key": "canary",
            "story_title": "Deterministic canary corpus",
            "n_buckets": len(BUCKETS),
            "n_articles_total": len(briefing_corpus),
            "corpus": briefing_corpus,
        },
    }


if __name__ == "__main__":
    doc = build()
    CORPUS.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {CORPUS} ({CORPUS.stat().st_size:,} bytes)")
