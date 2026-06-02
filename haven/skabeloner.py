"""haven.skabeloner — Jinja2-miljø + skabelonfiltre + kontrast_farve.

Render-lagets fundament i cli-opdelingen (se briefs/cli-opdeling.md, fase 3).
Bygger Jinja-environmentet og registrerer alle skabelonfiltre. Afhænger af
kontekst (MÅNEDER) + indlaes (opslag_plante) — ikke af generering/feeds/soeg.

VIGTIGT: template-stien resolver via Path(__file__).parent / "templates", dvs.
haven/templates/ — uafhængigt af cwd, præcis som da koden lå i cli.py. En lokal
templates/-mappe i projektroden vinder dog over pakkedata (lokal tilpasning).
"""

import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .kontekst import MÅNEDER, MÅNEDER_LANG
from .indlaes import opslag_plante

__all__ = ["lav_jinja_env", "kontrast_farve"]


def kontrast_farve(hex_farve: str) -> str:
    hex_farve = (hex_farve or "").lstrip("#")
    if len(hex_farve) != 6:
        return "#000000"  # Manglende/ugyldig farve — antag lys baggrund, sort tekst
    try:
        r, g, b = (int(hex_farve[i:i+2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return "#000000"
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    luminans = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return "#000000" if luminans > 0.179 else "#ffffff"


# ── Jinja2-miljø ───────────────────────────────────────────────────────────────

def lav_jinja_env():
    _lokal = Path.cwd() / "templates"
    template_mappe = str(_lokal if _lokal.is_dir() else Path(__file__).parent / "templates")
    env = Environment(loader=FileSystemLoader(template_mappe), autoescape=False)

    # Filter: aktiv afgrøde fra en zone
    def aktiv_afgrøde(zone):
        måned = datetime.date.today().month

        def _beret(afgrøde, næste=None):
            pid = afgrøde.get("plante_id")
            p   = opslag_plante(pid) if pid else {}
            if næste:
                næste_pid  = næste.get("plante_id")
                næste_p    = opslag_plante(næste_pid) if næste_pid else {}
                efterfølger = f"{næste_p.get('navn', næste_pid or '?')} ({MÅNEDER[næste.get('fra', 1) - 1]})"
            else:
                efterfølger = None
            result = {**p, **afgrøde}
            result.setdefault("plante", p.get("navn") or zone.get("navn") or pid or "")
            result.setdefault("sort",   p.get("sort", ""))
            # 'or'-coalescing (ikke setdefault): en eksplicit farve: null i planten
            # må ikke overleve som None — det crasher kontrast_farve i templaten.
            result["farve"] = result.get("farve") or p.get("farve") or "#c8e6c9"
            result["efterfølger"] = efterfølger
            return result

        afgrøder = zone.get("afgrøder", [])
        if not afgrøder:
            return _beret({})

        def _er_aktiv(a):
            fra, til = a.get("fra", 1), a.get("til", 12)
            return (fra <= måned <= til) if fra <= til else (måned >= fra or måned <= til)

        aktive = [(i, a) for i, a in enumerate(afgrøder) if _er_aktiv(a)]
        if aktive:
            # Sidst-starter-vinder: ved overlap foretrækkes den nyeste afgrøde.
            # Ved uafgjort (samme fra-måned) vinder den første i listen.
            best_i, best_a = aktive[0]
            for i, a in aktive[1:]:
                if a.get("fra", 1) > best_a.get("fra", 1):
                    best_i, best_a = i, a
            return _beret(best_a, afgrøder[best_i + 1] if best_i + 1 < len(afgrøder) else None)

        return _beret(afgrøder[0], afgrøder[1] if len(afgrøder) > 1 else None)

    # Filter: kalendercelleinfo for én plante og én måned
    def kalender_celle(plante, m):
        ind = plante.get("indendørs")
        upl = plante.get("udplantning")
        dir = plante.get("direkte")
        hf  = plante.get("høst_fra")
        ht  = plante.get("høst_til")
        if ind and upl and ind <= m <= upl - 1:
            return {"klasse": "indendørs",  "label": "ind."}
        if upl and m == upl:
            return {"klasse": "udplantning", "label": "↓"}
        if dir and m == dir:
            return {"klasse": "direkte",     "label": "↓"}
        if hf and ht:
            i_høst = (hf <= m <= ht) if hf <= ht else (m >= hf or m <= ht)
            if i_høst:
                return {"klasse": "høst", "label": "⚘"}
        return {"klasse": "tom", "label": ""}

    # Filter: formatér dato til dansk
    def dato_fmt(dato):
        try:
            d = str(dato)
            år, mån, dag = d.split("-")
            return f"{int(dag)}. {MÅNEDER_LANG[int(mån)-1]} {år}"
        except (ValueError, IndexError):
            return str(dato)

    # Filter: splitlines til brug i skabelon
    def splitlines(tekst):
        return str(tekst).splitlines()

    # Filter: succession-JSON til zone-popup (kun hvis flere afgrøder)
    import json as _json
    def zone_succession(zone):
        afgrøder = zone.get("afgrøder", [])
        if not afgrøder:
            return ""
        # Enkelt afgrøde uden datoer: altid aktiv, ingen navigation nødvendig
        if len(afgrøder) == 1 and not afgrøder[0].get("fra") and not afgrøder[0].get("til"):
            return ""
        måned = datetime.date.today().month
        resultat = []
        for a in afgrøder:
            pid  = a.get("plante_id")
            p    = opslag_plante(pid) if pid else {}
            fra  = a.get("fra", 1)
            til  = a.get("til", 12)
            aktiv = (fra <= måned <= til) if fra <= til else (måned >= fra or måned <= til)
            resultat.append({
                "plante":    p.get("navn") or zone.get("navn") or pid or "",
                "sort":      a.get("sort") or p.get("sort") or "",
                "farve":     p.get("farve") or "#c8e6c9",
                "fra":       fra,
                "til":       til,
                "fra_navn":  MÅNEDER[fra - 1],
                "til_navn":  MÅNEDER[til - 1],
                "aktiv":     aktiv,
            })
        return _json.dumps(resultat, ensure_ascii=False)

    import markdown as _md
    _md_exts = ["fenced_code"]
    import urllib.parse as _urlparse
    env.filters["md"]               = lambda t: _md.markdown(str(t), extensions=_md_exts)
    env.filters["aktiv_afgrøde"]    = aktiv_afgrøde
    env.filters["zone_succession"]  = zone_succession
    env.filters["kalender_celle"]   = kalender_celle
    env.filters["dato_fmt"]         = dato_fmt
    env.filters["splitlines"]       = splitlines
    env.filters["kontrast_farve"]   = kontrast_farve
    env.filters["urlencode"]        = lambda s: _urlparse.quote(str(s), safe="")
    return env
