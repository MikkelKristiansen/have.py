import html as _html
import re as _re
import urllib.request
import urllib.parse
import json

WIKIDATA_SPROG    = "da"
WIKIDATA_FALLBACK = "en"


def wikidata_søg(søgeterm: str) -> list[dict]:
    """Søger Wikidata efter plante. Returnerer liste af kandidater."""
    params = urllib.parse.urlencode({
        "action": "wbsearchentities",
        "search": søgeterm,
        "language": WIKIDATA_SPROG,
        "fallbacklanguage": WIKIDATA_FALLBACK,
        "type": "item",
        "format": "json",
        "limit": 8,
    })
    url = f"https://www.wikidata.org/w/api.php?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "have.py/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return [
        {"id": h["id"], "label": h.get("label", ""), "description": h.get("description", "")}
        for h in data.get("search", [])
    ]


def wikidata_hent_plantedata(q_id: str) -> dict:
    """Henter latin + familie fra Wikidata via SPARQL."""
    sparql = f"""
SELECT DISTINCT ?latin ?familieNavn WHERE {{
  BIND(wd:{q_id} AS ?plante)
  OPTIONAL {{ ?plante wdt:P225 ?latin }}
  OPTIONAL {{
    ?plante wdt:P171+ ?familie .
    ?familie wdt:P105 wd:Q35409 .
    ?familie wdt:P225 ?familieNavn
  }}
}}"""
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
        {"query": sparql, "format": "json"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "have.py/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    bindings = data["results"]["bindings"]
    if not bindings:
        return {}
    b = bindings[0]
    return {k: b[k]["value"] for k in ("latin", "familieNavn") if k in b}


def wikidata_hent_foto_url(q_id: str) -> str | None:
    """Returnerer direkte Commons-URL til P18-billede, eller None."""
    sparql = f"""
SELECT ?p18Url WHERE {{
  BIND(wd:{q_id} AS ?plante)
  OPTIONAL {{
    ?plante wdt:P18 ?p18 .
    BIND(CONCAT(
      "https://commons.wikimedia.org/wiki/Special:FilePath/",
      STRAFTER(STR(?p18), "Special:FilePath/")
    ) AS ?p18Url)
  }}
}}"""
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
        {"query": sparql, "format": "json"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "have.py/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    b = data["results"]["bindings"]
    return b[0]["p18Url"]["value"] if b and "p18Url" in b[0] else None


def wikidata_hent_foto_metadata(foto_url: str) -> dict:
    """Henter licens og forfatter fra Commons API for en Special:FilePath-URL.

    Returnerer dict med: url, licens, forfatter (alle kan være None).
    """
    filnavn = urllib.parse.unquote(foto_url.split("Special:FilePath/")[-1])
    params = urllib.parse.urlencode({
        "action": "query",
        "titles": f"File:{filnavn}",
        "prop": "imageinfo",
        "iiprop": "extmetadata|url",
        "format": "json",
    })
    url = f"https://commons.wikimedia.org/w/api.php?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "have.py/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())

    pages = data.get("query", {}).get("pages", {})
    page  = next(iter(pages.values()), {})
    info  = (page.get("imageinfo") or [{}])[0]
    meta  = info.get("extmetadata", {})

    raw_forfatter = meta.get("Artist", {}).get("value", "")
    forfatter = _html.unescape(_re.sub(r"<[^>]+>", "", raw_forfatter)).strip() or None

    return {
        "url":       info.get("descriptionurl"),
        "licens":    meta.get("LicenseShortName", {}).get("value") or None,
        "forfatter": forfatter,
    }
