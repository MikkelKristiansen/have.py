#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
haven — Generer HTML-plan for køkkenhaven via Jinja2-skabeloner.
Læser YAML-filer og producerer HTML til webbrug og print via browser.

Brug:
  have build                         # generer HTML lokalt
  have deploy                        # byg og upload til server
"""

import sys
import os
import argparse
import argcomplete
from pathlib import Path
import subprocess
import datetime
import yaml
from jinja2 import Environment, FileSystemLoader, pass_eval_context
from pydantic import ValidationError

# ── Konfiguration ──────────────────────────────────────────────────────────────

from . import __version__
from .config import (
    load_config, data_mappe, out_mappe, sti,
    sftp_adgangskode, ftp_adgangskode, PROJECT_ROOT,
)
from .models import Plante, FotoModel
from .wikidata import (wikidata_søg, wikidata_hent_plantedata,
                       wikidata_hent_foto_url, wikidata_hent_foto_metadata)

_config = load_config()

AKTIVT_ÅR   = _config["aktivt_år"]
DATA_MAPPE  = data_mappe(_config)
OUT_MAPPE   = out_mappe(_config)
PLANTER_FIL = sti(_config, "data") / "planter.yaml"
DYR_FIL     = sti(_config, "data") / "dyr.yaml"
ALMANAK_FIL = DATA_MAPPE / "almanak.yaml"
ENTRIES_FIL = DATA_MAPPE / "entries.yaml"

YAML_FILER_DEFAULT = [
    DATA_MAPPE / f"{bed}.yaml" for bed in _config["bede"]
]

BASE_URL = _config["site"]["basis_url"]

_deploy = _config.get("deploy", {})
DEPLOY_PROTOKOL = _deploy.get("protokol", "ingen")

_sftp = _deploy.get("sftp", {})
SFTP_HOST   = _sftp.get("host", "")
SFTP_BRUGER = _sftp.get("bruger", "")
SFTP_MAPPE  = _sftp.get("mappe", "")
SFTP_KODE   = sftp_adgangskode()

_ftp = _deploy.get("ftp", {})
FTP_HOST   = _ftp.get("host", "")
FTP_BRUGER = _ftp.get("bruger", "")
FTP_MAPPE  = _ftp.get("mappe", "")
FTP_KODE   = ftp_adgangskode()

MÅNEDER      = ["Jan","Feb","Mar","Apr","Maj","Jun","Jul","Aug","Sep","Okt","Nov","Dec"]
MÅNEDER_LANG = ["januar","februar","marts","april","maj","juni",
                "juli","august","september","oktober","november","december"]

# ── Plantedatabase ─────────────────────────────────────────────────────────────

def byg_plante_db(sti: Path = PLANTER_FIL) -> dict:
    """Indlæser planter.yaml og returnerer en dict { id → plante_dict }."""
    data = load_yaml(sti)
    db = {}
    planter = data if isinstance(data, list) else data.get("planter", [])
    for plante in planter:
        if "id" in plante:
            db[plante["id"]] = plante
        else:
            print(f"[ADVARSEL] Plante uden id: {plante.get('navn', '?')}", file=sys.stderr)
    return db


PLANTE_DB: dict = {}  # Populeres i main via PLANTE_DB.update(byg_plante_db())


def opslag_plante(plante_id: str) -> dict:
    """Slår et plante_id op i PLANTE_DB. Logger advarsel ved ukendt id."""
    if plante_id not in PLANTE_DB:
        print(f"[ADVARSEL] Ukendt plante_id: {plante_id!r}", file=sys.stderr)
        return {}
    return PLANTE_DB[plante_id]


def berig_kalender_planter(plante_id_liste: list) -> list:
    """Konverterer liste af plante_id'er til berigede plante-dicts."""
    return [opslag_plante(pid) for pid in plante_id_liste if pid]


# ── Dyreregister (høns m.m.) ─────────────────────────────────────────────────────

def byg_dyr_db(sti: Path = DYR_FIL) -> dict:
    """Indlæser dyr.yaml og returnerer en dict { id → dyr_dict }.

    Samme mønster som byg_plante_db. Returnerer tom dict hvis filen mangler —
    dyreregistret er valgfrit og kun relevant for husdyr-zoner.
    """
    if not os.path.exists(sti):
        return {}
    data = load_yaml(sti)
    db = {}
    dyr = data if isinstance(data, list) else data.get("dyr", [])
    for d in dyr or []:
        if "id" in d:
            db[d["id"]] = d
        else:
            print(f"[ADVARSEL] Dyr uden id: {d.get('race', '?')}", file=sys.stderr)
    return db


DYR_DB: dict = {}  # Populeres i generer_alle via DYR_DB.update(byg_dyr_db())


def _dyr_label(d: dict) -> str:
    """Vis et dyr som 'race farve' (til lister og overskrifter)."""
    dele = [str(d.get("race", "")).strip(), str(d.get("farve", "")).strip()]
    return " ".join(p for p in dele if p) or d.get("id", "?")


# Hønse-entry-typer: ikon + dansk label. Styrer både wizard-valg og visning.
HONS_TYPER = {
    "æglægning":    {"ikon": "🥚", "label": "Æglægning"},
    "ruge-start":   {"ikon": "🐣", "label": "Rugestart"},
    "foderkøb":     {"ikon": "🌾", "label": "Foderkøb"},
    "sundhedsobs":  {"ikon": "🩺", "label": "Sundhedsobservation"},
    "dødsfald":     {"ikon": "🪦", "label": "Dødsfald"},
    "fjerfældning": {"ikon": "🪶", "label": "Fjerfældning"},
}


# ── L2: Strukturel validering af plantedatabasen ───────────────────────────────
#
# Skemaet er udledt fra templates/planter.html og have.html.
# Opdatér _FOTO_PÅKRÆVEDE_FELTER når templates ændrer sig.

_FOTO_PÅKRÆVEDE_FELTER = {"fil": str}   # underfelter der altid dereferences


def valider_planter(db: dict) -> None:
    """L2: Kontrollér at hvert plant-objekt har den form templates forventer."""
    fejl = []
    for pid, data in db.items():
        try:
            Plante(**data)
        except ValidationError as e:
            for felt in e.errors():
                loc = ".".join(str(x) for x in felt["loc"])
                fejl.append((PLANTER_FIL.name, f"{pid}.{loc}: {felt['msg']}"))
    _print_fejl_og_afslut(fejl)


# ── L3: Referentiel validering ─────────────────────────────────────────────────

def valider_referencer(db: dict, bede_yaml_filer: list) -> None:
    """L3: Kontrollér plante_id-referencer og lokale fotofiler.

    L3a — plante_id i bed-filer: bede[].zoner[].plante_id og
          bede[].zoner[].afgrøder[].plante_id og kalender_planter[].
    L3b — lokale foto-filer: p.foto.fil der ikke starter med http.

    Forudsætter at valider_planter har kørt og bestået (db er strukturelt gyldig).
    Samler alle fejl og afslutter med sys.exit(1) ved fund.
    """
    fejl: list[tuple[str, str]] = []

    # L3a: plante_id-referencer i bed-filer
    for yaml_sti in bede_yaml_filer:
        yaml_sti = Path(yaml_sti)
        if not yaml_sti.exists():
            continue
        data = load_bed_yaml(yaml_sti)
        fil = yaml_sti.name

        for bed in data.get("bede", []):
            bed_navn = bed.get("navn") or bed.get("id") or "?"
            for zone in bed.get("zoner", []):
                for kilde in zone.get("afgrøder", []):
                    pid = kilde.get("plante_id")
                    if pid and pid not in db:
                        fejl.append((fil,
                            f"bed {bed_navn!r}: refererer ukendt plante_id {pid!r}"))

        for pid in data.get("kalender_planter", []):
            if pid and pid not in db:
                fejl.append((fil,
                    f"kalender_planter: refererer ukendt plante_id {pid!r}"))

    # L3b: lokale fotofiler
    fotos_mappe = sti(_config, "fotos") / "planter"
    for pid, p in db.items():
        foto = p.get("foto")
        if not isinstance(foto, dict):
            continue
        fil_val = foto.get("fil", "")
        if not isinstance(fil_val, str) or fil_val.startswith("http"):
            continue
        if not (fotos_mappe / fil_val).exists():
            fejl.append((PLANTER_FIL.name,
                f"{pid}.foto.fil: {fil_val!r} findes ikke i fotos/planter/"))

    _print_fejl_og_afslut(fejl)


# ── Hjælpefunktioner ───────────────────────────────────────────────────────────

def _print_fejl_og_afslut(fejl: list) -> None:
    """Printer fejlliste grupperet efter filnavn og kalder sys.exit(1) ved fejl."""
    if not fejl:
        return
    fra_filer: dict = {}
    for fil, besked in fejl:
        fra_filer.setdefault(fil, []).append(besked)
    for fil, beskeder in fra_filer.items():
        print(f"❌ Fejl i {fil}:", file=sys.stderr)
        for b in beskeder:
            print(f"  • {b}", file=sys.stderr)
    sys.exit(1)


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


# ── YAML ───────────────────────────────────────────────────────────────────────

_YAML_FEJL_HINTS = [
    ("could not find expected ':'",       "Mangler kolon (:) efter en nøgle — eller er der et uventet tegn?"),
    ("mapping values are not allowed",    "En værdi med kolon (:) skal sættes i anførselstegn, f.eks. \"tekst: med kolon\""),
    ("found character '\\t'",             "Tab-tegn er ikke tilladt i YAML — brug mellemrum til indrykning"),
    ("expected '<document start>'",       "Mangler der et # foran en kommentar, eller er indrykningen forkert?"),
    ("found unexpected ':'",              "Uventet kolon — værdier med kolon skal i anførselstegn"),
    ("found unexpected end of stream",    "Filen slutter uventet — mangler der en afsluttende linje?"),
    ("could not determine a constructor", "Ukendt YAML-type — brug anførselstegn rundt om værdien"),
]

_KONTEKST_LINJER_FØR = 5
_KONTEKST_LINJER_EFTER = 2


def load_yaml(sti):
    sti = Path(sti)
    try:
        tekst = sti.read_text(encoding="utf-8")
    except OSError as e:
        print(f"❌ Kan ikke læse {sti.name}: {e}")
        sys.exit(1)

    try:
        return yaml.safe_load(tekst)
    except yaml.YAMLError as e:
        print(f"\n❌ YAML-fejl i {sti.name}")

        if hasattr(e, "problem_mark"):
            mark = e.problem_mark
            linje_nr = mark.line          # 0-baseret
            kolonne  = mark.column

            linjer = tekst.splitlines()
            fra = max(0, linje_nr - _KONTEKST_LINJER_FØR)
            til = min(len(linjer), linje_nr + _KONTEKST_LINJER_EFTER + 1)

            print()
            for i in range(fra, til):
                præfiks = "  → " if i == linje_nr else "    "
                print(f"  {præfiks}{i + 1:3} │ {linjer[i]}")
            print(f"           {' ' * kolonne}^")

            if linje_nr > 0:
                print(f"\n  ⚠️  Fejlen kan være på eller før linje {linje_nr + 1} — YAML-parseren")
                print(f"      rapporterer der hvor den opgiver, ikke nødvendigvis der hvor")
                print(f"      ændringen er foretaget.")

            problem = (e.problem or "").lower()
            hint = next((h for nøgle, h in _YAML_FEJL_HINTS if nøgle in problem), None)
            print()
            if hint:
                print(f"  💡 {hint}")
            else:
                print(f"  Fejl: {e.problem}")
        else:
            print(f"  {e}")

        print(f"\n  Se docs/skema.md for feltbeskrivelser og gyldige værdier.\n")
        sys.exit(1)


def normaliser_bed_data(data: dict) -> dict:
    """Konverterer det simple zone-format (plante_id direkte på zonen) til afgrøder-format."""
    for bed in data.get("bede", []):
        for zone in bed.get("zoner", []):
            if zone.get("plante_id") and not zone.get("afgrøder"):
                zone["afgrøder"] = [{"plante_id": zone["plante_id"]}]
    return data


def load_bed_yaml(sti) -> dict:
    return normaliser_bed_data(load_yaml(sti))


# ── Hjælpefunktioner ───────────────────────────────────────────────────────────

def skriv_hvis_ændret(sti: Path, indhold: str) -> bool:
    sti = Path(sti)
    if sti.exists() and sti.read_text(encoding="utf-8") == indhold:
        return False
    sti.write_text(indhold, encoding="utf-8")
    return True


# ── Generering ─────────────────────────────────────────────────────────────────

def generer_html(yaml_sti, html_sti, env, alle_planter, nav_context=None,
                 almanak_fil=None, entries_fil=None, data_mappe_sti=None):
    _almanak_fil  = Path(almanak_fil)  if almanak_fil  else ALMANAK_FIL
    _entries_fil  = Path(entries_fil)  if entries_fil  else ENTRIES_FIL
    _data_mappe   = Path(data_mappe_sti) if data_mappe_sti else DATA_MAPPE
    data      = load_bed_yaml(yaml_sti)
    html_navn = data["meta"].get("html_navn", yaml_sti.replace(".yaml", ""))

    # Filtrér planter til kun dem der er relevante for denne side
    relevante_ids = set()
    for bed in data.get("bede", []):
        for zone in bed.get("zoner", []):
            for kilde in zone.get("afgrøder", []):
                if kilde.get("plante_id"):
                    relevante_ids.add(kilde["plante_id"])
    for pid in data.get("kalender_planter", []):
        relevante_ids.add(pid)
    relevante_planter = sorted(
        [p for p in alle_planter if p.get("id") in relevante_ids],
        key=lambda p: p["navn"]
    )

    # Almanak — filtrér samlet almanak.yaml på dette områdes id
    almanak_måneder = []
    if os.path.exists(_almanak_fil):
        alm = load_yaml(_almanak_fil)
        for m in alm.get("måneder", []):
            mån = {
                "måned": m["måned"],
                "navn":  m["navn"],
                "indledning":   next((i["tekst"] for i in m.get("indledninger", [])
                                      if i["område_id"] == html_navn), None),
                "begivenheder": [b["tekst"] for b in m.get("begivenheder", [])
                                 if b["område_id"] == html_navn],
                "entries":      [],
            }
            almanak_måneder.append(mån)

        # Indlæs entries fra entries.yaml og fordel på måneder
        if os.path.exists(_entries_fil):
            entries_data = load_yaml(_entries_fil)
            for e in (entries_data.get("entries") or []):
                if e.get("område_id") != html_navn:
                    continue
                e_kopi = dict(e)
                if hasattr(e_kopi.get("dato"), "isoformat"):
                    e_kopi["dato"] = e_kopi["dato"].isoformat()
                # Normaliser plante_id og berig med plantenavne
                pid = e_kopi.get("plante_id")
                if pid is None:
                    e_kopi["plante_id"] = []
                elif isinstance(pid, str):
                    e_kopi["plante_id"] = [pid] if pid else []
                elif not isinstance(pid, list):
                    e_kopi["plante_id"] = list(pid)
                e_kopi["plante_navne"] = [PLANTE_DB.get(p, {}).get("navn", p)
                                          for p in e_kopi["plante_id"] if p]
                try:
                    måned_nr = int(str(e_kopi["dato"]).split("-")[1])
                    almanak_måneder[måned_nr - 1]["entries"].append(e_kopi)
                except (KeyError, IndexError, ValueError):
                    pass
        # Indlæs entries fra markdown-mappe
        entries_mappe = os.path.join(_data_mappe, "entries", "sektioner")
        for e in _les_entries_mappe(entries_mappe):
            if (e.get("zone") or e.get("område_id", "")) != html_navn:
                continue
            e_kopi = dict(e)
            if hasattr(e_kopi.get("dato"), "isoformat"):
                e_kopi["dato"] = e_kopi["dato"].isoformat()
            # Berig med plantenavne (plante_id er allerede normaliseret til liste af _les_entries_mappe)
            e_kopi["plante_navne"] = [PLANTE_DB.get(p, {}).get("navn", p)
                                      for p in e_kopi.get("plante_id", []) if p]
            try:
                måned_nr = int(str(e_kopi["dato"]).split("-")[1])
                almanak_måneder[måned_nr - 1]["entries"].append(e_kopi)
            except (KeyError, IndexError, ValueError):
                pass
        # Sortér entries ældste først (stigende dato)
        for mån in almanak_måneder:
            mån["entries"].sort(key=lambda e: str(e["dato"]))
    har_almanak = bool(almanak_måneder)

    skabelon = env.get_template("have.html")
    output = skabelon.render(
        titel           = data["meta"]["titel"],
        år              = data["meta"]["år"],
        ikon            = data["meta"].get("ikon", "🌿"),
        ikon_billede    = data["meta"].get("ikon_billede", ""),
        undertitel      = data["meta"].get("undertitel", ""),
        beskrivelse     = data["meta"].get("beskrivelse", ""),
        bede            = data.get("bede", []),
        planter         = relevante_planter,
        måneder         = MÅNEDER,
        har_almanak     = har_almanak,
        almanak_måneder = almanak_måneder,
        aktuel_måned    = datetime.date.today().month,
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(html_sti, output):
        print(f"✅ HTML genereret: {html_sti}")
    else:
        print(f"ℹ️  HTML uændret: {html_sti}")



def _les_hons_entries(mappe) -> list:
    """Læs hønse-entries (én YAML-fil pr. entry) fra entries/{zone}/-mappen."""
    entries = []
    if not os.path.isdir(mappe):
        return entries
    for fil in sorted(os.listdir(mappe)):
        if not (fil.endswith(".yaml") or fil.endswith(".yml")):
            continue
        e = load_yaml(os.path.join(mappe, fil))
        if not isinstance(e, dict):
            continue
        e = dict(e)
        for nøgle in ("dato", "forventet_klæk"):
            if hasattr(e.get(nøgle), "isoformat"):
                e[nøgle] = e[nøgle].isoformat()
        e["_fil"] = Path(fil).stem
        entries.append(e)
    return entries


def _hons_resume(e: dict) -> str:
    """Byg en kort, menneskelæselig opsummering af en hønse-entry til loggen."""
    t = e.get("type", "")
    dele: list = []
    if t == "æglægning":
        return f"{e.get('æg', 0)} æg"
    if t == "ruge-start":
        if e.get("høne_label"):
            dele.append(e["høne_label"])
        if e.get("æg_antal") is not None:
            dele.append(f"{e['æg_antal']} æg lagt til rugning")
        if e.get("forventet_klæk"):
            dele.append(f"forventet klæk {e['forventet_klæk']}")
    elif t == "foderkøb":
        if e.get("foder_type"):
            dele.append(str(e["foder_type"]))
        if e.get("mængde_kg") is not None:
            dele.append(f"{e['mængde_kg']} kg")
        if e.get("pris") is not None:
            dele.append(f"{e['pris']} kr")
        if e.get("butik"):
            dele.append(str(e["butik"]))
    elif t == "sundhedsobs":
        if e.get("høne_label"):
            dele.append(e["høne_label"])
        else:
            dele.append("hele flokken")
        if e.get("observation"):
            dele.append(str(e["observation"]))
        if e.get("handling"):
            dele.append(f"→ {e['handling']}")
    elif t == "dødsfald":
        if e.get("høne_label"):
            dele.append(e["høne_label"])
        if e.get("årsag"):
            dele.append(f"årsag: {e['årsag']}")
    elif t == "fjerfældning":
        fase = e.get("fase", "")
        return f"fældning ({fase})" if fase else "fældning"
    return " · ".join(dele)


def _berig_hons_entry(e: dict) -> dict:
    """Berig en entry med ikon, type-label, opslået høne-navn og resumé."""
    e = dict(e)
    t = e.get("type", "")
    cfg = HONS_TYPER.get(t, {"ikon": "📝", "label": t or "Note"})
    e["ikon"] = cfg["ikon"]
    e["type_label"] = cfg["label"]
    hid = e.get("høne")
    e["høne_label"] = _dyr_label(DYR_DB[hid]) if hid in DYR_DB else (hid or "")
    e["resume"] = _hons_resume(e)
    return e


def generer_hons_html(yaml_sti, html_sti, env, nav_context=None, data_mappe_sti=None):
    """Generer en husdyr-zoneside (hønsehus): register + observationslog.

    Returnerer de berigede entries, så kalderen kan genbruge dem til ICS-generering.
    """
    _data_mappe = Path(data_mappe_sti) if data_mappe_sti else DATA_MAPPE
    data = load_yaml(yaml_sti)
    meta = data.get("meta", {})
    html_navn = meta.get("html_navn", Path(yaml_sti).stem)
    # zone-typer: 'husdyr' aktiverer alternativ template og wizard-sæt.
    # Zoner uden 'type' behandles som plantezoner (eksisterende opførsel).
    zone_type = meta.get("type", "plante")

    # Høne-register: aktive først, derefter race/farve
    dyr = sorted(
        DYR_DB.values(),
        key=lambda d: (not d.get("aktiv", True), str(d.get("race", "")), str(d.get("farve", ""))),
    )

    # Observationslog: nyeste øverst
    entries_mappe = os.path.join(_data_mappe, "entries", html_navn)
    entries = [_berig_hons_entry(e) for e in _les_hons_entries(entries_mappe)]
    entries.sort(key=lambda e: str(e.get("dato", "")), reverse=True)

    har_ics = any(e.get("type") == "ruge-start" and e.get("forventet_klæk") for e in entries)

    skabelon = env.get_template("hons.html")
    output = skabelon.render(
        titel        = meta.get("titel", "Hønsehuset"),
        år           = meta.get("år", AKTIVT_ÅR),
        ikon         = meta.get("ikon", "🐔"),
        ikon_billede = meta.get("ikon_billede", ""),
        undertitel   = meta.get("undertitel", ""),
        beskrivelse  = meta.get("beskrivelse", ""),
        zone_type    = zone_type,
        dyr          = dyr,
        entries      = entries,
        har_ics      = har_ics,
        ics_fil      = f"{html_navn}-{AKTIVT_ÅR}.ics",
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(html_sti, output):
        print(f"✅ HTML genereret: {html_sti}")
    else:
        print(f"ℹ️  HTML uændret: {html_sti}")
    return entries


def generer_hons_ics(entries, ics_sti, år) -> bool:
    """Generer en ICS-kalender med forventede klækninger fra ruge-start-entries.

    Returnerer True hvis filen blev skrevet (mindst én klække-event), ellers False.
    """
    def ics_escape(s):
        s = str(s).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
        s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "")
        return s.strip()

    def ics_fold(line):
        chunks = []
        while True:
            if len(line.encode("utf-8")) <= 75:
                chunks.append(line)
                break
            n = 75
            while len(line[:n].encode("utf-8")) > 75:
                n -= 1
            chunks.append(line[:n])
            line = " " + line[n:]
        return "\r\n".join(chunks)

    now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    vevents = []
    for e in entries:
        if e.get("type") != "ruge-start" or not e.get("forventet_klæk"):
            continue
        try:
            d = datetime.date.fromisoformat(str(e["forventet_klæk"]))
        except ValueError:
            continue
        dato_start = d.strftime("%Y%m%d")
        dato_end   = (d + datetime.timedelta(days=1)).strftime("%Y%m%d")
        høne = e.get("høne_label") or _dyr_label(DYR_DB.get(e.get("høne"), {})) or "?"
        antal = e.get("æg_antal", "?")
        lagt = e.get("dato", "")
        description = ics_escape(f"{høne} — {antal} æg lagt {lagt}")
        uid = f"hons-klaek-{dato_start}-{e.get('_fil', '')}@have.py"
        vevents.append("\r\n".join([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_ts}",
            f"DTSTART;VALUE=DATE:{dato_start}",
            f"DTEND;VALUE=DATE:{dato_end}",
            ics_fold(f"SUMMARY:{ics_escape('🐣 Forventet klækning')}"),
            ics_fold(f"DESCRIPTION:{description}"),
            "END:VEVENT",
        ]))

    if not vevents:
        return False

    header = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//have.py//Hønsekalender//DA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Hønsehuset {år}",
    ])
    indhold = header + "\r\n" + "\r\n".join(vevents) + "\r\nEND:VCALENDAR\r\n"
    with open(ics_sti, "w", encoding="utf-8", newline="") as f:
        f.write(indhold)
    print(f"✅ Høns-ICS genereret: {ics_sti} ({len(vevents)} klækninger)")
    return True


def flet_almanakker(projekter_data, entries_fil=None):
    """
    Fletter måneder fra alle almanakfiler.
    Returnerer liste af 12 måneder med blandede entries og begivenheder.
    """
    _entries_fil = Path(entries_fil) if entries_fil else ENTRIES_FIL
    MÅNED_NAVNE = ["Januar","Februar","Marts","April","Maj","Juni",
                   "Juli","August","September","Oktober","November","December"]

    # Byg 12 tomme måneder
    måneder = [{"måned": i+1, "navn": MÅNED_NAVNE[i],
                "indledninger": [], "begivenheder": [], "entries": []}
               for i in range(12)]

    for html_navn, alm_data in projekter_data:
        # Kilde-css-klasse baseret på html_navn
        css_kilde = f"kilde-{html_navn.replace('_','-')}"
        titel = {"hoejbede": "Højbedshaven",
                 "krydderurter": "Krydderurterne",
                 "frugthaven": "Frugthaven", "drivhus": "Drivhuset"}.get(html_navn, html_navn)

        for mån in alm_data.get("måneder", []):
            idx = mån["måned"] - 1

            # Indledninger filtreret på dette område
            for ind in (mån.get("indledninger") or []):
                if ind.get("område_id") == html_navn:
                    måneder[idx]["indledninger"].append((titel, ind["tekst"]))

            # Begivenheder filtreret på dette område
            for b in (mån.get("begivenheder") or []):
                if b.get("område_id") == html_navn:
                    måneder[idx]["begivenheder"].append({
                        "tekst": b["tekst"],
                        "kilde": titel,
                        "css":   css_kilde,
                    })

            # Entries filtreret på dette område
            # Entries hentes fra entries.yaml

    # Byg opslagsdict: html_navn -> titel
    # Indlæs fra meta.html_navn i bed-YAML'erne — filnavnet matcher ikke nødvendigvis html_navn
    # (fx har højbedshaven.yaml html_navn="hoejbede")
    område_titler: dict[str, str] = {}
    for yaml_sti in YAML_FILER_DEFAULT:
        if os.path.exists(yaml_sti):
            meta = load_yaml(yaml_sti).get("meta", {})
            hn = meta.get("html_navn")
            if hn:
                område_titler[hn] = meta.get("titel", hn)

    # Indlæs entries fra entries.yaml og fordel på måneder og område
    if os.path.exists(_entries_fil):
        entries_data = load_yaml(_entries_fil)
        for e in (entries_data.get("entries") or []):
            oid = e.get("område_id", "")
            if hasattr(e.get("dato"), "isoformat"):
                e["dato"] = e["dato"].isoformat()
            try:
                måned_nr = int(str(e["dato"]).split("-")[1])
            except (KeyError, IndexError, ValueError):
                continue
            e_kopi = dict(e)
            e_kopi["kilde"]     = område_titler.get(oid, oid)
            e_kopi["css_kilde"] = f"kilde-{oid.replace('_','-')}"
            # Normaliser plante_id og berig med plantenavne
            pid = e_kopi.get("plante_id")
            if pid is None:
                e_kopi["plante_id"] = []
            elif isinstance(pid, str):
                e_kopi["plante_id"] = [pid] if pid else []
            else:
                e_kopi["plante_id"] = list(pid)
            e_kopi["plante_navne"] = [PLANTE_DB.get(p, {}).get("navn", p)
                                      for p in e_kopi["plante_id"] if p]
            måneder[måned_nr - 1]["entries"].append(e_kopi)

    # Indlæs entries fra markdown-mappe
    entries_mappe_md = Path(_entries_fil).parent / "entries" / "sektioner"
    for e in _les_entries_mappe(str(entries_mappe_md)):
        oid = e.get("zone") or e.get("område_id", "")
        if hasattr(e.get("dato"), "isoformat"):
            e["dato"] = e["dato"].isoformat()
        try:
            måned_nr = int(str(e["dato"]).split("-")[1])
        except (KeyError, IndexError, ValueError):
            continue
        e_kopi = dict(e)
        e_kopi.setdefault("titel", "")
        e_kopi["kilde"]     = område_titler.get(oid, oid)
        e_kopi["css_kilde"] = f"kilde-{oid.replace('_','-')}"
        # plante_id er allerede normaliseret til liste af _les_entries_mappe
        e_kopi["plante_navne"] = [PLANTE_DB.get(p, {}).get("navn", p)
                                  for p in e_kopi.get("plante_id", []) if p]
        måneder[måned_nr - 1]["entries"].append(e_kopi)

    # Sortér entries inden for hver måned (stigende dato)
    for mån in måneder:
        mån["entries"].sort(key=lambda e: str(e["dato"]))

    return måneder


def generer_måned_svg(måned_data: dict) -> "dict | None":
    """Generer tre SVG-grafer for én måneds daglige vejrdata."""
    daglige = måned_data.get("daglige") if måned_data else None
    if not daglige:
        return None

    d_middel = list(daglige.get("middel") or [])
    d_min    = list(daglige.get("min")    or [])
    d_ned    = list(daglige.get("nedbør") or [])
    n = len(d_middel)
    if not n:
        return None

    W, H   = 400, 80
    ML, MR = 28, 4
    PT, PB = 6, 14
    DW = W - ML - MR
    DH = H - PT - PB
    col = DW / n

    def xd(i):
        return round(ML + (i + 0.5) * col, 2)

    dag_lbl_idx = sorted({0, 4, 9, 14, 19, 24, n - 1})

    def lbl_y(x, y, txt):
        return (f'<text x="{x}" y="{y}" font-size="6.5" fill="#aaa" '
                f'text-anchor="end" font-family="sans-serif">{txt}</text>')

    def lbl_x(x, y, txt):
        return (f'<text x="{x}" y="{y}" font-size="6.5" fill="#ccc" '
                f'text-anchor="middle" font-family="sans-serif">{txt}</text>')

    def hgrid(y, stroke, da=None):
        d = f' stroke-dasharray="{da}"' if da else ""
        return (f'<line x1="{ML}" y1="{y}" x2="{W - MR}" y2="{y}" '
                f'stroke="{stroke}" stroke-width="0.5"{d}/>')

    # ── Temperaturlinje (deles af middel og min) ──────────────────────────────
    T_MIN, T_MAX = -15, 30

    def yt(t):
        return round(PT + (T_MAX - t) / (T_MAX - T_MIN) * DH, 2)

    def temp_svg(vals, c_pos, c_neg):
        els = []
        for gv, stroke, da in [
            (-5, "#e8e8e8", "2,3"), (0, "#bbb", "3,2"),
            (5, "#e8e8e8", "2,3"),  (10, "#e8e8e8", "2,3"),
            (15, "#e8e8e8", "2,3"), (20, "#e8e8e8", "2,3"),
        ]:
            yg = yt(gv)
            els.append(hgrid(yg, stroke, da))
            els.append(lbl_y(ML - 2, round(yg + 2.5, 2), f"{gv}°"))
        for i in dag_lbl_idx:
            if i < n:
                els.append(lbl_x(xd(i), H - 2, str(i + 1)))
        y0 = yt(0)
        for i in range(n - 1):
            v1, v2 = vals[i], vals[i + 1]
            if v1 is None or v2 is None:
                continue
            x1, x2 = xd(i), xd(i + 1)
            y1, y2 = yt(v1), yt(v2)
            if (v1 >= 0) == (v2 >= 0):
                c = c_pos if v1 >= 0 else c_neg
                els.append(
                    f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                    f'stroke="{c}" stroke-width="1.0" stroke-linecap="round"/>'
                )
            else:
                ratio = v1 / (v1 - v2)
                xc = round(x1 + ratio * (x2 - x1), 2)
                c1, c2 = (c_pos, c_neg) if v1 >= 0 else (c_neg, c_pos)
                els.append(
                    f'<line x1="{x1}" y1="{y1}" x2="{xc}" y2="{y0}" '
                    f'stroke="{c1}" stroke-width="1.0" stroke-linecap="round"/>'
                    f'<line x1="{xc}" y1="{y0}" x2="{x2}" y2="{y2}" '
                    f'stroke="{c2}" stroke-width="1.0" stroke-linecap="round"/>'
                )
        return (
            f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
            + "".join(els) + "</svg>"
        )

    # ── Nedbør ────────────────────────────────────────────────────────────────
    N_MAX  = 20
    y_bot  = PT + DH
    bw     = max(round(col * 0.72, 2), 0.8)

    def yn(v):
        return round(PT + (N_MAX - min(v, N_MAX)) / N_MAX * DH, 2)

    ned_els = []
    for gv in [5, 10]:
        yg = yn(gv)
        ned_els.append(hgrid(yg, "#e8e8e8", "2,3"))
        ned_els.append(lbl_y(ML - 2, round(yg + 2.5, 2), str(gv)))
    ned_els.append(lbl_y(ML - 2, y_bot, "0"))
    ned_els.append(hgrid(y_bot, "#ddd"))
    for i in dag_lbl_idx:
        if i < len(d_ned):
            ned_els.append(lbl_x(xd(i), H - 2, str(i + 1)))
    for i, nv in enumerate(d_ned):
        if not nv or nv <= 0:
            continue
        bh = round(min(nv, N_MAX) / N_MAX * DH, 2)
        bx = round(xd(i) - bw / 2, 2)
        ned_els.append(
            f'<rect x="{bx}" y="{round(y_bot - bh, 2)}" '
            f'width="{bw}" height="{bh}" fill="#90aec9" rx="0.5"/>'
        )

    ned_svg = (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        + "".join(ned_els) + "</svg>"
    )

    return {
        "temperatur_linje": temp_svg(d_middel, "#4a7c59", "#5b8dd9"),
        "min_linje":        temp_svg(d_min,    "#7aadce", "#1e3a8a"),
        "nedbør_søjler":    ned_svg,
    }


def generer_samlet_almanak(projekter_yaml, almanak_sti, env, alle_planter=None, nav_context=None,
                           almanak_fil=None, entries_fil=None, år=None):
    """Generer én samlet almanakside fra alle projekters almanakfiler."""
    _almanak_fil = Path(almanak_fil) if almanak_fil else ALMANAK_FIL
    if alle_planter is None:
        pd = load_yaml(PLANTER_FIL)
        alle_planter = pd if isinstance(pd, list) else pd.get("planter", [])
    # Indlæs samlet almanak.yaml og opdel per område
    yaml_filer = projekter_yaml
    år_fra_yaml = None
    projekter_data = []
    temperatur_dict = {}
    if os.path.exists(_almanak_fil):
        alm = load_yaml(_almanak_fil)
        år_fra_yaml = alm.get("meta", {}).get("år")
        temperatur_dict = alm.get("temperatur", {})
        # Find alle unikke område_id'er i filen
        område_ids = set()
        for m in alm.get("måneder", []):
            for ind in m.get("indledninger", []):
                område_ids.add(ind["område_id"])
            for b in m.get("begivenheder", []):
                område_ids.add(b["område_id"])
            for e in (m.get("entries") or []):
                område_ids.add(e.get("område_id",""))
        projekter_data = [(oid, alm) for oid in sorted(område_ids) if oid]

    if not projekter_data:
        return

    år = år_fra_yaml or år or AKTIVT_ÅR
    måneder  = flet_almanakker(projekter_data, entries_fil=entries_fil)
    for mån in måneder:
        mån["vejr"] = generer_måned_svg(temperatur_dict.get(MÅNEDER_LANG[mån["måned"] - 1], {}))
    # Alle planter sorteret alfabetisk til samlet kalender
    alle_planter_sorteret = sorted(alle_planter, key=lambda p: p["navn"])

    # Byg opslagsdict: titel → ikon fra bed-YAML meta-blokke (ikke hårdkodet)
    område_ikoner = {}
    for yaml_sti in yaml_filer:
        if os.path.exists(yaml_sti):
            meta  = load_yaml(yaml_sti).get("meta", {})
            titel = meta.get("titel", "")
            ikon  = meta.get("ikon", "🌿")
            if titel:
                område_ikoner[titel] = ikon
    env.filters["område_ikon"] = lambda kilde: område_ikoner.get(kilde, "🌿")

    skabelon = env.get_template("almanak.html")
    output   = skabelon.render(år=år, måneder=måneder,
                               alle_planter=alle_planter_sorteret,
                               måneds_navne=MÅNEDER,
                               aktuel_måned=datetime.date.today().month,
                               **(nav_context or {}))

    if skriv_hvis_ændret(almanak_sti, output):
        print(f"✅ Samlet almanak genereret: {almanak_sti}")
    else:
        print(f"ℹ️  Samlet almanak uændret: {almanak_sti}")


def generer_info_side(yaml_sti, html_sti, env, nav_context=None):
    """Generer en simpel info-side (om.html, kontakt.html) fra YAML."""
    data = load_yaml(yaml_sti)
    år   = datetime.date.today().year
    skabelon = env.get_template("info.html")
    output = skabelon.render(
        titel   = data.get("titel", ""),
        år      = år,
        indhold = data.get("indhold", []),
        kontakt = data.get("kontakt", []),
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(html_sti, output):
        print(f"✅ Info-side genereret: {html_sti}")
    else:
        print(f"ℹ️  Info-side uændret: {html_sti}")


def generer_index(projekter, index_sti, env, nav_context=None, hero_billede="", år=None):
    skabelon = env.get_template("index.html")
    output = skabelon.render(projekter=projekter, år=år if år is not None else AKTIVT_ÅR, hero_billede=hero_billede, **(nav_context or {}))
    if skriv_hvis_ændret(index_sti, output):
        print(f"✅ Index genereret: {index_sti}")
    else:
        print(f"ℹ️  Index uændret: {index_sti}")


def generer_planter_oversigt(alle_planter, yaml_filer, planter_sti, env, nav_context=None):
    """Generer planter.html — grupperingen og ikoner afledes fra meta i bed-YAML'erne."""
    id_til_gruppe: dict = {}
    gruppe_rækkefølge: list = []
    gruppe_ikoner: dict = {}
    gruppe_url: dict = {}

    for yaml_sti in yaml_filer:
        if not os.path.exists(yaml_sti):
            continue
        data  = load_bed_yaml(yaml_sti)
        meta  = data.get("meta", {})
        titel = meta.get("titel", yaml_sti)
        ikon  = meta.get("ikon", "🌿")
        html_navn = meta.get("html_navn", "")
        if titel not in gruppe_rækkefølge:
            gruppe_rækkefølge.append(titel)
            gruppe_ikoner[titel] = ikon
            if html_navn:
                gruppe_url[titel] = f"{html_navn}.html"
        for bed in data.get("bede", []):
            for zone in bed.get("zoner", []):
                for kilde in zone.get("afgrøder", []):
                    pid = kilde.get("plante_id")
                    if pid and pid not in id_til_gruppe:
                        id_til_gruppe[pid] = titel
        for pid in data.get("kalender_planter", []):
            if pid not in id_til_gruppe:
                id_til_gruppe[pid] = titel

    IKKE_I_HAVEN = "Ikke i haven"
    gruppe_rækkefølge.append(IKKE_I_HAVEN)
    grupper_dict: dict = {g: [] for g in gruppe_rækkefølge}
    for p in alle_planter:
        g = id_til_gruppe.get(p.get("id"), IKKE_I_HAVEN)
        grupper_dict[g].append(p)
    for planter in grupper_dict.values():
        planter.sort(key=lambda p: (p.get("navn", ""), p.get("sort", "")))
    grupper = [
        {"navn": g, "ikon": gruppe_ikoner.get(g, "🌿"), "url": gruppe_url.get(g, ""), "planter": grupper_dict[g]}
        for g in gruppe_rækkefølge if grupper_dict.get(g)
    ]
    skabelon = env.get_template("planter.html")
    output = skabelon.render(
        år=datetime.date.today().year, grupper=grupper,
        måneder=MÅNEDER, måneder_lang=MÅNEDER_LANG,
        antal_planter=len(alle_planter),
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(planter_sti, output):
        print(f"✅ Planterside genereret: {planter_sti}")
    else:
        print(f"ℹ️  Planterside uændret: {planter_sti}")


def generer_samlet_arkiv(år_liste, arkiv_samlet_sti, env, plante_db=None, nav_context=None):
    """Generer arkiv-samlet.html — alle bede med planter på tværs af alle år."""
    data_rod = PROJECT_ROOT / "data"
    plante_db = plante_db or {}

    # Aggreger: {html_navn: {titel, ikon, bede: {bed_id: {navn, år: {år: [planter]}}}}}
    områder: dict = {}

    for år in sorted(år_liste):
        år_mappe = data_rod / str(år)
        if not år_mappe.is_dir():
            continue
        for yaml_fil in sorted(år_mappe.glob("*.yaml")):
            if yaml_fil.name.startswith("."):
                continue
            if yaml_fil.name in ("almanak.yaml", "entries.yaml", "planter.yaml"):
                continue
            data = load_bed_yaml(str(yaml_fil))
            meta = data.get("meta", {})
            html_navn = meta.get("html_navn")
            if not html_navn:
                continue
            titel = meta.get("titel", html_navn)
            ikon = meta.get("ikon", "🌿")

            if html_navn not in områder:
                områder[html_navn] = {"titel": titel, "ikon": ikon, "bede": {}}

            for bed in data.get("bede", []):
                bed_id = bed.get("id", "")
                bed_navn = bed.get("navn", bed_id)

                if bed_id not in områder[html_navn]["bede"]:
                    områder[html_navn]["bede"][bed_id] = {"navn": bed_navn, "år": {}}

                seen: set = set()
                planter_i_år: list = []
                for zone in bed.get("zoner", []):
                    for afgrøde in zone.get("afgrøder", []):
                        plante_id = afgrøde.get("plante_id", "")
                        plante = plante_db.get(plante_id, {})
                        navn = plante.get("navn", plante_id)
                        sort = afgrøde.get("sort") or plante.get("sort", "")
                        key = (navn, sort)
                        if key not in seen:
                            seen.add(key)
                            planter_i_år.append({"navn": navn, "sort": sort})

                if planter_i_år:
                    områder[html_navn]["bede"][bed_id]["år"][år] = planter_i_år

    områder = {
        navn: område
        for navn, område in områder.items()
        if any(bed["år"] for bed in område["bede"].values())
    }

    skabelon = env.get_template("arkiv_samlet.html")
    output = skabelon.render(
        titel="Samlet arkiv",
        år=datetime.date.today().year,
        områder=områder,
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(str(arkiv_samlet_sti), output):
        print(f"✅ Samlet arkiv genereret: {arkiv_samlet_sti}")
    else:
        print(f"ℹ️  Samlet arkiv uændret: {arkiv_samlet_sti}")


INIT_YAML = """# Højbedshaven {år}
# Rediger denne fil for at opdatere din plan.

meta:
  år: {år}
  titel: "Højbedshaven"
  html_navn: "hoejbede"

bede:
  - id: bed-1
    navn: "Bed 1"
    bredde_cm: 240
    dybde_cm: 80
    farve: "#d4edda"
    zoner:
      - navn: "Tomater"
        bredde: 0.5
        plante: "Cherrytomater"
        sort: "Sungold"
        farve: "#ff8c69"
      - navn: "Salat"
        bredde: 0.5
        plante: "Salat"
        sort: "Lollo Rossa"
        farve: "#aed581"

planter:
  - navn: "Cherrytomater"
    sort: "Sungold"
    indendørs: 3
    udplantning: 6
    høst_fra: 7
    høst_til: 10
    noter: "Skal ikke fryse. Kræver støtte."
  - navn: "Salat"
    sort: "Lollo Rossa"
    direkte: 4
    høst_fra: 5
    høst_til: 9
    noter: "Sås løbende hver 3. uge."
"""

INIT_ALMANAK = """# Havealmanak {år}
# Kopieret fra almanak-skabelon.yaml — tilpas til din have.

måneder:
  - måned: 1
    navn: "Januar"
    indledning: "Havens hvilemåned. Planlæg sæsonen."
    begivenheder:
      - Bestil frø og løg
    entries: []

  - måned: 2
    navn: "Februar"
    indledning: "Første forspiring indendørs."
    begivenheder:
      - Forspir peberfrugter og chili
    entries: []

  - måned: 3
    navn: "Marts"
    indledning: "Forspiring skyder fart."
    begivenheder:
      - Forspir tomater og squash
      - Direkte såning af spinat og radiser
    entries: []

  - måned: 4
    navn: "April"
    indledning: "Travleste forspiremåned."
    begivenheder:
      - Læg kartofler
      - Direkte såning af gulerødder
    entries: []

  - måned: 5
    navn: "Maj"
    indledning: "Nat-frosten er næsten ovre."
    begivenheder:
      - Hærd forspirede planter af
      - Sæt bønner direkte
    entries: []

  - måned: 6
    navn: "Juni"
    indledning: "Udplantning af de varmekrævende."
    begivenheder:
      - Udplant tomater og basilikum
    entries: []

  - måned: 7
    navn: "Juli"
    indledning: "Høstsæsonen åbner."
    begivenheder:
      - Høst gulerødder og bønner løbende
    entries: []

  - måned: 8
    navn: "August"
    indledning: "Fuld høstsæson."
    begivenheder:
      - Høst tomater kontinuerligt
    entries: []

  - måned: 9
    navn: "September"
    indledning: "Efterårshøst og oprydning."
    begivenheder:
      - Høst og opbevar løg
    entries: []

  - måned: 10
    navn: "Oktober"
    indledning: "Frosten kommer. Grønkål smager bedst nu."
    begivenheder:
      - Høst grønkål efter frost
    entries: []

  - måned: 11
    navn: "November"
    indledning: "Haven lukker ned."
    begivenheder:
      - Afsluttende oprydning
    entries: []

  - måned: 12
    navn: "December"
    indledning: "Hvil og planlægning til næste sæson."
    begivenheder:
      - Gennemgå årets noter
    entries: []
"""

_OM_YAML = """\
titel: "Om siden"
html_navn: "om"

indhold:
  - tekst: >
      Velkommen til {have_titel}. Her dokumenterer jeg sæsonen {år} med bedoversigter,
      sådatokalendere og en løbende almanak.
  - tekst: >
      Siden genereres automatisk fra YAML-filer via have.py.
      Rediger filerne i data/ for at tilpasse den til din have.
"""

_KONTAKT_YAML = """\
titel: "Kontakt"
html_navn: "kontakt"

indhold:
  - tekst: >
      Har du spørgsmål eller kommentarer til haven, er du velkommen til at tage kontakt.

kontakt:
  - label: "E-mail"
    værdi: "din@email.dk"
    link: "mailto:din@email.dk"
"""

_PLANTER_YAML = """\
# Plantedatabase {år}
# Tilføj dine planter her. Hvert element refereres fra bede-filer via id-feltet.
# Kalenderfelter er månedsnumre (1-12). Udelad dem der ikke er relevante.

meta:
  titel: "Planteregister"
  html_navn: "planter"
  undertitel: "Alle sorter med kalender og noter"
  beskrivelse: ""
  ikon: "🌿"
  tags: []

planter:
- id: tomat-eksempel
  navn: Tomater
  sort: Money Maker
  farve: "#e53935"
  placering: Sol
  indendørs: 3
  udplantning: 5
  høst_fra: 7
  høst_til: 10
  noter: Udplantes efter frostrisikoens ophør.
  foto:
    fil: placeholder.jpg
- id: agurk-eksempel
  navn: Agurker
  sort: Marketmore
  farve: "#8bc34a"
  placering: Sol
  indendørs: 4
  udplantning: 5
  høst_fra: 7
  høst_til: 9
  noter: Kræver varme og jævn vanding.
  foto:
    fil: placeholder.jpg
- id: salat-eksempel
  navn: Salat
  sort: Lollo Rossa
  farve: "#4a7c59"
  placering: Sol/halvskygge
  direkte: 4
  høst_fra: 5
  høst_til: 9
  noter: Sås løbende hver 3. uge.
  foto:
    fil: placeholder.jpg
- id: gulerod-eksempel
  navn: Gulerødder
  sort: Nantes
  farve: "#ff6f00"
  placering: Sol
  direkte: 4
  høst_fra: 7
  høst_til: 10
  noter: Tyndes til 5 cm afstand.
  foto:
    fil: placeholder.jpg
- id: basilikum-eksempel
  navn: Basilikum
  sort: Genovese
  farve: "#2d5a27"
  placering: Sol
  indendørs: 4
  udplantning: 5
  høst_fra: 6
  høst_til: 9
  noter: Knibes for at undgå blomstring.
  foto:
    fil: placeholder.jpg
- id: persille-eksempel
  navn: Persille
  sort: Gigante d'Italia
  farve: "#374720"
  placering: Sol/halvskygge
  direkte: 4
  høst_fra: 6
  høst_til: 10
  noter: Langsom spiring — hold fugtig.
  foto:
    fil: placeholder.jpg
- id: jordbær-eksempel
  navn: Jordbær
  sort: Elsanta
  farve: "#e53935"
  placering: Sol
  høst_fra: 6
  høst_til: 8
  noter: Fjern udløbere løbende.
  foto:
    fil: placeholder.jpg
- id: hindbær-eksempel
  navn: Hindbær
  sort: Autumn Bliss
  farve: "#c2185b"
  placering: Sol/halvskygge
  høst_fra: 8
  høst_til: 10
  noter: Skæres ned efter høst.
  foto:
    fil: placeholder.jpg
"""


def check(yaml_filer, strict=False, farver=False):
    """Validér hele projektet — kritiske fejl og advarsler med præcise handlingsanvisninger."""
    fejl = 0
    advarsler = 0

    def E(tekst):
        nonlocal fejl
        print(f"  ❌ {tekst}")
        fejl += 1

    def W(tekst):
        nonlocal advarsler, fejl
        if strict:
            print(f"  ❌ {tekst}  [strict]")
            fejl += 1
        else:
            print(f"  ⚠️  {tekst}")
        advarsler += 1

    def OK(tekst):
        print(f"  ✅ {tekst}")

    # ── 0. Pre-flight ──────────────────────────────────────────────────────────
    print(f"\n🔍 0. Pre-flight\n")

    if not os.path.isdir(DATA_MAPPE):
        E(f"{DATA_MAPPE}/ eksisterer ikke — "
          f"kør: have nyt-år {AKTIVT_ÅR}")
    else:
        OK(f"{DATA_MAPPE}/ fundet")

    if not os.path.isfile(PLANTER_FIL):
        E(f"{PLANTER_FIL} mangler — opret filen eller kør: have init")
    else:
        OK(f"{PLANTER_FIL} fundet")

    PÅKRÆVEDE_SKABELONER = ["base.html", "have.html", "index.html",
                             "almanak.html", "planter.html"]
    if os.path.isdir("templates"):
        mangler_tmpl = [t for t in PÅKRÆVEDE_SKABELONER
                        if not os.path.isfile(os.path.join("templates", t))]
        if mangler_tmpl:
            for t in mangler_tmpl:
                E(f"templates/{t} mangler — er templates/-mappen ufuldstændig?")
        else:
            OK(f"templates/ komplet ({len(PÅKRÆVEDE_SKABELONER)} filer)")
    else:
        OK("templates/ bruger pakkedata (ingen lokal tilpasning)")

    fotos_entries = os.path.join("fotos", "entries", str(AKTIVT_ÅR))
    if not os.path.isdir(fotos_entries):
        W(f"{fotos_entries}/ mangler — "
          f"opret mappen eller kør: have nyt-år {AKTIVT_ÅR}")
    else:
        OK(f"{fotos_entries}/ fundet")

    if fejl:
        print(f"\n{'─'*40}")
        print(f"❌ {fejl} kritiske fejl — ret dem før du fortsætter.\n")
        return

    # ── 1. planter.yaml ────────────────────────────────────────────────────────
    print(f"\n🔍 1. planter.yaml\n")

    planter_data = load_yaml(PLANTER_FIL)
    alle_planter = planter_data if isinstance(planter_data, list) \
                   else planter_data.get("planter", [])

    # Unikke id'er
    ids = [p.get("id") for p in alle_planter]
    duplikater = {pid for pid in ids if pid and ids.count(pid) > 1}
    ingen_id   = [p for p in alle_planter if not p.get("id")]
    for p in ingen_id:
        E(f"Plante uden id: '{p.get('navn','?')}' — tilføj et unikt id-felt")
    for pid in sorted(duplikater):
        linjer = [i+1 for i, p in enumerate(alle_planter) if p.get("id") == pid]
        E(f"Duplikat id '{pid}' på positionerne {linjer} i {PLANTER_FIL} — "
          f"id'er skal være unikke")
    if not ingen_id and not duplikater:
        OK(f"{len(alle_planter)} planter — id'er unikke")

    # Påkrævede felter
    for p in alle_planter:
        if not p.get("navn"):
            E(f"id='{p.get('id','?')}': mangler navn-felt — tilføj navn til planten")

    # Anbefalede felter
    mangler_latin = [p for p in alle_planter if not p.get("latin")]
    if mangler_latin:
        W(f"{len(mangler_latin)} planter mangler latin-felt "
          f"({', '.join(p.get('id','?') for p in mangler_latin[:5])}"
          f"{'…' if len(mangler_latin) > 5 else ''}) — "
          f"have hent-fotos kan ikke søge dem")
    else:
        OK(f"Alle {len(alle_planter)} planter har latin-felt")

    mangler_farve = [p for p in alle_planter if not p.get("farve")]
    if mangler_farve:
        W(f"{len(mangler_farve)} planter mangler farve-felt "
          f"({', '.join(p.get('id','?') for p in mangler_farve[:5])}"
          f"{'…' if len(mangler_farve) > 5 else ''}) — "
          f"bede vises med standardfarve")
    else:
        OK(f"Alle {len(alle_planter)} planter har farve-felt")

    # Billeder
    fotos_planter = os.path.join("fotos", "planter")
    for p in alle_planter:
        foto_data = p.get("foto")
        if isinstance(foto_data, dict):
            foto = foto_data.get("fil", "")
            if foto and not foto.startswith("http"):
                sti = os.path.join(fotos_planter, foto)
                if not os.path.isfile(sti):
                    W(f"fotos/planter/{foto} refereret i '{p.get('id','?')}' "
                      f"men filen eksisterer ikke — "
                      f"tilføj filen eller ret foto-feltet")

    # Kalenderdata
    kal_advarsler_før = advarsler
    for p in alle_planter:
        navn = p.get("navn", "?")
        pid  = p.get("id", "?")
        hf   = p.get("høst_fra")
        ht   = p.get("høst_til")
        ind  = p.get("indendørs")
        upl  = p.get("udplantning")
        dir_ = p.get("direkte")

        if hf and ht and hf > ht:
            if not (hf > 6 and ht < 6):
                W(f"'{pid}' ({navn}): høst_fra={hf} > høst_til={ht} — "
                  f"ret tallene, eller er det wrap-around (fx grønkål okt–mar)?")
            else:
                OK(f"'{pid}' ({navn}): wrap-around høst ({hf}–{ht}) antaget")

        if ind and upl and ind > upl:
            W(f"'{pid}' ({navn}): indendørs={ind} > udplantning={upl} — "
              f"udplantning skal være efter forspiring")

        if not any([hf, ind, upl, dir_]):
            W(f"'{pid}' ({navn}): ingen kalenderdata — "
              f"tilføj mindst ét af høst_fra/indendørs/udplantning/direkte")

        for felt, val in [("indendørs", ind), ("udplantning", upl),
                          ("direkte", dir_), ("høst_fra", hf), ("høst_til", ht)]:
            if val is not None and not (1 <= val <= 12):
                E(f"'{pid}' ({navn}): {felt}={val} er ikke 1–12 — "
                  f"brug månedsnummer 1–12")

    if advarsler == kal_advarsler_før and fejl == 0:
        OK("Kalenderdata ser fornuftig ud")

    # ── 2. YAML-projektfiler ───────────────────────────────────────────────────
    print(f"\n🔍 2. YAML-projektfiler\n")

    plante_ids_db = {p["id"] for p in alle_planter if p.get("id")}
    kendte_html_navne = set()

    for yaml_sti in yaml_filer:
        if not os.path.isfile(yaml_sti):
            E(f"{yaml_sti} mangler — ret bede-listen i haven.yaml "
              f"eller opret filen med: have ny-bed")
            continue

        data  = load_bed_yaml(yaml_sti)
        meta  = data.get("meta", {})
        titel = meta.get("titel", yaml_sti)

        # meta.html_navn
        html_navn = meta.get("html_navn")
        if not html_navn:
            E(f"{yaml_sti}: meta.html_navn mangler — "
              f"siden kan ikke genereres, tilføj fx 'html_navn: hoejbede'")
        else:
            kendte_html_navne.add(html_navn)

        # meta.år
        meta_år = meta.get("år")
        if meta_år and meta_år != AKTIVT_ÅR:
            W(f"{yaml_sti}: meta.år={meta_år} men AKTIVT_ÅR={AKTIVT_ÅR} — "
              f"opdatér meta.år i filen eller aktivt_år i haven.yaml")

        # plante_id krydsreferencer
        ukendte = []
        for bed in data.get("bede", []):
            bed_navn = bed.get("navn", "?")
            for zone in bed.get("zoner", []):
                for kilde in zone.get("afgrøder", []):
                    pid = kilde.get("plante_id", "")
                    if pid and pid not in plante_ids_db:
                        ukendte.append(f"{bed_navn}/{pid}")
        for pid in data.get("kalender_planter", []):
            if pid not in plante_ids_db:
                ukendte.append(f"kalender_planter/{pid}")
        if ukendte:
            W(f"{titel}: {len(ukendte)} ukendt(e) plante_id(er): "
              f"{', '.join(ukendte[:4])}{'…' if len(ukendte) > 4 else ''} — "
              f"tilføj dem til {PLANTER_FIL}")
        else:
            OK(f"{titel}: alle plante_id'er fundet i databasen")

        # Bredde-sum pr. bed
        for bed in data.get("bede", []):
            zoner = bed.get("zoner", [])
            if not zoner:
                continue
            if not all(z.get("bredde") is not None for z in zoner):
                continue  # ingen bredde-felter — spring over
            total = sum(z.get("bredde", 0) for z in zoner)
            if abs(total - 1.0) > 0.01:
                W(f"{titel} / {bed.get('navn','?')}: "
                  f"bredde-sum = {total:.2f} (forventet 1.0) — "
                  f"hul eller overlap i bedvisningen")

    # ── 3. almanak.yaml ────────────────────────────────────────────────────────
    if os.path.isfile(ALMANAK_FIL) and kendte_html_navne:
        print(f"\n🔍 3. almanak.yaml\n")
        alm = load_yaml(ALMANAK_FIL)
        MÅNED_NAVNE = ["januar","februar","marts","april","maj","juni",
                       "juli","august","september","oktober","november","december"]
        mangler_ind = []
        for m in alm.get("måneder", []):
            mån_navn = MÅNED_NAVNE[m["måned"] - 1]
            ind_ids  = {i["område_id"] for i in m.get("indledninger", [])
                        if i.get("tekst","").strip()}
            for oid in kendte_html_navne:
                if oid not in ind_ids:
                    mangler_ind.append(f"{mån_navn}/{oid}")
        if mangler_ind:
            W(f"{len(mangler_ind)} indledning(er) mangler tekst i almanak.yaml "
              f"(fx {mangler_ind[0]}) — "
              f"udfyld tekst-felterne eller ignorer hvis intentionelt tomt")
        else:
            OK(f"Alle områder har indledning i alle måneder")

    # ── 4. entries.yaml ────────────────────────────────────────────────────────
    if os.path.isfile(ENTRIES_FIL) and kendte_html_navne:
        print(f"\n🔍 4. entries.yaml\n")
        entries_data = load_yaml(ENTRIES_FIL)
        entries      = entries_data.get("entries") or []
        ukendte_omr  = set()
        for e in entries:
            oid = e.get("område_id", "")
            if oid and oid not in kendte_html_navne:
                ukendte_omr.add(oid)
        if ukendte_omr:
            W(f"entries.yaml: {len(ukendte_omr)} ukendt(e) område_id(er): "
              f"{', '.join(sorted(ukendte_omr))} — "
              f"entries vises ikke; ret område_id til et af: "
              f"{', '.join(sorted(kendte_html_navne))}")
        else:
            OK(f"{len(entries)} entries — alle område_id'er kendte")

    # ── 5. Farvetabel (kun ved --farver) ───────────────────────────────────────
    if farver:
        print(f"\n🔍 Farver\n")
        print(f"  {'Plante':<25} {'Sort':<20} Farve")
        print(f"  {'─'*58}")
        farve_mangler = []
        for p in alle_planter:
            farve = p.get("farve")
            navn  = p.get("navn", p.get("id", "?"))
            sort  = p.get("sort", "")
            if farve:
                try:
                    swatch = (f"\033[48;2;{int(farve[1:3],16)};"
                              f"{int(farve[3:5],16)};{int(farve[5:],16)}m   \033[0m")
                except ValueError:
                    swatch = "   "
                print(f"  {navn:<25} {sort:<20} {swatch} {farve}")
            else:
                print(f"  ⚠️  {navn:<23} {sort:<20} — mangler farve-felt")
                farve_mangler.append(p)
        print()
        if farve_mangler:
            print(f"  ⚠️  {len(farve_mangler)} planter mangler farve-felt.")
        else:
            print(f"  ✅ Alle {len(alle_planter)} planter har farve-felt.")

    # ── 6. Opsummering ─────────────────────────────────────────────────────────
    print(f"\n{'─'*40}")
    if fejl == 0 and advarsler == 0:
        print(f"✅ Alt ser fint ud! {len(alle_planter)} planter valideret.\n")
    elif fejl == 0:
        suffix = " — kør med --strict for at behandle dem som fejl" if not strict else ""
        print(f"⚠️  0 fejl, {advarsler} advarsler{suffix}.\n")
    else:
        print(f"❌ {fejl} fejl, {advarsler} advarsler — ret fejlene før du genererer.\n")


def _slug(tekst):
    """Lav et filnavn-venligt slug fra dansk tekst."""
    oversæt = {"æ": "ae", "ø": "oe", "å": "aa", " ": "-"}
    slug = tekst.lower()
    for fra, til in oversæt.items():
        slug = slug.replace(fra, til)
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    return slug.strip("-") or "have"


def slugify(tekst: str) -> str:
    """Slugificér tekst efter id-konventionen for planter.

    Trin: dansk translitteration (æ→ae, ø→oe, å→aa) FØR ascii-encoding,
    Unicode NFKD-normalisering, lowercase, alt ikke-alfanumerisk → bindestreg,
    og strip af leading/trailing bindestreger. Resultatet indeholder kun a-z, 0-9, '-'.
    """
    import re as _re
    import unicodedata as _ud
    s = tekst or ""
    for fra, til in (("æ", "ae"), ("ø", "oe"), ("å", "aa"),
                     ("Æ", "ae"), ("Ø", "oe"), ("Å", "aa")):
        s = s.replace(fra, til)
    s = _ud.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = _re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def plante_id(navn: str, sort: str | None = None) -> str:
    """Byg et plante-id fra navn (+ sort hvis angivet) via slugify."""
    tekst = f"{navn} {sort}" if sort else (navn or "")
    return slugify(tekst)


def generer_ics(almanak_sti, ics_sti, år, yaml_filer=None):
    """Generer en ICS-kalender fra almanak.yaml — én VEVENT pr. måned."""
    alm    = load_yaml(almanak_sti)
    now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Byg opslagsdict: område_id → {ikon, titel} fra bed-YAML meta-blokke
    område_meta = {}
    for yaml_sti in (yaml_filer or []):
        if not os.path.exists(yaml_sti):
            continue
        data = load_yaml(yaml_sti)
        meta = data.get("meta", {})
        oid  = meta.get("html_navn", "")
        if oid:
            område_meta[oid] = {
                "ikon":  meta.get("ikon", "🌿"),
                "titel": meta.get("titel", oid),
            }

    def ics_escape(s):
        """Escape ICS special chars; newlines → \\n (literal)."""
        s = s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
        s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "")
        return s.strip()

    def ics_fold(line):
        """Fold long lines per RFC 5545 (max 75 octets, continuation with SP)."""
        chunks = []
        while True:
            if len(line.encode("utf-8")) <= 75:
                chunks.append(line)
                break
            n = 75
            while len(line[:n].encode("utf-8")) > 75:
                n -= 1
            chunks.append(line[:n])
            line = " " + line[n:]
        return "\r\n".join(chunks)

    vevents = []
    for mån in alm.get("måneder", []):
        måned_nr   = mån["måned"]
        måned_navn = mån.get("navn", f"Måned {måned_nr}")
        dato_start = f"{år}{måned_nr:02d}01"
        dato_end   = (datetime.date(år, måned_nr, 1) + datetime.timedelta(days=1)).strftime("%Y%m%d")

        # Gruppér begivenheder pr. område (bevar rækkefølge)
        område_bev: dict = {}
        for bev in mån.get("begivenheder", []):
            tekst = bev.get("tekst", "").strip()
            oid   = bev.get("område_id", "")
            if not tekst or not oid:
                continue
            første_linje = tekst.splitlines()[0].strip()
            if første_linje:
                område_bev.setdefault(oid, []).append(første_linje)

        if not område_bev:
            continue  # Måneden har ingen begivenheder — spring over

        # Byg DESCRIPTION: ikon+titel som overskrift, begivenheder med •
        desc_dele = []
        for oid, bevs in område_bev.items():
            om    = område_meta.get(oid, {"ikon": "🌿", "titel": oid})
            ovs   = ics_escape(f"{om['ikon']} {om['titel']}")
            punkt = "\\n• ".join(ics_escape(b) for b in bevs)
            desc_dele.append(f"{ovs}\\n• {punkt}")
        description = "\\n\\n".join(desc_dele)

        summary = f"\U0001f33f Haven \u2014 {måned_navn} {år}"
        uid     = f"{år}-{måned_nr:02d}@have.py"

        vevents.append("\r\n".join([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_ts}",
            f"DTSTART;VALUE=DATE:{dato_start}",
            f"DTEND;VALUE=DATE:{dato_end}",
            ics_fold(f"SUMMARY:{summary}"),
            ics_fold(f"DESCRIPTION:{description}"),
            "END:VEVENT",
        ]))

    header  = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//have.py//Havealmanak//DA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Havealmanak {år}",
    ])
    indhold = header + "\r\n" + "\r\n".join(vevents) + "\r\nEND:VCALENDAR\r\n"

    with open(ics_sti, "w", encoding="utf-8", newline="") as f:
        f.write(indhold)
    print(f"✅ ICS-kalender genereret: {ics_sti} ({len(vevents)} måneder)")


# ── RSS ────────────────────────────────────────────────────────────────────────

_RFC_DAGE  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_RFC_MÅNDR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _xml_escape(s):
    """Escape XML special chars i tekst-indhold."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rfc2822(dato):
    """Formater dato som RFC 2822-streng til brug i RSS pubDate/lastBuildDate."""
    d = dato if hasattr(dato, "year") else datetime.date.fromisoformat(str(dato))
    return (f"{_RFC_DAGE[d.weekday()]}, {d.day:02d} "
            f"{_RFC_MÅNDR[d.month - 1]} {d.year} 00:00:00 +0000")


def _rss_kanal_header(år, base_url):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        '  <channel>\n'
        f'    <title>Haven {år}</title>\n'
        f'    <link>{base_url}/{år}/</link>\n'
        '    <description>Havens dagbog og almanak</description>\n'
        '    <language>da</language>\n'
        f'    <lastBuildDate>{_rfc2822(datetime.date.today())}</lastBuildDate>\n'
    )


def generer_rss_dagbog(entries_sti, rss_sti, år, base_url):
    """Generer have-dagbog.rss — ét <item> pr. entry, nyeste først."""
    data    = load_yaml(entries_sti)
    entries = sorted(
        [e for e in (data.get("entries") or [])
         if e.get("dato") and e.get("titel")],
        key=lambda e: str(e["dato"]),
        reverse=True,
    )

    items = []
    for e in entries:
        dato_str = str(e["dato"])
        oid      = e.get("område_id", "")
        titel    = _xml_escape(e.get("titel", ""))
        tekst    = _xml_escape(str(e.get("tekst", "")).strip())
        pub_date = _rfc2822(e["dato"])
        guid     = f"{base_url}/{år}/have-dagbog.rss#{oid}-{dato_str}"
        items.append(
            "    <item>\n"
            f"      <title>{titel}</title>\n"
            f"      <description>{tekst}</description>\n"
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"      <category>{_xml_escape(oid)}</category>\n"
            f"      <guid isPermaLink=\"false\">{_xml_escape(guid)}</guid>\n"
            "    </item>"
        )

    indhold = (_rss_kanal_header(år, base_url)
               + "\n".join(items) + "\n"
               + "  </channel>\n</rss>\n")
    with open(rss_sti, "w", encoding="utf-8") as f:
        f.write(indhold)
    print(f"✅ RSS dagbog genereret: {rss_sti} ({len(entries)} entries)")


def generer_rss_almanak(almanak_sti, rss_sti, år, base_url, yaml_filer=None):
    """Generer have-almanak.rss — ét <item> pr. måned med begivenheder."""
    alm = load_yaml(almanak_sti)

    # Byg opslagsdict: område_id → {ikon, titel}
    område_meta = {}
    for yaml_sti in (yaml_filer or []):
        if not os.path.exists(yaml_sti):
            continue
        meta = load_yaml(yaml_sti).get("meta", {})
        oid  = meta.get("html_navn", "")
        if oid:
            område_meta[oid] = {
                "ikon":  meta.get("ikon", "🌿"),
                "titel": meta.get("titel", oid),
            }

    items = []
    for mån in alm.get("måneder", []):
        måned_nr   = mån["måned"]
        måned_navn = mån.get("navn", f"Måned {måned_nr}")

        # Gruppér begivenheder pr. område
        område_bev: dict = {}
        for bev in mån.get("begivenheder", []):
            tekst = bev.get("tekst", "").strip()
            oid   = bev.get("område_id", "")
            if not tekst or not oid:
                continue
            første = tekst.splitlines()[0].strip()
            if første:
                område_bev.setdefault(oid, []).append(første)

        if not område_bev:
            continue

        # Byg description: ikon+titel som overskrift, begivenheder med •
        desc_dele = []
        for oid, bevs in område_bev.items():
            om    = område_meta.get(oid, {"ikon": "🌿", "titel": oid})
            ovs   = f"{om['ikon']} {om['titel']}"
            punkt = "\n• ".join(bevs)
            desc_dele.append(f"{ovs}\n• {punkt}")
        description = _xml_escape("\n\n".join(desc_dele))

        titel    = _xml_escape(f"🌿 Haven — {måned_navn} {år}")
        pub_date = _rfc2822(datetime.date(år, måned_nr, 1))
        guid     = f"{base_url}/{år}/have-almanak.rss#{år}-{måned_nr:02d}"

        items.append(
            "    <item>\n"
            f"      <title>{titel}</title>\n"
            f"      <description>{description}</description>\n"
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"      <guid isPermaLink=\"false\">{guid}</guid>\n"
            "    </item>"
        )

    indhold = (_rss_kanal_header(år, base_url)
               + "\n".join(items) + "\n"
               + "  </channel>\n</rss>\n")
    with open(rss_sti, "w", encoding="utf-8") as f:
        f.write(indhold)
    print(f"✅ RSS almanak genereret: {rss_sti} ({len(items)} måneder)")


_META_FELTER_DEFAULT = {
    "titel": "",
    "html_navn": "",
    "ikon": "",
    "ikon_billede": "",
    "undertitel": "",
    "beskrivelse": "",
    "tags": [],
}


_STARTER_BEDE = {
    "hoejbede": """\
bede:
- id: bed-1
  navn: Bed 1
  bredde_cm: 120
  dybde_cm: 80
  farve: '#e8f5e9'
  zoner:
  - navn: Salat
    bredde: 0.5
    plante_id: salat-eksempel
  - navn: Gulerødder
    bredde: 0.5
    plante_id: gulerod-eksempel

kalender_planter: [salat-eksempel, gulerod-eksempel]
""",
    "krydderurter": """\
bede:
- id: palleramme-1
  navn: Palleramme 1
  bredde_cm: 120
  dybde_cm: 80
  farve: '#fef9e7'
  zoner:
  - navn: Basilikum
    bredde: 0.5
    plante_id: basilikum-eksempel
  - navn: Persille
    bredde: 0.5
    plante_id: persille-eksempel

kalender_planter: [basilikum-eksempel, persille-eksempel]
""",
    "frugthaven": """\
bede:
- id: frugtbed-1
  navn: Bærbed
  bredde_cm: 200
  dybde_cm: 60
  farve: '#fce4ec'
  zoner:
  - navn: Jordbær
    bredde: 0.6
    plante_id: jordbær-eksempel
  - navn: Hindbær
    bredde: 0.4
    plante_id: hindbær-eksempel

kalender_planter: [jordbær-eksempel, hindbær-eksempel]
""",
    "drivhus": """\
bede:
- id: drivhus-1
  navn: Drivhus — sektion 1
  bredde_cm: 200
  dybde_cm: 80
  farve: '#e3f2fd'
  zoner:
  - navn: Tomater
    bredde: 0.5
    plante_id: tomat-eksempel
  - navn: Agurker
    bredde: 0.5
    plante_id: agurk-eksempel

kalender_planter: [tomat-eksempel, agurk-eksempel]
""",
}


def _lav_område_yaml(om, år):
    meta = (
        f"# {om['titel']} {år}\n\n"
        f"meta:\n"
        f"  år: {år}\n"
        f"  titel: \"{om['titel']}\"\n"
        f"  html_navn: \"{om['html_navn']}\"\n"
        f"  ikon: \"{om['ikon']}\"\n"
        f"  ikon_billede: \"\"\n"
        f"  undertitel: \"{om['undertitel']}\"\n"
        f"  beskrivelse: \"\"\n"
        f"  tags: []\n\n"
    )
    bede = _STARTER_BEDE.get(om["html_navn"], "bede: []\n\nkalender_planter: []\n")
    return meta + bede


_ALMANAK_MÅNEDSTEKST = [
    "Havens hvilemåned. Planlæg sæsonen og bestil frø.",
    "Første forspiring indendørs — tomater og peberfrugter.",
    "Forspiring skyder fart. Tjek udstyret.",
    "Travleste forspiremåned. Direkte såning begynder.",
    "Nat-frosten er næsten ovre. Udplantning nærmer sig.",
    "Udplantning af de varmekrævende afgrøder.",
    "Høstsæsonen åbner. Hold øje med vand.",
    "Fuld høstsæson. Løbende høst og såning af efterårskulturer.",
    "Efterårshøst og oprydning. Sæt løg og hvidløg.",
    "Frosten kommer. Grønkål smager bedst nu.",
    "Afslut sæsonen. Kompostér og dæk bedene.",
    "Ro i haven. Planlæg næste år.",
]


_STARTER_BEGIVENHEDER = {
    "hoejbede":    {4: "Så gulerødder direkte og plant salat ud."},
    "krydderurter":{5: "Sæt basilikum ud — venter til efter frost."},
    "frugthaven":  {6: "Jordbær begynder at modne — høst løbende."},
    "drivhus":     {5: "Udplant tomater og agurker i drivhuset."},
}


def _lav_almanak_yaml(have_titel, områder, år):
    måneder_navne = [
        "Januar", "Februar", "Marts", "April", "Maj", "Juni",
        "Juli", "August", "September", "Oktober", "November", "December",
    ]
    tags_str = ", ".join(f'"{om["titel"]}"' for om in områder)

    linjer = [
        f"# Havealmanak {år}",
        "# område_id knytter indledninger og begivenheder til de enkelte haver.",
        "",
        "meta:",
        f"  år: {år}",
        '  titel: "Havealmanak"',
        '  html_navn: "almanak"',
        f'  undertitel: "{have_titel}"',
        '  beskrivelse: ""',
        '  ikon: "📖"',
        f"  tags: [{tags_str}]",
        "",
        "måneder:",
    ]
    for i, navn in enumerate(måneder_navne, 1):
        tekst = _ALMANAK_MÅNEDSTEKST[i - 1]
        linjer += [
            "",
            f"  - måned: {i}",
            f'    navn: "{navn}"',
            "    indledninger:",
        ]
        for om in områder:
            linjer += [
                f"      - område_id: {om['html_navn']}",
                f'        tekst: "{tekst}"',
            ]
        linjer.append("    begivenheder:")
        for om in områder:
            begivenhed = _STARTER_BEGIVENHEDER.get(om["html_navn"], {}).get(i, "")
            linjer += [
                f"      - område_id: {om['html_navn']}",
                f'        tekst: "{begivenhed}"',
            ]
        linjer.append("    entries: []")

    return "\n".join(linjer) + "\n"


def _lav_entries_yaml(år: int, zone: str) -> str:
    import datetime
    april = datetime.date(år, 4, 20).isoformat()
    maj   = datetime.date(år, 5, 12).isoformat()
    return (
        f"# Haveentries {år}\n"
        "# Brug 'have ny-entry' til at oprette entries interaktivt,\n"
        "# eller skriv dem direkte her. Eksempel:\n"
        "#\n"
        "# entries:\n"
        f"#   - dato: {april}\n"
        f"#     zone: {zone}       # HTML-navn på det bed du skriver om\n"
        "#     plante_id: nantes   # ID på planten (valgfri)\n"
        "#     tekst: |\n"
        "#       De første gulerødder er spiret frem — fine, hårfine blade.\n"
        "#\n"
        "#       Markdown virker: **fed**, *kursiv*, lister osv.\n"
        f"#   - dato: {maj}\n"
        f"#     zone: {zone}\n"
        "#     tekst: Lugede ukrudt og vandede.\n"
        "#     foto:\n"
        f"#       fil: mit-foto.jpg   # Placér billedet i fotos/entries/{år}/\n"
        "#       tekst: Billedtekst\n"
        "\n"
        "entries: []\n"
    )


def _find_yaml_filer():
    """Find projektets YAML-filer i DATA_MAPPE automatisk. Fallback: YAML_FILER_DEFAULT."""
    SYSTEM_FILER = {"planter.yaml", "almanak.yaml", "entries.yaml"}
    if os.path.isdir(DATA_MAPPE):
        filer = sorted(
            os.path.join(DATA_MAPPE, f)
            for f in os.listdir(DATA_MAPPE)
            if f.endswith(".yaml") and not f.startswith(".") and f not in SYSTEM_FILER
            and os.path.isfile(os.path.join(DATA_MAPPE, f))
        )
        if filer:
            return filer
    return YAML_FILER_DEFAULT


def init_projekt(ja: bool = False):
    import shutil
    år = AKTIVT_ÅR

    def _spørg(prompt: str, default: str = "") -> str:
        if ja:
            print(f"{prompt}{default}")
            return default
        import re as _re
        import questionary
        clean = _re.sub(r"\s*\[.*?\]\s*$", "", prompt.rstrip(": \t")).strip()
        svar = questionary.text(f"{clean}:", default=default).ask()
        return (svar or "").strip() or default

    STANDARD_OMRÅDER = {
        "højbede":      {"titel": "Højbedshaven",    "ikon": "🥕", "undertitel": "Køkkengrøntsager",                "html_navn": "hoejbede"},
        "krydderurter": {"titel": "Krydderurtehaven", "ikon": "🌱", "undertitel": "Pallerammer",                      "html_navn": "krydderurter"},
        "frugthaven":   {"titel": "Frugthaven",       "ikon": "🍎", "undertitel": "Frugttræer og bærbuske",          "html_navn": "frugthaven"},
        "drivhus":      {"titel": "Drivhuset",        "ikon": "🏡", "undertitel": "Tomater, agurker & peberfrugter", "html_navn": "drivhus"},
    }

    print("\n🌱 Opret nyt haveprojekt\n")

    # ── 1. Havens navn ──
    have_titel = _spørg("Navn på haven (sidetitel): ", "Min Have")

    # ── 2. Vælg områder ──
    if ja:
        valg_liste = list(STANDARD_OMRÅDER)
    else:
        import questionary as _q
        valg_liste = _q.checkbox(
            "Vælg standardområder:",
            choices=[
                _q.Choice(
                    title=f"{info['ikon']}  {info['titel']} — {info['undertitel']}",
                    value=nøgle,
                    checked=True,
                )
                for nøgle, info in STANDARD_OMRÅDER.items()
            ],
        ).ask() or list(STANDARD_OMRÅDER)

    # ── 3. Detaljer for hvert område ──
    områder = []
    for valg in valg_liste:
        if not valg:
            continue
        if valg in STANDARD_OMRÅDER:
            std = STANDARD_OMRÅDER[valg]
            print(f"\n{std['ikon']}  {std['titel']}")
            titel      = _spørg(f"  Titel [{std['titel']}]: ",      std["titel"])
            ikon       = _spørg(f"  Ikon [{std['ikon']}]: ",        std["ikon"])
            undertitel = _spørg(f"  Undertitel [{std['undertitel']}]: ", std["undertitel"])
            html_navn  = std["html_navn"]
        else:
            print(f"\n📌  Brugerdefineret område: '{valg}'")
            titel      = _spørg(f"  Titel [{valg}]: ", valg)
            ikon       = _spørg(f"  Ikon [🌿]: ",      "🌿")
            undertitel = _spørg(f"  Undertitel: ")
            html_navn  = _slug(valg)
        områder.append({
            "titel": titel, "ikon": ikon, "undertitel": undertitel,
            "html_navn": html_navn, "yaml_fil": f"{html_navn}.yaml",
        })

    if not områder:
        print("❌ Ingen områder valgt.")
        sys.exit(1)

    # ── FTP-konfiguration ──
    if ja:
        ftp_host = ftp_bruger = ftp_kode = ""
        ftp_mappe = "/"
    else:
        import questionary as _q
        print("\nFTP-upload (tryk Enter for at springe over):")
        ftp_host   = (_q.text("  Server (fx ftp.example.com):").ask() or "").strip()
        ftp_bruger = (_q.text("  Brugernavn:").ask() or "").strip()
        ftp_kode   = (_q.text("  Adgangskode:").ask() or "").strip()
        ftp_mappe  = (_q.text("  Mappe på server:", default="/").ask() or "/").strip()

    # ── 4. Opret undermapper i nuværende mappe ──
    if os.path.exists("data") and (
        any(os.path.isdir(os.path.join("data", f)) for f in os.listdir("data"))
        or any(f.endswith(".yaml") for f in os.listdir("data"))
    ):
        print("❌ 'data/' ser ud til allerede at være initialiseret. Afbryder.")
        sys.exit(1)

    os.makedirs("data", exist_ok=True)
    os.makedirs(os.path.join("data", str(år)), exist_ok=True)
    os.makedirs("fotos/planter", exist_ok=True)
    os.makedirs(os.path.join("fotos", "entries", str(år)), exist_ok=True)
    os.makedirs("out", exist_ok=True)

    # templates/ og static/ — kopiér fra pakkedata
    from importlib.resources import files as _pkg_files
    for mappe_navn in ("templates", "static"):
        if not os.path.exists(mappe_navn):
            os.makedirs(mappe_navn)
        pkg_mappe = _pkg_files("haven").joinpath(mappe_navn)
        for ressource in pkg_mappe.iterdir():
            dest = os.path.join(mappe_navn, ressource.name)
            if not os.path.exists(dest):
                Path(dest).write_bytes(ressource.read_bytes())

    # ── 5. Skriv YAML-filer ──
    data_år_sti = os.path.join("data", str(år))
    for om in områder:
        with open(os.path.join(data_år_sti, om["yaml_fil"]), "w", encoding="utf-8") as f:
            f.write(_lav_område_yaml(om, år))

    planter_sti = os.path.join("data", "planter.yaml")
    planter_fandtes = os.path.exists(planter_sti)
    if not planter_fandtes:
        with open(planter_sti, "w", encoding="utf-8") as f:
            f.write(_PLANTER_YAML.format(år=år))

    with open(os.path.join(data_år_sti, "almanak.yaml"), "w", encoding="utf-8") as f:
        f.write(_lav_almanak_yaml(have_titel, områder, år))

    første_zone = områder[0]["html_navn"] if områder else "hoejbede"
    with open(os.path.join(data_år_sti, "entries.yaml"), "w", encoding="utf-8") as f:
        f.write(_lav_entries_yaml(år, første_zone))

    om_sti = os.path.join("data", "om.yaml")
    om_fandtes = os.path.exists(om_sti)
    if not om_fandtes:
        with open(om_sti, "w", encoding="utf-8") as f:
            f.write(_OM_YAML.format(have_titel=have_titel, år=år))

    kontakt_sti = os.path.join("data", "kontakt.yaml")
    kontakt_fandtes = os.path.exists(kontakt_sti)
    if not kontakt_fandtes:
        with open(kontakt_sti, "w", encoding="utf-8") as f:
            f.write(_KONTAKT_YAML)

    # ── 5b. Opdatér haven.yaml's bede-liste ──
    bede_liste = [om["html_navn"] for om in områder]
    _opdater_haven_yaml(lambda cfg: cfg.__setitem__("bede", bede_liste), ".")

    # ── 6. FTP-config og opsummering ──
    if ftp_host or ftp_bruger:
        _opdater_ftp_config(ftp_host, ftp_bruger, ftp_kode, ftp_mappe, ".")
        print("✅ FTP-konfiguration gemt i haven.yaml")
        if ftp_kode:
            print("   ⚠️  Adgangskoden gemmes ikke — sæt: export HAVE_FTP_KODE=ditpassword")

    print(f"\n✅ '{have_titel}' oprettet i data/{år}/")
    print(f"\n   Oprettede filer:")
    for om in områder:
        print(f"   - data/{år}/{om['yaml_fil']}")
    if planter_fandtes:
        print(f"   - data/planter.yaml  (eksisterede allerede — beholdt)")
    else:
        print(f"   - data/planter.yaml")
    print(f"   - data/{år}/almanak.yaml")
    print(f"   - data/{år}/entries.yaml")
    if om_fandtes:
        print(f"   - data/om.yaml  (eksisterede allerede — beholdt)")
    else:
        print(f"   - data/om.yaml")
    if kontakt_fandtes:
        print(f"   - data/kontakt.yaml  (eksisterede allerede — beholdt)")
    else:
        print(f"   - data/kontakt.yaml")
    print()
    print(f"Byg sitet:")
    print(f"  have build")
    print()
    print(f"Tilføj planter ved at redigere dine YAML-filer og køre 'have build' igen.")
    print(f"Næste sæson: have nyt-år {år + 1}")


# ── Nyt område ────────────────────────────────────────────────────────────────

def nyt_område():
    """Interaktivt opret et nyt havområde i det aktuelle projekt."""
    import datetime
    import questionary
    år = datetime.date.today().year

    print("\n🌿 Nyt havområde\n")

    titel = questionary.text(
        "Titel:",
        validate=lambda v: bool(v.strip()) or "Titel er påkrævet",
    ).ask()
    if not titel:
        sys.exit(0)
    titel = titel.strip()
    ikon       = (questionary.text("Ikon (kan være blank):").ask() or "").strip()
    undertitel = (questionary.text("Undertitel:").ask() or "").strip()
    html_navn  = _slug(titel)

    om = {
        "titel": titel, "ikon": ikon, "undertitel": undertitel,
        "html_navn": html_navn, "yaml_fil": f"{html_navn}.yaml",
    }

    # ── Skriv område-YAML ──
    yaml_sti = os.path.join(DATA_MAPPE, om["yaml_fil"])
    if os.path.exists(yaml_sti):
        print(f"❌ '{yaml_sti}' findes allerede.")
        sys.exit(1)
    os.makedirs(DATA_MAPPE, exist_ok=True)
    with open(yaml_sti, "w", encoding="utf-8") as f:
        f.write(_lav_område_yaml(om, år))
    print(f"✅ Oprettet: {yaml_sti}")

    # ── Opdatér almanak.yaml ──
    if os.path.exists(ALMANAK_FIL):
        data = load_yaml(ALMANAK_FIL)
        for måned in data.get("måneder", []):
            måned.setdefault("indledninger", []).append(
                {"område_id": html_navn, "tekst": ""}
            )
            måned.setdefault("begivenheder", []).append(
                {"område_id": html_navn, "tekst": ""}
            )
        meta = data.setdefault("meta", {})
        tags = meta.setdefault("tags", [])
        if titel not in tags:
            tags.append(titel)
        with open(ALMANAK_FIL, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                      sort_keys=False, indent=2)
        print(f"✅ Opdateret: {ALMANAK_FIL}")
    else:
        print(f"ℹ️  {ALMANAK_FIL} ikke fundet — spring almanak over.")

    print(f"\n   Husk at tilføje til bede-listen i haven.yaml:")
    print(f'   - {om["html_navn"]}')


# ── Nyt år ────────────────────────────────────────────────────────────────────

def nyt_år(nyt_år_num: int):
    """Klargør data/<nyt_år>/ og fotos/entries/<nyt_år>/ til den kommende sæson."""
    import shutil
    fra_mappe = DATA_MAPPE.parent / str(nyt_år_num - 1)   # data/{nyt_år_num - 1}
    til_mappe = f"data/{nyt_år_num}"

    import questionary
    print(f"\nDette vil oprette {til_mappe}/ ved at kopiere alle filer fra {fra_mappe}/")
    print(f"og nulstille entries.yaml til tom liste.\n")
    if not questionary.confirm("Er du sikker?", default=False).ask():
        print("Afbrudt.")
        sys.exit(0)

    if not os.path.isdir(fra_mappe):
        print(f"❌ {fra_mappe} findes ikke.")
        sys.exit(1)
    if os.path.exists(til_mappe):
        print(f"❌ {til_mappe} findes allerede.")
        sys.exit(1)

    os.makedirs(til_mappe)

    SPRING_OVER = {"entries.yaml"}
    kopierede = []
    for fil in sorted(os.listdir(fra_mappe)):
        if not fil.endswith(".yaml") or fil.startswith(".") or fil in SPRING_OVER:
            continue
        kilde = os.path.join(fra_mappe, fil)
        mål   = os.path.join(til_mappe, fil)
        shutil.copy(kilde, mål)
        # Opdatér meta.år og backfill manglende meta-felter i kopien
        data = load_yaml(mål)
        if isinstance(data, dict) and "meta" in data:
            data["meta"]["år"] = nyt_år_num
            for felt, standard in _META_FELTER_DEFAULT.items():
                data["meta"].setdefault(felt, standard)
            with open(mål, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                          sort_keys=False, indent=2)
        kopierede.append(fil)
        print(f"  📄 {fil} kopieret og opdateret til år {nyt_år_num}")

    # Tom entries.yaml
    entries_sti = os.path.join(til_mappe, "entries.yaml")
    with open(entries_sti, "w", encoding="utf-8") as f:
        f.write(f"# Haveentries {nyt_år_num}\n# Tilføj noter og fotos her.\n\nentries: []\n")
    print(f"  📄 entries.yaml oprettet (tom)")

    # Opret fotos-mappe
    fotos_mappe = os.path.join("fotos", "entries", str(nyt_år_num))
    os.makedirs(fotos_mappe, exist_ok=True)
    print(f"  📁 {fotos_mappe}/ oprettet")

    print(f"\n✅ {til_mappe}/ klar til sæson {nyt_år_num}")
    print(f"\nNæste skridt: Sæt aktivt_år: {nyt_år_num} i haven.yaml og rediger dine bede-filer")


# ── Global årsindeks ───────────────────────────────────────────────────────────

def generer_redirect_index(out_basis: str, aktivt_år: int) -> None:
    """Generer out/index.html som simpel redirect til aktivt år."""
    os.makedirs(out_basis, exist_ok=True)
    html = f"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url={aktivt_år}/index.html">
<link rel="canonical" href="{aktivt_år}/index.html">
</head>
<body><p><a href="{aktivt_år}/index.html">Gå til haven {aktivt_år}</a></p></body>
</html>"""
    sti = os.path.join(out_basis, "index.html")
    if skriv_hvis_ændret(sti, html):
        print(f"✅ Redirect-index genereret: {sti}")
    else:
        print(f"ℹ️  Redirect-index uændret: {sti}")


def _regenerer_gl_år_sider(gl_år: int, år_liste: list, aktivt_år: int,
                            nav_bede_aktiv: list, have_navn: str, features: dict,
                            env, alle_planter: list, out_rod: Path):
    """Regenerer HTML-sider for et ikke-aktivt år med opdateret år_liste i nav."""
    gl_data = PROJECT_ROOT / "data" / str(gl_år)
    gl_out  = out_rod / str(gl_år)
    if not gl_data.is_dir() or not gl_out.is_dir():
        return

    gl_almanak  = str(gl_data / "almanak.yaml")
    gl_entries  = str(gl_data / "entries.yaml")
    gl_data_sti = str(gl_data)

    gl_yaml_filer = sorted([
        str(gl_data / f) for f in os.listdir(gl_data_sti)
        if f.endswith(".yaml") and not f.startswith(".")
        and f not in ("almanak.yaml", "entries.yaml")
        and os.path.isfile(str(gl_data / f))
    ])

    gl_bede_nav = []
    for gl_yaml in gl_yaml_filer:
        _meta = load_yaml(gl_yaml).get("meta", {})
        _hn = _meta.get("html_navn")
        if _hn:
            gl_bede_nav.append({
                "ikon":      _meta.get("ikon", "🌿"),
                "titel":     _meta.get("titel", _hn),
                "html_navn": _hn,
            })

    def gl_nav(aktiv_side=""):
        return {"nav_bede": gl_bede_nav, "have_navn": have_navn,
                "aktiv_side": aktiv_side, "features": features,
                "år_liste": år_liste, "aktivt_år": aktivt_år}

    for gl_yaml in gl_yaml_filer:
        gl_meta = load_yaml(gl_yaml).get("meta", {})
        gl_hn = gl_meta.get("html_navn")
        if not gl_hn:
            continue
        gl_html = str(gl_out / f"{gl_hn}.html")
        generer_html(gl_yaml, gl_html, env, alle_planter,
                     nav_context=gl_nav(gl_hn),
                     almanak_fil=gl_almanak,
                     entries_fil=gl_entries,
                     data_mappe_sti=gl_data_sti)

    generer_samlet_almanak(gl_yaml_filer, str(gl_out / "almanak.html"), env, alle_planter,
                           nav_context=gl_nav("almanak"),
                           almanak_fil=gl_almanak,
                           entries_fil=gl_entries,
                           år=gl_år)

    gl_projekter = [projekt_info(y) for y in gl_yaml_filer
                    if load_yaml(y).get("meta", {}).get("html_navn")]
    if os.path.isfile(gl_almanak):
        gl_projekter.append(projekt_info(gl_almanak))
    gl_planter_info = projekt_info(str(PLANTER_FIL))
    gl_planter_info["html_navn"] = "../planter"
    gl_projekter.append(gl_planter_info)
    generer_index(gl_projekter, str(gl_out / "index.html"), env,
                  nav_context=gl_nav("hjem"), år=gl_år)

    # Synkronisér fotos for det historiske år
    fotos_basis = PROJECT_ROOT / "fotos"
    if fotos_basis.exists():
        gl_fotos_dest = gl_out / "fotos"
        entries_kilde = fotos_basis / "entries" / str(gl_år)
        if entries_kilde.exists():
            _sync_mappe(entries_kilde, gl_fotos_dest / "entries")
        for fil in fotos_basis.iterdir():
            if fil.is_file():
                dst = gl_fotos_dest / fil.name
                if not dst.exists() or fil.stat().st_mtime > dst.stat().st_mtime:
                    import shutil
                    gl_fotos_dest.mkdir(exist_ok=True)
                    shutil.copy2(fil, dst)
                    os.chmod(dst, 0o644)



# ── Upload ─────────────────────────────────────────────────────────────────────

def _opdater_haven_yaml(fn, arbejdsmappe: str = "."):
    """Læs, modificér og skriv haven.yaml — bevarer kommentarer via ruamel.yaml."""
    from ruamel.yaml import YAML
    sti = os.path.join(arbejdsmappe, "haven.yaml")
    ryaml = YAML()
    ryaml.preserve_quotes = True
    with open(sti, encoding="utf-8") as f:
        cfg = ryaml.load(f)
    fn(cfg)
    with open(sti, "w", encoding="utf-8") as f:
        ryaml.dump(cfg, f)


def _opdater_ftp_config(host, bruger, kode, mappe, arbejdsmappe: str = "."):
    """Skriv FTP-konfiguration (host/bruger/mappe) til haven.yaml."""
    def _opdater(cfg):
        ftp = cfg.setdefault("deploy", {}).setdefault("ftp", {})
        ftp["host"]   = host
        ftp["bruger"] = bruger
        ftp["mappe"]  = mappe
    _opdater_haven_yaml(_opdater, arbejdsmappe)


def upload_ftp(_filer):
    """Upload hele out/-mappen til FTP-server via lftp mirror (kun ændrede filer)."""
    if not FTP_KODE:
        print("❌ HAVE_FTP_KODE er ikke sat — kør: export HAVE_FTP_KODE=ditpassword")
        sys.exit(1)

    out_rod = OUT_MAPPE.parent
    print(f"  ↑ {out_rod}/ → {FTP_BRUGER}@{FTP_HOST}:{FTP_MAPPE}/")
    try:
        result = subprocess.run(
            [
                "lftp",
                "-u", f"{FTP_BRUGER},{FTP_KODE}",
                f"ftp://{FTP_HOST}",
                "-e", (
                    f"mirror -R --delete --verbose {out_rod}/ {FTP_MAPPE}/;"
                    " bye"
                ),
            ],
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        print("❌ lftp er ikke installeret — kør: sudo pacman -S lftp")
        sys.exit(1)

    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        print(f"❌ lftp-fejl (exit {result.returncode}):")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        sys.exit(1)
    print("✅ Alle filer uploadet via lftp.")


def upload(filer):
    """Upload HTML-filer og fotos til server via lftp + SFTP."""
    if not SFTP_KODE:
        print("❌ HAVE_SFTP_KODE er ikke sat — kør: export HAVE_SFTP_KODE=ditpassword")
        sys.exit(1)

    out_rod = OUT_MAPPE.parent
    print(f"  ↑ {out_rod}/ → {SFTP_BRUGER}@{SFTP_HOST}:{SFTP_MAPPE}/")
    try:
        result = subprocess.run(
            [
                "lftp",
                "-u", f"{SFTP_BRUGER},{SFTP_KODE}",
                f"sftp://{SFTP_HOST}",
                "-e", (
                    "set sftp:connect-program 'ssh -o IdentityAgent=none';"
                    f" mirror -R --delete --verbose {out_rod}/ {SFTP_MAPPE}/;"
                    " bye"
                ),
            ],
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        print("❌ lftp er ikke installeret — kør: sudo pacman -S lftp")
        sys.exit(1)

    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        print(f"❌ lftp-fejl (exit {result.returncode}):")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        sys.exit(1)
    print("✅ Alle filer uploadet via lftp.")


# ── Projektinfo til forsiden ───────────────────────────────────────────────────

def projekt_info(yaml_sti):
    """Læs projektmetadata direkte fra YAML-filens meta-blok."""
    data      = load_yaml(yaml_sti)
    meta      = {} if isinstance(data, list) else data.get("meta", {})
    html_navn = meta.get("html_navn", Path(yaml_sti).stem)
    return {
        "titel":       meta.get("titel", html_navn),
        "html_navn":   html_navn,
        "undertitel":  meta.get("undertitel", ""),
        "beskrivelse": meta.get("beskrivelse", ""),
        "ikon":        meta.get("ikon", "🌿"),
        "ikon_billede":meta.get("ikon_billede", ""),
        "tags":        meta.get("tags", []),
    }


# ── Entry-oprettelse ───────────────────────────────────────────────────────────

def _les_entries_mappe(entries_mappe: str) -> list:
    """Læser markdown-filer fra entries-mappen og returnerer liste af entry-dicts."""
    import re as _re
    entries = []
    if not os.path.isdir(entries_mappe):
        return entries
    for fil in sorted(os.listdir(entries_mappe)):
        if not fil.endswith(".md"):
            continue
        sti = os.path.join(entries_mappe, fil)
        with open(sti, encoding="utf-8") as f:
            indhold = f.read()
        m = _re.match(r"^---\n(.*?)\n---\n(.*)$", indhold, _re.DOTALL)
        if not m:
            continue
        try:
            frontmatter = yaml.safe_load(m.group(1))
            tekst_indhold = m.group(2).strip()
        except yaml.YAMLError:
            continue
        if not isinstance(frontmatter, dict):
            continue
        entry = dict(frontmatter)
        entry["tekst"] = tekst_indhold
        entry["_fil"] = Path(sti).stem
        if "zone" in entry and "område_id" not in entry:
            entry["område_id"] = entry["zone"]
        # Normaliser foto: string → {fil, tekst} som skabelonen forventer
        if "foto" in entry and isinstance(entry["foto"], str):
            entry["foto"] = {"fil": os.path.basename(entry["foto"]), "tekst": ""}
        # Normaliser plante_id: string eller liste → altid liste
        pid = entry.get("plante_id")
        if pid is None:
            entry["plante_id"] = []
        elif isinstance(pid, str):
            entry["plante_id"] = [pid] if pid else []
        elif not isinstance(pid, list):
            entry["plante_id"] = list(pid)
        entries.append(entry)
    return entries


_BILLEDE_EKST = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _sync_mappe(kilde: Path, dest: Path) -> int:
    """Kopiér kilde → dest, kun filer der er nye eller nyere. Returnerer antal kopierede filer."""
    import shutil
    dest.mkdir(parents=True, exist_ok=True)
    kopierede = 0
    for src in kilde.iterdir():
        dst = dest / src.name
        if src.is_dir():
            kopierede += _sync_mappe(src, dst)
        elif not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(src, dst)
            os.chmod(dst, 0o644)
            kopierede += 1
    return kopierede


def _generer_manglende_thumbnails(fotos_mappe: Path):
    """Generer thumbs/<fil> (maks 400px) for billeder der mangler thumbnail."""
    from PIL import Image, ImageOps
    thumbs = fotos_mappe / "thumbs"
    thumbs.mkdir(exist_ok=True)
    for billedfil in sorted(fotos_mappe.iterdir()):
        if not billedfil.is_file() or billedfil.suffix.lower() not in _BILLEDE_EKST:
            continue
        thumb = thumbs / billedfil.name
        if thumb.exists():
            continue
        try:
            with Image.open(billedfil) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((400, 400))
                if billedfil.suffix.lower() in (".jpg", ".jpeg"):
                    img.save(thumb, "JPEG", quality=82, optimize=True)
                else:
                    img.save(thumb, optimize=True)
        except Exception:
            pass


def generer_alle(yaml_filer=None) -> list:
    """Generer alle HTML-sider. Returnerer liste af (sti, navn)-tupler til upload."""
    import shutil
    if yaml_filer is None:
        yaml_filer = _find_yaml_filer()

    data_rod = PROJECT_ROOT / "data"
    if not any(data_rod.glob("**/*.yaml")):
        print("❌ Ingen have fundet — kør: have init")
        sys.exit(1)
    if not os.path.isdir(DATA_MAPPE):
        print(f"❌ data/{AKTIVT_ÅR}/ eksisterer ikke — kør: have nyt-år {AKTIVT_ÅR}")
        sys.exit(1)
    if not os.path.isfile(PLANTER_FIL):
        print(f"❌ {PLANTER_FIL} mangler — kør: have init")
        sys.exit(1)

    os.makedirs(OUT_MAPPE, exist_ok=True)
    env          = lav_jinja_env()
    upload_filer = []
    projekter    = []
    advarsler    = []

    planter_data = load_yaml(PLANTER_FIL)
    if isinstance(planter_data, list):
        alle_planter = planter_data
    else:
        alle_planter = planter_data.get("planter", [])
    PLANTE_DB.update(byg_plante_db(PLANTER_FIL))
    print(f"✅ Plantedatabase indlæst: {len(alle_planter)} planter")
    DYR_DB.clear()
    DYR_DB.update(byg_dyr_db())
    if DYR_DB:
        print(f"✅ Dyreregister indlæst: {len(DYR_DB)} dyr")
    valider_planter(PLANTE_DB)
    valider_referencer(PLANTE_DB, yaml_filer)

    # ── Navigation-kontekst ────────────────────────────────────────────────────
    have_navn = _config.get("navn", "")
    if not have_navn and os.path.isfile(ALMANAK_FIL):
        alm_meta = load_yaml(ALMANAK_FIL).get("meta", {})
        have_navn = alm_meta.get("undertitel", "")
    have_navn = have_navn or "Haven"

    nav_bede = []
    for _ys in yaml_filer:
        if not os.path.isfile(_ys):
            continue
        _meta = load_yaml(_ys).get("meta", {})
        _hn   = _meta.get("html_navn")
        if _hn:
            nav_bede.append({
                "ikon":     _meta.get("ikon", "🌿"),
                "titel":    _meta.get("titel", _hn),
                "html_navn": _hn,
            })

    _data_basis = str(PROJECT_ROOT / "data")
    år_liste = sorted([
        int(d) for d in os.listdir(_data_basis)
        if d.isdigit() and os.path.isdir(os.path.join(_data_basis, d))
    ]) if os.path.isdir(_data_basis) else [AKTIVT_ÅR]

    def nav_ctx(aktiv_side="", op_sti="../", jaar_sti=""):
        return {"nav_bede": nav_bede, "have_navn": have_navn, "aktiv_side": aktiv_side,
                "features": _config.get("features", {}), "år_liste": år_liste,
                "aktivt_år": AKTIVT_ÅR, "op_sti": op_sti, "jaar_sti": jaar_sti}
    # ─────────────────────────────────────────────────────────────────────────

    for yaml_sti in yaml_filer:
        if not os.path.isfile(yaml_sti):
            print(f"❌ {yaml_sti} mangler — springer over "
                  f"(ret bede-listen i haven.yaml eller kør: have ny-bed)",
                  file=sys.stderr)
            continue
        data      = load_yaml(yaml_sti)
        meta      = data.get("meta", {})
        html_navn = meta.get("html_navn")
        if not html_navn:
            print(f"❌ {yaml_sti}: meta.html_navn mangler — "
                  f"siden springes over; tilføj fx 'html_navn: hoejbede'",
                  file=sys.stderr)
            continue
        meta_år = meta.get("år")
        if meta_år and meta_år != AKTIVT_ÅR:
            advarsler.append(
                f"⚠️  {yaml_sti}: meta.år={meta_år} men AKTIVT_ÅR={AKTIVT_ÅR} — "
                f"opdatér meta.år eller kør: have check"
            )
        html_sti = os.path.join(OUT_MAPPE, html_navn + ".html")
        # zone-typer: 'husdyr' aktiverer alternativ template og wizard-sæt.
        # Zoner uden 'type' behandles som plantezoner (eksisterende opførsel).
        if meta.get("type") == "husdyr":
            hons_entries = generer_hons_html(yaml_sti, html_sti, env, nav_context=nav_ctx(html_navn))
            upload_filer.append((html_sti, html_navn + ".html"))
            projekter.append(projekt_info(yaml_sti))
            ics_sti = os.path.join(OUT_MAPPE, f"{html_navn}-{AKTIVT_ÅR}.ics")
            if generer_hons_ics(hons_entries, ics_sti, AKTIVT_ÅR):
                upload_filer.append((ics_sti, f"{html_navn}-{AKTIVT_ÅR}.ics"))
            continue
        generer_html(yaml_sti, html_sti, env, alle_planter, nav_context=nav_ctx(html_navn))
        upload_filer.append((html_sti, html_navn + ".html"))
        projekter.append(projekt_info(yaml_sti))

    index_sti  = os.path.join(OUT_MAPPE, "index.html")
    samlet_sti = os.path.join(OUT_MAPPE, "almanak.html")
    generer_samlet_almanak(yaml_filer, samlet_sti, env, alle_planter, nav_context=nav_ctx("almanak"))
    upload_filer.append((samlet_sti, "almanak.html"))
    projekter.append(projekt_info(ALMANAK_FIL))

    planter_sti = os.path.join(str(OUT_MAPPE.parent), "planter.html")
    generer_planter_oversigt(alle_planter, yaml_filer, planter_sti, env, nav_context=nav_ctx("planter", op_sti="", jaar_sti=f"{AKTIVT_ÅR}/"))
    upload_filer.append((planter_sti, "planter.html"))

    arkiv_samlet_sti = OUT_MAPPE.parent / "arkiv-samlet.html"
    generer_samlet_arkiv(år_liste, arkiv_samlet_sti, env, plante_db=PLANTE_DB,
                         nav_context=nav_ctx("arkiv-samlet", op_sti="", jaar_sti=f"{AKTIVT_ÅR}/"))
    upload_filer.append((str(arkiv_samlet_sti), "arkiv-samlet.html"))

    for _gl_år in år_liste:
        _stale = OUT_MAPPE.parent / str(_gl_år) / "planter.html"
        if _stale.exists():
            _stale.unlink()
            print(f"🗑  Fjernet forældet: {_stale}")
    planter_info = projekt_info(PLANTER_FIL)
    planter_info["undertitel"] = f"{len(alle_planter)} sorter med kalender og noter"
    planter_info["html_navn"] = "../planter"
    projekter.append(planter_info)

    generer_index(projekter, index_sti, env, nav_context=nav_ctx("hjem"),
                  hero_billede=_config.get("hero_billede", ""))
    upload_filer.append((index_sti, "index.html"))

    for info_yaml, info_html in [("data/om.yaml", "om.html"), ("data/kontakt.yaml", "kontakt.html")]:
        if os.path.exists(info_yaml):
            info_sti = os.path.join(str(OUT_MAPPE.parent), info_html)
            generer_info_side(info_yaml, info_sti, env, nav_context=nav_ctx("", op_sti="", jaar_sti=f"{AKTIVT_ÅR}/"))
            upload_filer.append((info_sti, info_html))
        for _gl_år in år_liste:
            _stale = OUT_MAPPE.parent / str(_gl_år) / info_html
            if _stale.exists():
                _stale.unlink()
                print(f"🗑  Fjernet forældet: {_stale}")

    søg_json_sti, søg_data = generer_søg_json(OUT_MAPPE.parent, PROJECT_ROOT / "data", PLANTE_DB)
    upload_filer.append((str(søg_json_sti), "søg.json"))
    opdater_schema_plante_ids(PLANTE_DB)

    import json as _json
    søg_html_sti = OUT_MAPPE.parent / "søg.html"
    skabelon_søg = env.get_template("søg.html")
    søg_html = skabelon_søg.render(
        år=AKTIVT_ÅR,
        søg_data_json=_json.dumps(søg_data, ensure_ascii=False, separators=(",", ":")),
        **nav_ctx("søg", op_sti="", jaar_sti=f"{AKTIVT_ÅR}/"),
    )
    if skriv_hvis_ændret(søg_html_sti, søg_html):
        print(f"✅ Søgeside genereret: {søg_html_sti}")
    else:
        print(f"ℹ️  Søgeside uændret: {søg_html_sti}")
    upload_filer.append((str(søg_html_sti), "søg.html"))

    _lokal_css = Path.cwd() / "static" / "style.css"
    css_kilde = str(_lokal_css if _lokal_css.exists() else Path(__file__).parent / "static" / "style.css")
    if os.path.exists(css_kilde):
        css_tekst = Path(css_kilde).read_text(encoding="utf-8")
        # Kopiér til årsmappe
        css_dest = os.path.join(OUT_MAPPE, "style.css")
        if skriv_hvis_ændret(css_dest, css_tekst):
            os.chmod(css_dest, 0o644)
            print(f"✅ CSS kopieret: {css_dest}")
        else:
            print(f"ℹ️  CSS uændret: {css_dest}")
        upload_filer.append((css_dest, "style.css"))
        # Kopiér til rodmappe (bruges af søg.html, planter.html, om.html m.fl.)
        css_rod = str(OUT_MAPPE.parent / "style.css")
        skriv_hvis_ændret(css_rod, css_tekst)
        os.chmod(css_rod, 0o644)

    _lokal_js = Path.cwd() / "static" / "almanak-filter.js"
    js_kilde = str(_lokal_js if _lokal_js.exists() else Path(__file__).parent / "static" / "almanak-filter.js")
    if os.path.exists(js_kilde):
        js_tekst = Path(js_kilde).read_text(encoding="utf-8")
        # Kopiér kun til årsmappe — almanak-filter.js bruges kun af almanak.html
        js_dest = os.path.join(OUT_MAPPE, "almanak-filter.js")
        if skriv_hvis_ændret(js_dest, js_tekst):
            os.chmod(js_dest, 0o644)
            print(f"✅ JS kopieret: {js_dest}")
        else:
            print(f"ℹ️  JS uændret: {js_dest}")
        upload_filer.append((js_dest, "almanak-filter.js"))

    fotos_basis = PROJECT_ROOT / "fotos"
    if fotos_basis.exists():
        # Plantefotos er tidløse — kopieres til out/fotos/planter/ (rod-niveau)
        planter_kilde = fotos_basis / "planter"
        if planter_kilde.exists():
            planter_dest = OUT_MAPPE.parent / "fotos" / "planter"
            _generer_manglende_thumbnails(planter_kilde)
            n = _sync_mappe(planter_kilde, planter_dest)
            _generer_manglende_thumbnails(planter_dest)
            if n > 0:
                print(f"✅ Plantefotos synkroniseret: {n} filer → {planter_dest}")
            else:
                print(f"ℹ️  Plantefotos uændrede: {planter_dest}")
            # Ryd stale planter-mapper i årsundermapper
            for _gl_år in år_liste:
                _stale_planter = OUT_MAPPE.parent / str(_gl_år) / "fotos" / "planter"
                if _stale_planter.exists():
                    shutil.rmtree(_stale_planter)
                    print(f"🗑  Fjernet forældet: {_stale_planter}")

        # Entryfotos er årstalsbestemte — kopieres til out/{år}/fotos/entries/
        fotos_dest = OUT_MAPPE / "fotos"
        fotos_dest.mkdir(exist_ok=True)
        entries_kilde = fotos_basis / "entries" / str(AKTIVT_ÅR)
        entries_dest  = fotos_dest / "entries"
        if entries_kilde.exists():
            if entries_dest.exists():
                shutil.rmtree(entries_dest)
            shutil.copytree(entries_kilde, entries_dest)
        else:
            entries_dest.mkdir(exist_ok=True)
        for fil in fotos_basis.iterdir():
            if fil.is_file():
                dst = fotos_dest / fil.name
                shutil.copy2(fil, dst)
                os.chmod(dst, 0o644)
        for rod, _, filer_i_rod in os.walk(fotos_dest):
            for fil in filer_i_rod:
                os.chmod(os.path.join(rod, fil), 0o644)
        print(f"✅ Årsfotos kopieret: {fotos_dest}")

    generer_redirect_index(str(OUT_MAPPE.parent), AKTIVT_ÅR)

    for _gl_år in år_liste:
        if _gl_år != AKTIVT_ÅR:
            _regenerer_gl_år_sider(
                _gl_år, år_liste, AKTIVT_ÅR,
                nav_bede, have_navn, _config.get("features", {}),
                env, alle_planter, OUT_MAPPE.parent,
            )

    if os.path.exists(ALMANAK_FIL):
        ics_sti = os.path.join(OUT_MAPPE, f"have-{AKTIVT_ÅR}.ics")
        if (not os.path.exists(ics_sti) or
                os.path.getmtime(ALMANAK_FIL) > os.path.getmtime(ics_sti)):
            generer_ics(ALMANAK_FIL, ics_sti, AKTIVT_ÅR, yaml_filer)
        else:
            print(f"ℹ️  ICS uændret (almanak.yaml ikke nyere): {ics_sti}")
        upload_filer.append((ics_sti, f"have-{AKTIVT_ÅR}.ics"))

    dagbog_rss_sti  = os.path.join(OUT_MAPPE, "have-dagbog.rss")
    almanak_rss_sti = os.path.join(OUT_MAPPE, "have-almanak.rss")
    if os.path.exists(ENTRIES_FIL):
        if (not os.path.exists(dagbog_rss_sti) or
                os.path.getmtime(ENTRIES_FIL) > os.path.getmtime(dagbog_rss_sti)):
            generer_rss_dagbog(ENTRIES_FIL, dagbog_rss_sti, AKTIVT_ÅR, BASE_URL)
        else:
            print(f"ℹ️  RSS dagbog uændret: {dagbog_rss_sti}")
        upload_filer.append((dagbog_rss_sti, "have-dagbog.rss"))
    if os.path.exists(ALMANAK_FIL):
        if (not os.path.exists(almanak_rss_sti) or
                os.path.getmtime(ALMANAK_FIL) > os.path.getmtime(almanak_rss_sti)):
            generer_rss_almanak(ALMANAK_FIL, almanak_rss_sti, AKTIVT_ÅR, BASE_URL, yaml_filer)
        else:
            print(f"ℹ️  RSS almanak uændret: {almanak_rss_sti}")
        upload_filer.append((almanak_rss_sti, "have-almanak.rss"))

    if advarsler:
        print(f"\n{'─'*40}")
        for a in advarsler:
            print(a)
        print(f"{'─'*40}")
        print(f"Kør 'have check' for fuld diagnose.\n")

    return upload_filer


def opret_entry(dato: str, zone: str, tekst: str,
                plante_id=None, foto_kilde: str = None,
                _generer: bool = True) -> str:
    """Opretter en dagbogsentry som markdown-fil. Returnerer stien til filen.

    plante_id kan være en streng (enkelt plante) eller en liste af strenge.
    """
    import shutil
    entries_mappe = os.path.join(DATA_MAPPE, "entries", "sektioner")
    os.makedirs(entries_mappe, exist_ok=True)

    basis = f"{dato}-{zone}"
    sti   = os.path.join(entries_mappe, f"{basis}.md")
    n     = 2
    while os.path.exists(sti):
        sti = os.path.join(entries_mappe, f"{basis}-{n}.md")
        n  += 1

    foto_sti = None
    if foto_kilde:
        # Gem i fotos/entries/{AKTIVT_ÅR}/ — generatoren kopierer derfra til out/
        fotos_entries_kilde = os.path.join("fotos", "entries", str(AKTIVT_ÅR))
        os.makedirs(fotos_entries_kilde, exist_ok=True)
        ext       = os.path.splitext(foto_kilde)[1]
        foto_navn = os.path.splitext(os.path.basename(sti))[0] + ext
        foto_dest = os.path.join(fotos_entries_kilde, foto_navn)
        shutil.copy2(foto_kilde, foto_dest)
        foto_sti = foto_navn  # kun filnavn — _les_entries_mappe normaliserer til dict
        try:
            from PIL import Image, ImageOps
            foto_dest_sti = Path(foto_dest)
            thumbs_mappe = foto_dest_sti.parent / "thumbs"
            thumbs_mappe.mkdir(exist_ok=True)
            with Image.open(foto_dest_sti) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((400, 400))
                ext_l = foto_dest_sti.suffix.lower()
                if ext_l in (".jpg", ".jpeg"):
                    img.save(thumbs_mappe / foto_dest_sti.name, "JPEG", quality=82, optimize=True)
                else:
                    img.save(thumbs_mappe / foto_dest_sti.name, optimize=True)
        except Exception as e:
            print(f"⚠️  Thumbnail ikke genereret: {e}")

    # Normaliser plante_id til liste
    if isinstance(plante_id, str):
        plante_ids = [plante_id] if plante_id else []
    else:
        plante_ids = [p for p in (plante_id or []) if p]

    linjer = ["---", f"dato: {dato}", f"zone: {zone}"]
    if len(plante_ids) == 1:
        linjer.append(f"plante_id: {plante_ids[0]}")
    elif len(plante_ids) > 1:
        linjer.append("plante_id:")
        for pid in plante_ids:
            linjer.append(f"  - {pid}")
    if foto_sti:
        linjer.append(f"foto: {foto_sti}")
    linjer += ["---", "", tekst]

    with open(sti, "w", encoding="utf-8") as f:
        f.write("\n".join(linjer) + "\n")

    if _generer:
        generer_alle()

    return str(sti)


def ny_entry():
    """Interaktiv wizard til at oprette en ny dagbogsentry."""
    import re as _re
    import questionary

    i_dag = datetime.date.today().isoformat()
    dato_input = questionary.text(
        "Dato:",
        default=i_dag,
        validate=lambda v: bool(_re.match(r"^\d{4}-\d{2}-\d{2}$", v))
            or f"Ugyldigt datoformat: {v!r} (forventet YYYY-MM-DD)",
    ).ask()
    if dato_input is None:
        sys.exit(0)

    dato_år = int(dato_input[:4])
    if dato_år != AKTIVT_ÅR:
        ok = questionary.confirm(
            f"⚠️  {dato_år} er ikke det aktive år ({AKTIVT_ÅR}). Vil du fortsætte?",
            default=False,
        ).ask()
        if not ok:
            sys.exit(0)

    yaml_filer = _find_yaml_filer()
    zoner = []
    for yaml_sti in yaml_filer:
        if not os.path.exists(yaml_sti):
            continue
        meta = load_yaml(yaml_sti).get("meta", {})
        html_navn = meta.get("html_navn")
        if html_navn:
            zoner.append((html_navn, meta.get("titel", html_navn)))

    zone = questionary.select(
        "Zone:",
        choices=[
            questionary.Choice(title=f"{zone_titel} ({zone_id})", value=zone_id)
            for zone_id, zone_titel in zoner
        ],
    ).ask()
    if zone is None:
        sys.exit(0)

    plante_data = load_yaml(PLANTER_FIL)
    planter = plante_data if isinstance(plante_data, list) else plante_data.get("planter", [])
    plante_choices = [
        questionary.Choice(title=f"{p.get('navn', '?')} ({p.get('id', '?')})", value=p.get("id"))
        for p in sorted(planter, key=lambda p: p.get("navn", "").lower())
    ]
    valgte_planter = questionary.checkbox(
        "Planter (valgfri — brug mellemrum til at vælge, Enter for at bekræfte):",
        choices=plante_choices,
    ).ask()
    if valgte_planter is None:
        sys.exit(0)
    plante_id = valgte_planter  # liste (evt. tom)

    tekst = (questionary.text(
        "Tekst:",
        validate=lambda v: bool(v.strip()) or "Tekst er påkrævet",
    ).ask() or "").strip()
    if not tekst:
        sys.exit(1)

    foto_input = (questionary.text("Foto (sti til fil, tast Enter for at springe over):").ask() or "").strip()
    foto_kilde = None
    if foto_input:
        if not os.path.isfile(foto_input):
            print(f"❌ Filen eksisterer ikke: {foto_input!r}")
            sys.exit(1)
        foto_kilde = foto_input

    sti = opret_entry(dato_input, zone, tekst, plante_id, foto_kilde)
    print(f"✓ Entry gemt: {sti}")


def opret_plante(plante_dict: dict) -> str:
    """Appender en ny plante til PLANTER_FIL. Returnerer plante_dict['id']."""
    pid = plante_dict["id"]
    eksisterende = byg_plante_db(PLANTER_FIL)
    if pid in eksisterende:
        print(f"❌ plante_id {pid!r} eksisterer allerede i {PLANTER_FIL.name}")
        sys.exit(1)

    # Sørg for at filen ender med newline inden append
    indhold = PLANTER_FIL.read_bytes()
    if indhold and indhold[-1:] != b"\n":
        with open(PLANTER_FIL, "ab") as f:
            f.write(b"\n")

    yaml_blok = yaml.dump(
        [plante_dict],
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    with open(PLANTER_FIL, "a", encoding="utf-8") as f:
        f.write(yaml_blok)

    return pid, yaml_blok


def ny_plante():
    """Interaktiv wizard til at oprette en ny plante i planter.yaml."""
    import re as _re
    import shutil as _shutil
    import questionary

    db = byg_plante_db(PLANTER_FIL)
    kendte_ids = set(db.keys())

    # ── Trin 0: Wikidata-søgning ───────────────────────────────────────────────
    wikidata_q_id  = None
    wikidata_label = None
    auto_latin     = None
    auto_familie   = None

    søgeterm = (questionary.text("Søg på Wikidata (fx 'spinat', Enter = spring over):").ask() or "").strip()
    if søgeterm:
        try:
            kandidater = wikidata_søg(søgeterm)
            if not kandidater:
                print("⚠️  Ingen resultater fra Wikidata — fortsætter manuelt")
            else:
                wikidata_choices = [questionary.Choice(title="Spring Wikidata over", value=None)]
                wikidata_choices += [
                    questionary.Choice(
                        title=f"{k['id']:12} {k['label']:25} {k['description'][:55]}",
                        value=k,
                    )
                    for k in kandidater
                ]
                valgt = questionary.select("Vælg Wikidata-resultat:", choices=wikidata_choices).ask()
                if valgt:
                    wikidata_q_id  = valgt["id"]
                    wikidata_label = valgt["label"]
                    print(f"  → {wikidata_q_id} valgt — henter plantedata ...")
                    try:
                        pdata = wikidata_hent_plantedata(wikidata_q_id)
                        auto_latin   = pdata.get("latin")
                        auto_familie = pdata.get("familieNavn")
                        if auto_latin:
                            print(f"  Latin:   {auto_latin}")
                        if auto_familie:
                            print(f"  Familie: {auto_familie}")
                    except Exception as e:
                        print(f"  ⚠️  Kunne ikke hente plantedata: {e}")
        except Exception as e:
            print(f"⚠️  Wikidata utilgængeligt ({e}) — fortsætter manuelt")

    print()

    # ── navn ──────────────────────────────────────────────────────────────────
    default_navn = wikidata_label or ""

    def _valider_navn(v):
        if not v.strip() and not default_navn:
            return "navn er påkrævet"
        return True

    navn = (questionary.text(
        "Navn (fx 'Spinat'):",
        default=default_navn,
        validate=_valider_navn,
    ).ask() or default_navn).strip()
    if not navn:
        sys.exit(0)

    # ── sort ──────────────────────────────────────────────────────────────────
    sort = (questionary.text("Sort/Kultivar (fx 'Matador', Enter = ingen):").ask() or "").strip() or None

    # ── id ────────────────────────────────────────────────────────────────────
    id_forslag = plante_id(navn, sort)

    def _valider_pid(v):
        v = v.strip()
        if not v:
            return "id er påkrævet"
        if not _re.match(r"^[a-z0-9-]+$", v):
            return "id må kun indeholde [a-z0-9-]"
        if v in kendte_ids:
            return f"{v!r} eksisterer allerede"
        return True

    pid = (questionary.text(
        "Plante-id:",
        default=id_forslag,
        validate=_valider_pid,
    ).ask() or "").strip()
    if not pid:
        sys.exit(0)

    # ── latin ─────────────────────────────────────────────────────────────────
    def _valider_latin(v):
        v = v.strip()
        if not v:
            return True
        if " " not in v:
            return "latinsk navn skal indeholde mindst ét mellemrum"
        return True

    latin_input = questionary.text(
        "Latin (fx 'Spinacia oleracea', Enter = ingen):",
        default=auto_latin or "",
        validate=_valider_latin,
    ).ask()
    latin = ((latin_input or "").strip() or auto_latin or None)

    # ── placering ─────────────────────────────────────────────────────────────
    placering = (questionary.text(
        "Placering (fx 'Sol', 'Halvskygge'):",
        validate=lambda v: bool(v.strip()) or "placering er påkrævet",
    ).ask() or "").strip()

    # ── farve ─────────────────────────────────────────────────────────────────
    # ── farve ─────────────────────────────────────────────────────────────────
    _FARVEFORSLAG = [
        ("#2d5a27", "Mørkegrøn     — kål, spinat, persille"),
        ("#4a7c59", "Grøn          — salat, ærter, bønner"),
        ("#8bc34a", "Lysegrøn      — agurk, courgette"),
        ("#374720", "Olivengrøn    — rosmarin, timian"),
        ("#ff6f00", "Orange        — gulerod, græskar"),
        ("#e53935", "Rød           — tomat, jordbær, rød peber"),
        ("#c2185b", "Mørkerød      — rødbede, rødkål"),
        ("#f9a825", "Gul           — gul peber, majskolbe"),
        ("#6d4c41", "Brun          — kartoffel, jordskokke"),
        ("#7b1fa2", "Lilla         — aubergine, lilla basilikum"),
        ("#ffffff", "Hvid          — blomkål, fennikel, hvidløg"),
    ]

    def _swatch(hex_kode):
        r, g, b = int(hex_kode[1:3], 16), int(hex_kode[3:5], 16), int(hex_kode[5:7], 16)
        return f"\033[48;2;{r};{g};{b}m   \033[0m"

    farve_valg = questionary.select(
        "Farve:",
        choices=[
            questionary.Choice(
                title=[("bg:" + h, "   "), ("", f"  {h}  {label}")],
                value=h,
            )
            for h, label in _FARVEFORSLAG
        ] + [questionary.Choice(title="Indtast selv …", value="__manuel__")],
    ).ask()

    if farve_valg == "__manuel__":
        farve = (questionary.text(
            "Farve hex (fx '#374720'):",
            validate=lambda v: bool(_re.match(r"^#[0-9a-fA-F]{6}$", v)) or f"ugyldig hex-farve: {v!r}",
        ).ask() or "").strip()
    else:
        farve = farve_valg

    # ── afstand / rækkeafstand ────────────────────────────────────────────────
    def _valider_afstand(v):
        v = v.strip()
        if not v:
            return True
        if _re.match(r"^\d+(-\d+)?$", v):
            return True
        return f"ugyldigt format: {v!r}"

    afstand = (questionary.text(
        "Planteafstand cm (fx '30' eller '12-15', Enter = ingen):",
        validate=_valider_afstand,
    ).ask() or "").strip() or None

    rækkeafstand = (questionary.text(
        "Rækkeafstand cm (fx '25-30', Enter = ingen):",
        validate=_valider_afstand,
    ).ask() or "").strip() or None

    # ── sådybde ───────────────────────────────────────────────────────────────
    def _valider_sådybde(v):
        v = v.strip()
        if not v:
            return True
        try:
            n = int(v)
            if n > 0:
                return True
            return "sådybde skal være et positivt heltal"
        except ValueError:
            return f"ugyldigt heltal: {v!r}"

    sådybde_str = (questionary.text(
        "Sådybde cm (fx '1', Enter = ingen):",
        validate=_valider_sådybde,
    ).ask() or "").strip()
    sådybde = int(sådybde_str) if sådybde_str else None

    # ── høst_fra / høst_til ───────────────────────────────────────────────────
    def _valider_måned(v):
        v = v.strip()
        if not v:
            return True
        try:
            m = int(v)
            if 1 <= m <= 12:
                return True
            return "skal være 1–12"
        except ValueError:
            return f"ugyldigt heltal: {v!r}"

    def spørg_måned(prompt, default: int | None = None):
        default_str = str(default) if default else ""
        suffix = f"1-12, Enter = {default}" if default else "1-12, Enter = ingen"
        val = (questionary.text(f"{prompt} ({suffix}):", default=default_str, validate=_valider_måned).ask() or "").strip()
        return int(val) if val else None

    while True:
        høst_fra = spørg_måned("Høst fra måned", default=7)
        høst_til = spørg_måned("Høst til måned", default=9)
        if høst_fra and høst_til and høst_fra > høst_til:
            if høst_fra > 6 and høst_til < 6:
                print(f"  (wrap-around antaget: {høst_fra}–{høst_til}, fx oktober–marts)")
            else:
                print(f"⚠️  høst_fra={høst_fra} > høst_til={høst_til} — er det korrekt?")
                if not questionary.confirm("Fortsæt alligevel?", default=False).ask():
                    continue
        break

    # ── indendørs / udplantning / direkte ─────────────────────────────────────
    indendørs   = spørg_måned("Forspiring indendørs måned", default=3)
    udplantning = spørg_måned("Udplantning måned", default=5)
    direkte     = spørg_måned("Direkte såning måned", default=4)

    # ── noter ─────────────────────────────────────────────────────────────────
    noter = (questionary.text("Noter (Enter = ingen):").ask() or "").strip() or None

    # ── pasning ───────────────────────────────────────────────────────────────
    pasning = (questionary.text("Pasning (Enter = ingen):").ask() or "").strip() or None

    # ── foto ──────────────────────────────────────────────────────────────────
    foto = None

    if wikidata_q_id:
        try:
            p18_url = wikidata_hent_foto_url(wikidata_q_id)
            if p18_url:
                foto_meta = wikidata_hent_foto_metadata(p18_url)
                ext = Path(p18_url.rsplit("/", 1)[-1]).suffix.lower() or ".jpg"
                fil_forslag = f"{pid}{ext}"
                print(f"\n  Foto fundet på Wikidata (P18):")
                print(f"    Fil:       {fil_forslag}")
                print(f"    Kilde:     {foto_meta.get('url') or p18_url}")
                print(f"    Licens:    {foto_meta.get('licens') or '?'}")
                print(f"    Forfatter: {foto_meta.get('forfatter') or '?'}")
                if questionary.confirm("  Download og gem?", default=True).ask():
                    import urllib.request as _ur, shutil as _sh
                    fotos_mappe = sti(_config, "fotos") / "planter"
                    fotos_mappe.mkdir(exist_ok=True)
                    dest = fotos_mappe / fil_forslag
                    req = _ur.Request(p18_url, headers={"User-Agent": "have.py/1.0"})
                    with _ur.urlopen(req, timeout=15) as r:
                        with open(dest, "wb") as f:
                            _sh.copyfileobj(r, f)
                    print(f"  💾 Gemt: {dest.name}")
                    foto = {"fil": dest.name}
                    if foto_meta.get("url"):
                        foto["kilde"] = foto_meta["url"]
                    if foto_meta.get("licens"):
                        foto["licens"] = foto_meta["licens"]
                    if foto_meta.get("forfatter"):
                        foto["forfatter"] = foto_meta["forfatter"]
        except Exception as e:
            print(f"  ⚠️  Kunne ikke hente P18-foto: {e}")

    if foto is None:
        foto_valg = questionary.select(
            "Foto:",
            choices=[
                questionary.Choice(title="Placeholder (sættes ind nu, rettes senere)", value="1"),
                questionary.Choice(title="Eget foto", value="2"),
                questionary.Choice(title="Fra nettet (Wikimedia el.lign.)", value="3"),
            ],
        ).ask()

        if foto_valg == "1":
            foto = {"fil": "placeholder.jpg", "licens": "placeholder", "forfatter": "-"}
        elif foto_valg == "2":
            fil = (questionary.text(
                "Filnavn (fx 'spinat.jpg'):",
                validate=lambda v: bool(v.strip()) or "filnavn er påkrævet",
            ).ask() or "").strip()
            default_forfatter = os.getenv("USER", "")
            forfatter = (questionary.text("Forfatter:", default=default_forfatter).ask() or default_forfatter).strip()
            foto = {"fil": fil, "licens": "eget værk", "forfatter": forfatter}
        elif foto_valg == "3":
            fil = (questionary.text(
                "Filnavn (fx 'spinat.jpg'):",
                validate=lambda v: bool(v.strip()) or "filnavn er påkrævet",
            ).ask() or "").strip()
            kilde = (questionary.text(
                "Kilde-URL:",
                validate=lambda v: bool(v.strip()) or "kilde er påkrævet",
            ).ask() or "").strip()
            licens = (questionary.text(
                "Licens (fx 'CC BY-SA 4.0'):",
                validate=lambda v: bool(v.strip()) or "licens er påkrævet",
            ).ask() or "").strip()
            forfatter = (questionary.text(
                "Forfatter:",
                validate=lambda v: bool(v.strip()) or "forfatter er påkrævet",
            ).ask() or "").strip()
            foto = {"fil": fil, "kilde": kilde, "licens": licens, "forfatter": forfatter}
        else:
            print(f"❌ Ugyldigt valg: {foto_valg!r}")
            sys.exit(1)

    # ── Byg plante-dict i YAML-feltrækkefølge ─────────────────────────────────
    plante = {"id": pid, "navn": navn}
    if sort:
        plante["sort"] = sort
    if latin:
        plante["latin"] = latin
    if auto_familie:
        plante["familie"] = auto_familie
    if wikidata_q_id:
        plante["wikidata"] = wikidata_q_id
    plante["farve"] = farve
    plante["placering"] = placering
    if afstand:
        plante["afstand"] = int(afstand) if afstand.isdigit() else afstand
    if rækkeafstand:
        plante["rækkeafstand"] = int(rækkeafstand) if rækkeafstand.isdigit() else rækkeafstand
    if sådybde is not None:
        plante["sådybde"] = sådybde
    if indendørs:
        plante["indendørs"] = indendørs
    if udplantning:
        plante["udplantning"] = udplantning
    if direkte:
        plante["direkte"] = direkte
    if høst_fra:
        plante["høst_fra"] = høst_fra
    if høst_til:
        plante["høst_til"] = høst_til
    if noter:
        plante["noter"] = noter
    if pasning:
        plante["pasning"] = pasning
    plante["foto"] = foto

    gem_pid, yaml_blok = opret_plante(plante)
    print(f"\n✓ Plante gemt: {gem_pid}")
    print(f"  Fil: {PLANTER_FIL}\n")
    print("─" * 40)
    print(yaml_blok.rstrip())
    print("─" * 40)
    print("\n  Redigér planter.yaml direkte for at justere værdierne.")
    print("  Kør 'have' for at opdatere sitet, eller 'have check' for at validere.")


def ret_i_plante_yaml():
    """Interaktiv wizard til at redigere en eksisterende plante i planter.yaml."""
    import io as _io
    import re as _re
    import questionary
    from ruamel.yaml import YAML as RuamelYAML

    ry = RuamelYAML()
    ry.preserve_quotes = True
    ry.default_flow_style = False
    ry.width = 120

    # ── 1. Søg og vælg plante ─────────────────────────────────────────────────
    db = byg_plante_db(PLANTER_FIL)
    if not db:
        print(f"❌ Ingen planter fundet i {PLANTER_FIL}")
        sys.exit(1)

    valgt_plante = None
    while valgt_plante is None:
        søg = questionary.text("Søg efter plante (navn, sort eller id):").ask()
        if søg is None:
            sys.exit(0)
        hits = _søg_planter(søg, db)
        if not hits:
            print(f"  Ingen planter matcher '{søg}'. Prøv igen.")
            continue
        if len(hits) == 1:
            valgt_plante = hits[0]
        else:
            valgt = questionary.select(
                "Vælg plante:",
                choices=[questionary.Choice(title=_plante_label(p), value=p) for p in hits],
            ).ask()
            if valgt is None:
                sys.exit(0)
            valgt_plante = valgt

    pid = valgt_plante["id"]
    print(f"\n  Redigerer: {_plante_label(valgt_plante)}\n")

    # ── 2. Vælg felter der skal rettes ────────────────────────────────────────
    ALLE_FELTER = [
        ("navn",         "Navn"),
        ("sort",         "Sort/Kultivar"),
        ("latin",        "Latinsk navn"),
        ("familie",      "Familie"),
        ("farve",        "Farve"),
        ("placering",    "Placering"),
        ("afstand",      "Planteafstand"),
        ("rækkeafstand", "Rækkeafstand"),
        ("sådybde",      "Sådybde"),
        ("indendørs",    "Forspiring indendørs"),
        ("udplantning",  "Udplantning"),
        ("direkte",      "Direkte såning"),
        ("høst_fra",     "Høst fra"),
        ("høst_til",     "Høst til"),
        ("noter",        "Noter"),
        ("pasning",      "Pasning"),
        ("foto",         "Foto"),
    ]

    def _felt_label(felt, label):
        v = valgt_plante.get(felt)
        if felt == "foto" and isinstance(v, dict):
            return f"{label}  [{v.get('fil', '?')}]"
        if v is not None:
            return f"{label}  [{v}]"
        return f"{label}  (ikke sat)"

    valgte_felter = questionary.checkbox(
        "Hvilke felter vil du rette? (mellemrum = vælg, Enter = bekræft):",
        choices=[
            questionary.Choice(title=_felt_label(felt, label), value=felt)
            for felt, label in ALLE_FELTER
        ],
    ).ask()

    if not valgte_felter:
        print("Ingen felter valgt — afbrudt.")
        sys.exit(0)

    print()

    # ── 3. Rediger hvert felt ─────────────────────────────────────────────────
    ændringer: dict = {}

    def _valider_måned_opt(v):
        v = v.strip()
        if not v:
            return True
        try:
            m = int(v)
            if 1 <= m <= 12:
                return True
            return "skal være 1–12"
        except ValueError:
            return f"ugyldigt heltal: {v!r}"

    def _valider_afstand(v):
        v = v.strip()
        if not v:
            return True
        if _re.match(r"^\d+(-\d+)?$", v):
            return True
        return f"ugyldigt format: {v!r}"

    for felt in valgte_felter:
        nuværende = valgt_plante.get(felt)

        if felt == "navn":
            ny_val = (questionary.text(
                "Navn:",
                default=str(nuværende or ""),
                validate=lambda v: bool(v.strip()) or "navn er påkrævet",
            ).ask() or "").strip()
            if ny_val:
                ændringer["navn"] = ny_val

        elif felt == "sort":
            ny_val = (questionary.text(
                "Sort/Kultivar (Enter = fjern):",
                default=str(nuværende or ""),
            ).ask() or "").strip()
            ændringer["sort"] = ny_val or None

        elif felt == "latin":
            def _valider_latin_ret(v):
                v = v.strip()
                if not v or " " in v:
                    return True
                return "latinsk navn skal indeholde mindst ét mellemrum"

            ny_val = (questionary.text(
                "Latin (Enter = fjern):",
                default=str(nuværende or ""),
                validate=_valider_latin_ret,
            ).ask() or "").strip()
            ændringer["latin"] = ny_val or None

        elif felt == "familie":
            ny_val = (questionary.text(
                "Familie (Enter = fjern):",
                default=str(nuværende or ""),
            ).ask() or "").strip()
            ændringer["familie"] = ny_val or None

        elif felt == "farve":
            _FARVEFORSLAG = [
                ("#2d5a27", "Mørkegrøn     — kål, spinat, persille"),
                ("#4a7c59", "Grøn          — salat, ærter, bønner"),
                ("#8bc34a", "Lysegrøn      — agurk, courgette"),
                ("#374720", "Olivengrøn    — rosmarin, timian"),
                ("#ff6f00", "Orange        — gulerod, græskar"),
                ("#e53935", "Rød           — tomat, jordbær, rød peber"),
                ("#c2185b", "Mørkerød      — rødbede, rødkål"),
                ("#f9a825", "Gul           — gul peber, majskolbe"),
                ("#6d4c41", "Brun          — kartoffel, jordskokke"),
                ("#7b1fa2", "Lilla         — aubergine, lilla basilikum"),
                ("#ffffff", "Hvid          — blomkål, fennikel, hvidløg"),
            ]
            kendte_hex = {h for h, _ in _FARVEFORSLAG}
            farve_valg = questionary.select(
                "Farve:",
                choices=[
                    questionary.Choice(
                        title=[("bg:" + h, "   "), ("", f"  {h}  {label}")],
                        value=h,
                    )
                    for h, label in _FARVEFORSLAG
                ] + [questionary.Choice(title="Indtast selv …", value="__manuel__")],
                default=nuværende if nuværende in kendte_hex else None,
            ).ask()
            if farve_valg == "__manuel__":
                farve = (questionary.text(
                    "Farve hex (fx '#374720'):",
                    default=str(nuværende or ""),
                    validate=lambda v: bool(_re.match(r"^#[0-9a-fA-F]{6}$", v)) or f"ugyldig hex-farve: {v!r}",
                ).ask() or "").strip()
            else:
                farve = farve_valg
            if farve:
                ændringer["farve"] = farve

        elif felt == "placering":
            ny_val = (questionary.text(
                "Placering:",
                default=str(nuværende or ""),
                validate=lambda v: bool(v.strip()) or "placering er påkrævet",
            ).ask() or "").strip()
            if ny_val:
                ændringer["placering"] = ny_val

        elif felt == "afstand":
            ny_val = (questionary.text(
                "Planteafstand cm (fx '30' eller '12-15', Enter = fjern):",
                default=str(nuværende or ""),
                validate=_valider_afstand,
            ).ask() or "").strip()
            ændringer["afstand"] = (int(ny_val) if ny_val.isdigit() else ny_val) if ny_val else None

        elif felt == "rækkeafstand":
            ny_val = (questionary.text(
                "Rækkeafstand cm (fx '25-30', Enter = fjern):",
                default=str(nuværende or ""),
                validate=_valider_afstand,
            ).ask() or "").strip()
            ændringer["rækkeafstand"] = (int(ny_val) if ny_val.isdigit() else ny_val) if ny_val else None

        elif felt == "sådybde":
            def _valider_sådybde_ret(v):
                v = v.strip()
                if not v:
                    return True
                try:
                    n = int(v)
                    return True if n > 0 else "sådybde skal være et positivt heltal"
                except ValueError:
                    return f"ugyldigt heltal: {v!r}"

            ny_val = (questionary.text(
                "Sådybde cm (fx '1', Enter = fjern):",
                default=str(nuværende or ""),
                validate=_valider_sådybde_ret,
            ).ask() or "").strip()
            ændringer["sådybde"] = int(ny_val) if ny_val else None

        elif felt == "indendørs":
            ny_val = (questionary.text(
                "Forspiring indendørs måned (1-12, Enter = fjern):",
                default=str(nuværende or ""),
                validate=_valider_måned_opt,
            ).ask() or "").strip()
            ændringer["indendørs"] = int(ny_val) if ny_val else None

        elif felt == "udplantning":
            ny_val = (questionary.text(
                "Udplantning måned (1-12, Enter = fjern):",
                default=str(nuværende or ""),
                validate=_valider_måned_opt,
            ).ask() or "").strip()
            ændringer["udplantning"] = int(ny_val) if ny_val else None

        elif felt == "direkte":
            ny_val = (questionary.text(
                "Direkte såning måned (1-12, Enter = fjern):",
                default=str(nuværende or ""),
                validate=_valider_måned_opt,
            ).ask() or "").strip()
            ændringer["direkte"] = int(ny_val) if ny_val else None

        elif felt == "høst_fra":
            ny_val = (questionary.text(
                "Høst fra måned (1-12, Enter = fjern):",
                default=str(nuværende or ""),
                validate=_valider_måned_opt,
            ).ask() or "").strip()
            ændringer["høst_fra"] = int(ny_val) if ny_val else None

        elif felt == "høst_til":
            ny_val = (questionary.text(
                "Høst til måned (1-12, Enter = fjern):",
                default=str(nuværende or ""),
                validate=_valider_måned_opt,
            ).ask() or "").strip()
            ændringer["høst_til"] = int(ny_val) if ny_val else None

        elif felt == "noter":
            ny_val = (questionary.text(
                "Noter (Enter = fjern):",
                default=str(nuværende or ""),
            ).ask() or "").strip()
            ændringer["noter"] = ny_val or None

        elif felt == "pasning":
            ny_val = (questionary.text(
                "Pasning (Enter = fjern):",
                default=str(nuværende or ""),
            ).ask() or "").strip()
            ændringer["pasning"] = ny_val or None

        elif felt == "foto":
            nuværende_foto = nuværende if isinstance(nuværende, dict) else {}
            print("  Redigerer foto-felter:")
            foto_fil = (questionary.text(
                "  Filnavn:",
                default=nuværende_foto.get("fil", ""),
            ).ask() or "").strip()
            foto_kilde = (questionary.text(
                "  Kilde-URL (Enter = fjern):",
                default=nuværende_foto.get("kilde", ""),
            ).ask() or "").strip()
            foto_licens = (questionary.text(
                "  Licens:",
                default=nuværende_foto.get("licens", ""),
            ).ask() or "").strip()
            foto_forfatter = (questionary.text(
                "  Forfatter:",
                default=nuværende_foto.get("forfatter", ""),
            ).ask() or "").strip()
            nyt_foto: dict = {}
            if foto_fil:
                nyt_foto["fil"] = foto_fil
            if foto_kilde:
                nyt_foto["kilde"] = foto_kilde
            if foto_licens:
                nyt_foto["licens"] = foto_licens
            if foto_forfatter:
                nyt_foto["forfatter"] = foto_forfatter
            if nyt_foto:
                ændringer["foto"] = nyt_foto

    if not ændringer:
        print("Ingen ændringer — afbrudt.")
        sys.exit(0)

    # ── 4. Skriv tilbage med ruamel.yaml (bevarer struktur) ───────────────────
    with open(PLANTER_FIL, encoding="utf-8") as fh:
        rå_data = ry.load(fh)

    planter = rå_data if isinstance(rå_data, list) else rå_data.get("planter", [])
    plante_post = next((p for p in planter if p.get("id") == pid), None)
    if plante_post is None:
        print(f"❌ Kunne ikke finde plante {pid!r} i {PLANTER_FIL.name} — afbrudt.")
        sys.exit(1)

    for felt, ny_val in ændringer.items():
        if ny_val is None:
            plante_post.pop(felt, None)
        else:
            plante_post[felt] = ny_val

    buf = _io.StringIO()
    ry.dump(rå_data, buf)
    PLANTER_FIL.write_text(buf.getvalue(), encoding="utf-8")

    opdateret_navn = ændringer.get("navn") or valgt_plante.get("navn", pid)
    opdateret_sort = ændringer.get("sort") or valgt_plante.get("sort")
    label = f"{opdateret_navn} – {opdateret_sort} [{pid}]" if opdateret_sort else f"{opdateret_navn} [{pid}]"
    print(f"\n✓ {label} opdateret i {PLANTER_FIL.name}")
    print("  Kør 'have' for at opdatere sitet, eller 'have check' for at validere.")


def opdater_schema_plante_ids(plante_db: dict) -> None:
    """Skriv alle kendte plante_id'er som enum ind i bed.schema.json."""
    import json
    schema_sti = PROJECT_ROOT / "schema" / "bed.schema.json"
    if not schema_sti.exists():
        return
    schema = json.loads(schema_sti.read_text(encoding="utf-8"))
    ids = sorted(plante_db.keys())
    enum_felt = ids + [None]
    for def_navn in ("Zone", "Afgrøde"):
        felt = schema.get("$defs", {}).get(def_navn, {}).get("properties", {}).get("plante_id")
        if felt is not None:
            felt["enum"] = enum_felt
    ny = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    if skriv_hvis_ændret(schema_sti, ny):
        print(f"✅ Schema opdateret med {len(ids)} plante-ID'er: {schema_sti.name}")
    else:
        print(f"ℹ️  Schema uændret: {schema_sti.name}")


def opdater_schema_planter() -> None:
    """Regenerer planter.schema.json fra Plante-modellen."""
    import json
    from haven.models import Plante
    schema_sti = PROJECT_ROOT / "schema" / "planter.schema.json"
    if not schema_sti.exists():
        return
    ny = json.dumps(Plante.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    if skriv_hvis_ændret(schema_sti, ny):
        print(f"✅ Schema regenereret fra Plante-modellen: {schema_sti.name}")
    else:
        print(f"ℹ️  Schema uændret: {schema_sti.name}")


def generer_søg_json(out_rod: Path, data_rod: Path, plante_db: dict) -> Path:
    """Generer søg.json med alle entries på tværs af år. Returnerer stien til filen."""
    import json
    import re as _re

    søg_data = []

    for år_mappe in sorted(data_rod.iterdir()):
        if not år_mappe.is_dir() or not år_mappe.name.isdigit():
            continue
        år = int(år_mappe.name)

        # Byg zone_id → titel mapping fra YAML-filer i årets mappe
        zone_titler: dict[str, str] = {}
        for yaml_fil in sorted(år_mappe.glob("*.yaml")):
            if yaml_fil.name in {"almanak.yaml", "entries.yaml"}:
                continue
            try:
                d = load_yaml(str(yaml_fil))
                meta = d.get("meta", {}) if isinstance(d, dict) else {}
                hn = meta.get("html_navn")
                if hn:
                    zone_titler[hn] = meta.get("titel", hn)
            except Exception:
                pass

        # Entries fra markdown-filer
        entries_mappe = år_mappe / "entries"
        råentries: list[tuple[str, dict, str]] = []
        if entries_mappe.is_dir():
            for fil in sorted(entries_mappe.iterdir()):
                if fil.suffix != ".md":
                    continue
                try:
                    indhold = fil.read_text(encoding="utf-8")
                    m = _re.match(r"^---\n(.*?)\n---\n(.*)$", indhold, _re.DOTALL)
                    if not m:
                        continue
                    fm = yaml.safe_load(m.group(1))
                    if not isinstance(fm, dict):
                        continue
                    råentries.append((fil.stem, fm, m.group(2).strip()))
                except Exception:
                    pass

        # Entries fra entries.yaml (legacy / supplement)
        entries_yaml = år_mappe / "entries.yaml"
        if entries_yaml.exists():
            try:
                yd = load_yaml(str(entries_yaml))
                for e in (yd.get("entries") or []):
                    dato = e.get("dato")
                    if not dato:
                        continue
                    dato_str = dato.isoformat() if hasattr(dato, "isoformat") else str(dato)
                    zone = e.get("zone") or e.get("område_id", "")
                    stem = f"{dato_str}-{zone}"
                    råentries.append((stem, e, str(e.get("tekst", "")).strip()))
            except Exception:
                pass

        for fil_stem, fm, tekst in råentries:
            dato = fm.get("dato")
            if not dato:
                continue
            dato_str = dato.isoformat() if hasattr(dato, "isoformat") else str(dato)
            zone = fm.get("zone") or fm.get("område_id", "")
            # Normaliser plante_id: string eller liste → altid liste
            råpid = fm.get("plante_id")
            if råpid is None:
                plante_ids = []
            elif isinstance(råpid, str):
                plante_ids = [råpid] if råpid else []
            else:
                plante_ids = list(råpid)

            # Byg kommasepareret navneliste til søgeindeks
            navne_dele = []
            for pid in plante_ids:
                p = plante_db.get(pid, {})
                if p:
                    n = p.get("navn", "")
                    s = p.get("sort", "")
                    navne_dele.append(f"{n} – {s}" if s else n)
            navn = ", ".join(navne_dele) if navne_dele else None

            bed_titel = zone_titler.get(zone, zone)
            søg_data.append({
                "type":      "entry",
                "år":        år,
                "dato":      dato_str,
                "bed":       zone,
                "bed_titel": bed_titel,
                "plante_id": plante_ids if len(plante_ids) != 1 else plante_ids[0],
                "navn":      navn,
                "tekst":     tekst,
                "link":      f"{år}/almanak.html#{fil_stem}",
            })

        # ── Bedeplaner ────────────────────────────────────────────────────────────
        # (zone_html_navn, plante_id) → {bed_titel, bed_navne: set}
        SPRING = {"almanak.yaml", "entries.yaml"}
        bedeplaner: dict[tuple[str, str], dict] = {}
        for yaml_fil in sorted(år_mappe.glob("*.yaml")):
            if yaml_fil.name in SPRING:
                continue
            try:
                d = load_bed_yaml(str(yaml_fil))
                if not isinstance(d, dict):
                    continue
                meta = d.get("meta", {})
                html_navn = meta.get("html_navn")
                bed_titel = meta.get("titel", "")
                if not html_navn:
                    continue
                for bed in d.get("bede", []):
                    bed_navn = bed.get("navn") or bed.get("id", "")
                    for zone in bed.get("zoner", []):
                        pids: set[str] = {
                            afg["plante_id"]
                            for afg in zone.get("afgrøder", [])
                            if afg.get("plante_id")
                        }
                        for pid in pids:
                            key = (html_navn, pid)
                            if key not in bedeplaner:
                                bedeplaner[key] = {"bed_titel": bed_titel, "bed_navne": set()}
                            bedeplaner[key]["bed_navne"].add(bed_navn)
            except Exception:
                pass

        for (html_navn, plante_id), info in sorted(bedeplaner.items()):
            plante = plante_db.get(plante_id, {})
            navn = plante.get("navn", plante_id)
            sort = plante.get("sort", "")
            if sort:
                navn = f"{navn} – {sort}"
            bed_navne_str = ", ".join(sorted(info["bed_navne"]))
            søg_data.append({
                "type":      "bedeplan",
                "år":        år,
                "dato":      None,
                "bed":       html_navn,
                "bed_titel": info["bed_titel"],
                "plante_id": plante_id,
                "navn":      navn,
                "tekst":     bed_navne_str,
                "link":      f"{år}/{html_navn}.html#bedoversigt",
            })

    # ── Planter fra planter.yaml ─────────────────────────────────────────────
    planter_del = []
    for pid, p in sorted(plante_db.items()):
        navn = p.get("navn", pid)
        sort = p.get("sort", "")
        if sort:
            navn = f"{navn} – {sort}"
        dele = [navn]
        if p.get("latin"):
            dele.append(p["latin"])
        if p.get("familie"):
            dele.append(p["familie"])
        planter_del.append({
            "type":   "plante",
            "navn":   navn,
            "latin":  p.get("latin") or "",
            "familie": p.get("familie") or "",
            "tekst":  " · ".join(filter(None, [p.get("latin"), p.get("familie")])),
            "link":   f"planter.html#plante-{pid}",
        })
    planter_del.sort(key=lambda e: e["navn"].lower())

    entries_del  = [e for e in søg_data if e["type"] == "entry"]
    bedeplaner_del = [e for e in søg_data if e["type"] == "bedeplan"]
    entries_del.sort(key=lambda e: e["dato"], reverse=True)
    bedeplaner_del.sort(key=lambda e: (-e["år"], e["bed"], e.get("navn", "")))
    søg_data = entries_del + bedeplaner_del + planter_del
    ud_sti = out_rod / "søg.json"
    ny = json.dumps(søg_data, ensure_ascii=False, separators=(",", ":"))
    if skriv_hvis_ændret(ud_sti, ny):
        print(f"✅ Søgeindeks genereret: {ud_sti} ({len(søg_data)} entries)")
    else:
        print(f"ℹ️  Søgeindeks uændret: {ud_sti}")
    return ud_sti, søg_data


def _søg_planter(søg: str, db: dict, maks: int = 8) -> list[dict]:
    """Returnér op til `maks` planter hvis navn/sort/id matcher `søg` (case-insensitiv)."""
    søg_l = søg.lower()
    resultater = []
    for pid, p in db.items():
        felt = " ".join(filter(None, [
            str(p.get("navn", "")),
            str(p.get("sort", "")),
            pid,
        ])).lower()
        if søg_l in felt:
            resultater.append(p)
    resultater.sort(key=lambda p: p.get("navn", "").lower())
    return resultater[:maks]


def _plante_label(p: dict) -> str:
    navn = p.get("navn", p.get("id", "?"))
    sort = p.get("sort", "")
    pid  = p.get("id", "")
    if sort:
        return f"{navn} – {sort} [{pid}]"
    return f"{navn} [{pid}]"


def nyt_bed():
    """Interaktiv wizard til at oprette et nyt bed i en eksisterende zone-YAML-fil."""
    import questionary
    from ruamel.yaml import YAML as RuamelYAML

    ry = RuamelYAML()
    ry.preserve_quotes = True
    ry.default_flow_style = False
    ry.width = 120

    plante_db = byg_plante_db()

    # ── 1. Vælg zone-YAML-fil ──────────────────────────────────────────────────
    yaml_filer = sorted(
        f for f in os.listdir(DATA_MAPPE)
        if f.endswith(".yaml") and f not in {"almanak.yaml", "entries.yaml"}
    )
    if not yaml_filer:
        print(f"❌ Ingen zone-YAML-filer fundet i {DATA_MAPPE}/")
        sys.exit(1)

    valgt_fil = questionary.select(
        "Hvilken zone-fil skal bedet tilføjes til?",
        choices=yaml_filer,
    ).ask()
    if not valgt_fil:
        sys.exit(0)

    yaml_sti = DATA_MAPPE / valgt_fil
    with open(yaml_sti, encoding="utf-8") as f:
        zone_data = ry.load(f)

    eksisterende_ids = {b.get("id", "") for b in zone_data.get("bede", [])}

    print(f"\nTilføjer bed til {valgt_fil}\n")

    # ── 2. Stamoplysninger ─────────────────────────────────────────────────────
    while True:
        bed_id = questionary.text("Bed-id (url-venlig streng, fx 'bed-5'):").ask()
        if not bed_id:
            sys.exit(0)
        bed_id = bed_id.strip()
        if bed_id in eksisterende_ids:
            print(f"  ❌ '{bed_id}' findes allerede i {valgt_fil}. Vælg et andet id.")
        else:
            break

    bed_navn = questionary.text("Navn (vises over bedtegningen):").ask()
    if not bed_navn:
        sys.exit(0)

    bredde_str = questionary.text("Bredde i cm:", default="120").ask()
    dybde_str  = questionary.text("Dybde i cm:",  default="80").ask()
    farve      = questionary.text("Baggrundsfarve (hex, fx #d4edda):", default="#d4edda").ask()
    noter      = questionary.text("Noter (kan være tom):").ask()

    try:
        bredde_cm = int(bredde_str or 120)
        dybde_cm  = int(dybde_str  or 80)
    except ValueError:
        print("❌ Bredde og dybde skal være heltal.")
        sys.exit(1)

    # ── 3. Zoner ───────────────────────────────────────────────────────────────
    zoner = []
    print("\nTilføj zoner (tryk Enter uden navn for at afslutte)\n")

    while True:
        zone_navn = questionary.text(f"Zone {len(zoner) + 1} navn (Enter for at stoppe):").ask()
        if not zone_navn:
            if not zoner:
                print("  ❌ Bedet skal have mindst én zone.")
                continue
            break

        zone_bredde_str = questionary.text("  Relativ bredde (fx 0.5):", default="0.5").ask()
        try:
            zone_bredde = float(zone_bredde_str or 0.5)
        except ValueError:
            zone_bredde = 0.5

        zone_type = questionary.select(
            "  Zonetype:",
            choices=["Simpel (én plante_id)", "Sædskifte (afgrøder med måneder)"],
        ).ask()

        if zone_type and zone_type.startswith("Simpel"):
            while True:
                søg = questionary.text("  Søg plante (navn/sort/id):").ask()
                if not søg:
                    print("  ❌ Zone kræver en plante.")
                    continue
                hits = _søg_planter(søg, plante_db)
                if not hits:
                    print(f"  Ingen planter matcher '{søg}'. Prøv igen.")
                    continue
                if len(hits) == 1:
                    valgt_plante = hits[0]
                else:
                    labels = [_plante_label(p) for p in hits]
                    valgt_label = questionary.select("  Vælg plante:", choices=labels).ask()
                    if not valgt_label:
                        continue
                    valgt_plante = hits[labels.index(valgt_label)]
                break

            antal_str = questionary.text("  Antal planter (kan være tom):").ask()
            note_zone = questionary.text("  Kort note (kan være tom):").ask()

            zone = {"navn": zone_navn, "bredde": zone_bredde, "plante_id": valgt_plante["id"]}
            if antal_str and antal_str.strip().isdigit():
                zone["antal"] = int(antal_str.strip())
            if note_zone and note_zone.strip():
                zone["note"] = note_zone.strip()
        else:
            # Sædskifte
            afgrøder = []
            print("  Tilføj afgrøder (Enter uden plante for at afslutte)")
            while True:
                søg = questionary.text(f"    Afgrøde {len(afgrøder) + 1} (Enter for at stoppe):").ask()
                if not søg:
                    if not afgrøder:
                        print("    ❌ Sædskiftezone kræver mindst én afgrøde.")
                        continue
                    break
                hits = _søg_planter(søg, plante_db)
                if not hits:
                    print(f"    Ingen planter matcher '{søg}'. Prøv igen.")
                    continue
                if len(hits) == 1:
                    valgt_plante = hits[0]
                else:
                    labels = [_plante_label(p) for p in hits]
                    valgt_label = questionary.select("    Vælg plante:", choices=labels).ask()
                    if not valgt_label:
                        continue
                    valgt_plante = hits[labels.index(valgt_label)]

                fra_str = questionary.text("    Fra måned (1-12):").ask()
                til_str = questionary.text("    Til måned (1-12):").ask()
                try:
                    fra = int(fra_str or 0)
                    til = int(til_str or 0)
                except ValueError:
                    fra, til = 0, 0

                afgrøder.append({"plante_id": valgt_plante["id"], "fra": fra, "til": til})
                print(f"    ✓ {_plante_label(valgt_plante)} ({fra}–{til})")

            zone = {"navn": zone_navn, "bredde": zone_bredde, "afgrøder": afgrøder}

        zoner.append(zone)
        if 'plante_id' in zone:
            print(f"  ✓ Zone '{zone_navn}' tilføjet ({zone['plante_id']})")
        else:
            print(f"  ✓ Zone '{zone_navn}' tilføjet (sædskifte)")

    # ── 4. Byg bed-dict og vis YAML-preview ────────────────────────────────────
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    def _cm(**kwargs):
        m = CommentedMap()
        for k, v in kwargs.items():
            if v is not None:
                m[k] = v
        return m

    nyt_bed_data = _cm(
        id=bed_id,
        navn=bed_navn,
        bredde_cm=bredde_cm,
        dybde_cm=dybde_cm,
        farve=farve or "#d4edda",
    )
    if noter and noter.strip():
        nyt_bed_data["noter"] = noter.strip()

    zone_seq = CommentedSeq()
    for z in zoner:
        zm = CommentedMap()
        zm["navn"]   = z["navn"]
        zm["bredde"] = z["bredde"]
        if "plante_id" in z:
            zm["plante_id"] = z["plante_id"]
            if "antal" in z:
                zm["antal"] = z["antal"]
            if "note" in z:
                zm["note"] = z["note"]
        else:
            afg_seq = CommentedSeq()
            for a in z["afgrøder"]:
                am = CommentedMap()
                am["plante_id"] = a["plante_id"]
                am["fra"]       = a["fra"]
                am["til"]       = a["til"]
                afg_seq.append(am)
            zm["afgrøder"] = afg_seq
        zone_seq.append(zm)
    nyt_bed_data["zoner"] = zone_seq

    import io
    buf = io.StringIO()
    ry.dump({"__bed__": [nyt_bed_data]}, buf)
    preview_yaml = buf.getvalue()
    # Strip the wrapper key
    lines = preview_yaml.splitlines()
    bed_lines = [l[2:] if l.startswith("  ") else l for l in lines if not l.startswith("__bed__:")]
    print("\n── YAML-preview ──────────────────────────────────────────")
    print("\n".join(bed_lines))
    print("──────────────────────────────────────────────────────────\n")

    ok = questionary.confirm("Tilføj dette bed til filen?", default=True).ask()
    if not ok:
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    # ── 5. Indsæt i YAML-fil ───────────────────────────────────────────────────
    if "bede" not in zone_data or zone_data["bede"] is None:
        zone_data["bede"] = CommentedSeq()
    zone_data["bede"].append(nyt_bed_data)

    with open(yaml_sti, "w", encoding="utf-8") as f:
        ry.dump(zone_data, f)

    print(f"✓ Bed '{bed_id}' tilføjet til {yaml_sti}")
    print("  Kør 'have' for at opdatere sitet.")


# ── Plant en plante ────────────────────────────────────────────────────────────

def _markér_dyr_inaktiv(høne_id: str) -> None:
    """Sæt aktiv: false på en høne i dyr.yaml (bevarer struktur via ruamel)."""
    from ruamel.yaml import YAML as RuamelYAML
    ry = RuamelYAML()
    ry.preserve_quotes = True
    ry.width = 120
    if not os.path.exists(DYR_FIL):
        return
    with open(DYR_FIL, encoding="utf-8") as f:
        data = ry.load(f)
    dyr = data.get("dyr") if isinstance(data, dict) else data
    for d in (dyr or []):
        if d.get("id") == høne_id:
            d["aktiv"] = False
            with open(DYR_FIL, "w", encoding="utf-8") as f:
                ry.dump(data, f)
            print(f"  ✓ {høne_id} markeret som udgået (aktiv: false) i dyr.yaml")
            return


def hons_ny_høne():
    """Wizard: tilføj en ny høne til dyr.yaml."""
    import questionary
    import re as _re
    from ruamel.yaml import YAML as RuamelYAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    ry = RuamelYAML()
    ry.preserve_quotes = True
    ry.default_flow_style = False
    ry.width = 120

    race = questionary.text("Race:").ask()
    if not race or not race.strip():
        sys.exit(0)
    race = race.strip()

    farve = questionary.text("Farve/mærke (kan være tom):").ask()
    if farve is None:
        sys.exit(0)
    farve = farve.strip()

    fødsel = questionary.text(
        "Fødselsdato (ISO, fx 2023-04-12 — kan være tom):",
        validate=lambda v: (not v.strip()) or bool(_re.match(r"^\d{4}-\d{2}-\d{2}$", v.strip()))
            or "Format: ÅÅÅÅ-MM-DD",
    ).ask()
    if fødsel is None:
        sys.exit(0)
    fødsel = fødsel.strip()

    # Generér løbenummereret id: slug(race-farve)-N
    db = byg_dyr_db()
    basis = _slug(f"{race}-{farve}") if farve else _slug(race)
    n = 1
    nyt_id = f"{basis}-{n}"
    while nyt_id in db:
        n += 1
        nyt_id = f"{basis}-{n}"

    ny = CommentedMap()
    ny["id"] = nyt_id
    ny["race"] = race
    if farve:
        ny["farve"] = farve
    if fødsel:
        ny["fødselsdato"] = fødsel
    ny["aktiv"] = True

    import io
    buf = io.StringIO()
    ry.dump([ny], buf)
    print("\n── YAML-preview ──────────────────────────────────────────")
    print(buf.getvalue().rstrip())
    print("──────────────────────────────────────────────────────────\n")

    if not questionary.confirm(f"Tilføj '{nyt_id}' til dyr.yaml?", default=True).ask():
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    if os.path.exists(DYR_FIL):
        with open(DYR_FIL, encoding="utf-8") as f:
            data = ry.load(f)
    else:
        data = None
    if isinstance(data, dict):
        if not data.get("dyr"):
            data["dyr"] = CommentedSeq()
        data["dyr"].append(ny)
    else:
        if data is None:
            data = CommentedSeq()
        data.append(ny)

    with open(DYR_FIL, "w", encoding="utf-8") as f:
        ry.dump(data, f)
    print(f"✓ Høne '{nyt_id}' tilføjet til {DYR_FIL}")


def hons_ny_obs():
    """Wizard: registrér en hønse-observation som YAML-entry i entries/hons/."""
    import questionary
    import re as _re
    from ruamel.yaml import YAML as RuamelYAML

    # 1. Type
    valgt_type = questionary.select(
        "Hvilken type observation?",
        choices=[questionary.Choice(title=f"{cfg['ikon']} {cfg['label']}", value=t)
                 for t, cfg in HONS_TYPER.items()],
    ).ask()
    if not valgt_type:
        sys.exit(0)

    # 2. Dato
    i_dag = datetime.date.today().isoformat()
    dato = questionary.text(
        "Dato:",
        default=i_dag,
        validate=lambda v: bool(_re.match(r"^\d{4}-\d{2}-\d{2}$", v)) or f"Ugyldigt datoformat: {v!r}",
    ).ask()
    if not dato:
        sys.exit(0)

    db = byg_dyr_db()
    aktive = [d for d in db.values() if d.get("aktiv", True)]

    def vælg_høne(prompt: str, valgfri: bool = False):
        """Autocomplete over aktive høner — vis 'race farve', returnér id."""
        if not aktive:
            if not valgfri:
                print("  ⚠️  Ingen aktive høner i dyr.yaml — feltet springes over.")
            return None
        labels = {f"{_dyr_label(d)} [{d['id']}]": d["id"] for d in aktive}
        valg = questionary.autocomplete(
            prompt,
            choices=list(labels.keys()),
            validate=lambda v: True if (valgfri and not v.strip()) else (v in labels)
                or "Vælg en høne fra listen (Tab for forslag)",
        ).ask()
        if valg is None:
            sys.exit(0)
        return labels.get(valg.strip()) if valg.strip() else None

    def _heltal(v):
        return v.strip().isdigit() or "Skal være et heltal"

    def _tal(v):
        if not v.strip():
            return True
        try:
            float(v.replace(",", "."))
            return True
        except ValueError:
            return "Skal være et tal"

    entry: dict = {"dato": dato, "type": valgt_type}

    if valgt_type == "æglægning":
        antal = questionary.text("Antal æg:", default="0", validate=_heltal).ask()
        if antal is None:
            sys.exit(0)
        entry["æg"] = int(antal)

    elif valgt_type == "ruge-start":
        høne = vælg_høne("Høne (rugende):", valgfri=True)
        if høne:
            entry["høne"] = høne
        antal = questionary.text("Antal æg lagt til rugning:", default="0", validate=_heltal).ask()
        if antal is None:
            sys.exit(0)
        entry["æg_antal"] = int(antal)
        klæk = (datetime.date.fromisoformat(dato) + datetime.timedelta(days=21)).isoformat()
        entry["forventet_klæk"] = klæk
        print(f"\n🐣 Forventet klækning: {klæk}  (sat-dato + 21 dage)\n")

    elif valgt_type == "foderkøb":
        foder = questionary.text("Foder-type (fx pellets):").ask()
        if foder and foder.strip():
            entry["foder_type"] = foder.strip()
        mængde = questionary.text("Mængde i kg:", validate=_tal).ask()
        if mængde is None:
            sys.exit(0)
        if mængde.strip():
            tal = float(mængde.replace(",", "."))
            entry["mængde_kg"] = int(tal) if tal == int(tal) else tal
        pris = questionary.text("Pris i kr:", validate=_tal).ask()
        if pris and pris.strip():
            tal = float(pris.replace(",", "."))
            entry["pris"] = int(tal) if tal == int(tal) else tal
        butik = questionary.text("Butik:").ask()
        if butik and butik.strip():
            entry["butik"] = butik.strip()

    elif valgt_type == "sundhedsobs":
        høne = vælg_høne("Høne (Enter/tom = hele flokken):", valgfri=True)
        if høne:
            entry["høne"] = høne
        obs = questionary.text("Observation:",
                               validate=lambda v: bool(v.strip()) or "Observation er påkrævet").ask()
        if not obs:
            sys.exit(0)
        entry["observation"] = obs.strip()
        handling = questionary.text("Handling (kan være tom):").ask()
        if handling and handling.strip():
            entry["handling"] = handling.strip()

    elif valgt_type == "dødsfald":
        høne = vælg_høne("Høne:", valgfri=False)
        if høne:
            entry["høne"] = høne
        årsag = questionary.text("Årsag (kan være tom):", default="ukendt").ask()
        if årsag and årsag.strip():
            entry["årsag"] = årsag.strip()

    elif valgt_type == "fjerfældning":
        fase = questionary.select("Fase:", choices=["start", "slut"]).ask()
        if not fase:
            sys.exit(0)
        entry["fase"] = fase

    noter = questionary.text("Noter (kan være tom):").ask()
    if noter is None:
        sys.exit(0)
    if noter.strip():
        entry["noter"] = noter.strip()

    # Preview
    ry = RuamelYAML()
    ry.default_flow_style = False
    ry.width = 120
    ry.allow_unicode = True
    import io
    buf = io.StringIO()
    ry.dump(entry, buf)
    print("\n── Entry-preview ─────────────────────────────────────────")
    print(buf.getvalue().rstrip())
    print("──────────────────────────────────────────────────────────\n")

    if not questionary.confirm("Gem denne observation?", default=True).ask():
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    # Skriv entry-fil med kollisionshåndtering
    mappe = os.path.join(DATA_MAPPE, "entries", "hons")
    os.makedirs(mappe, exist_ok=True)
    basis = f"{dato}-{_slug(valgt_type)}"
    sti = os.path.join(mappe, basis + ".yaml")
    n = 2
    while os.path.exists(sti):
        sti = os.path.join(mappe, f"{basis}-{n}.yaml")
        n += 1
    with open(sti, "w", encoding="utf-8") as f:
        ry.dump(entry, f)
    print(f"✓ Observation gemt: {sti}")

    # Ved dødsfald: markér hønen udgået i dyr.yaml
    if valgt_type == "dødsfald" and entry.get("høne"):
        _markér_dyr_inaktiv(entry["høne"])

    print("  Kør 'have build' for at opdatere sitet.")


def plant_en_plante():
    """Interaktiv wizard til at plante en plante i et eksisterende bed."""
    import io
    import questionary
    from ruamel.yaml import YAML as RuamelYAML
    from ruamel.yaml.comments import CommentedSeq, CommentedMap

    ry = RuamelYAML()
    ry.preserve_quotes  = True
    ry.default_flow_style = False
    ry.width = 120

    plante_db = byg_plante_db()

    # ── 1. Vælg område ────────────────────────────────────────────────────────
    yaml_filer = sorted(
        f for f in os.listdir(DATA_MAPPE)
        if f.endswith(".yaml") and f not in {"almanak.yaml", "entries.yaml"}
    )
    if not yaml_filer:
        print(f"❌ Ingen zone-YAML-filer fundet i {DATA_MAPPE}/")
        sys.exit(1)

    fil_data: dict = {}
    fil_valg = []
    for fil in yaml_filer:
        with open(DATA_MAPPE / fil, encoding="utf-8") as fh:
            data = ry.load(fh)
        fil_data[fil] = data
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        titel = meta.get("titel", fil)
        fil_valg.append(questionary.Choice(title=f"{titel}  ({fil})", value=fil))

    valgt_fil = questionary.select(
        "Hvilket område vil du plante i?",
        choices=fil_valg,
    ).ask()
    if not valgt_fil:
        sys.exit(0)

    zone_data = fil_data[valgt_fil]

    # ── 2. Vælg bed ───────────────────────────────────────────────────────────
    bede = zone_data.get("bede", []) if isinstance(zone_data, dict) else []
    if not bede:
        print(f"❌ Ingen bede fundet i {valgt_fil}")
        sys.exit(1)

    bed_valg = []
    for bed in bede:
        bid   = bed.get("id", "?")
        bnavn = bed.get("navn", bid)
        bcm   = bed.get("bredde_cm", "?")
        dcm   = bed.get("dybde_cm",  "?")
        optaget = sum(z.get("bredde", 0) for z in bed.get("zoner", []))
        ledig_pct = round((1.0 - optaget) * 100)
        bed_valg.append(questionary.Choice(
            title=f"{bnavn}  [{bcm}×{dcm} cm — {ledig_pct}% ledig]",
            value=bid,
        ))

    valgt_bed_id = questionary.select(
        "Hvilket bed vil du plante i?",
        choices=bed_valg,
    ).ask()
    if not valgt_bed_id:
        sys.exit(0)

    valgt_bed  = next(b for b in bede if b.get("id") == valgt_bed_id)
    optaget    = sum(z.get("bredde", 0) for z in valgt_bed.get("zoner", []))
    ledig      = round(1.0 - optaget, 4)

    # ── 3. Vælg plante ────────────────────────────────────────────────────────
    if not plante_db:
        print(f"❌ Ingen planter fundet i {PLANTER_FIL}")
        sys.exit(1)

    valgt_plante = None
    print()
    while valgt_plante is None:
        søg = questionary.text("Søg efter plante (navn, sort eller id):").ask()
        if søg is None:
            sys.exit(0)
        hits = _søg_planter(søg, plante_db)
        if not hits:
            print(f"  Ingen planter matcher '{søg}'. Prøv igen.")
            continue
        if len(hits) == 1:
            valgt_plante = hits[0]
        else:
            labels = [_plante_label(p) for p in hits]
            valgt_label = questionary.select("Vælg plante:", choices=labels).ask()
            if not valgt_label:
                sys.exit(0)
            valgt_plante = hits[labels.index(valgt_label)]

    zone_navn = valgt_plante.get("sort") or valgt_plante.get("navn", "")

    def _valider_måned(v):
        try:
            m = int(v)
        except ValueError:
            return "Indtast et tal fra 1 til 12"
        if m < 1 or m > 12:
            return "Måneden skal være mellem 1 og 12"
        return True

    # ── 4. Efterafgrøde? ──────────────────────────────────────────────────────
    # Udled forslag til fra/til fra planter.yaml-kalenderdata
    _fra_forslag = valgt_plante.get("udplantning") or valgt_plante.get("direkte") or valgt_plante.get("indendørs")
    _til_forslag = valgt_plante.get("høst_til") or valgt_plante.get("høst_fra")

    er_efterafgrøde = questionary.confirm(
        "Er dette en efterafgrøde med en bestemt periode (fra/til måneder)?",
        default=False,
    ).ask()
    if er_efterafgrøde is None:
        sys.exit(0)

    fra_måned = None
    til_måned = None
    afløser_zone_idx = None
    eksisterende_zoner = valgt_bed.get("zoner", []) or []

    if er_efterafgrøde:
        fra_kwargs = {"default": str(_fra_forslag)} if _fra_forslag else {}
        fra_str = questionary.text(
            f"Fra hvilken måned plantes {zone_navn}? (1–12):",
            validate=_valider_måned,
            **fra_kwargs,
        ).ask()
        if fra_str is None:
            sys.exit(0)
        fra_måned = int(fra_str)

        til_kwargs = {"default": str(_til_forslag)} if _til_forslag else {}
        til_str = questionary.text(
            f"Til hvilken måned er {zone_navn} i jorden? (1–12):",
            validate=_valider_måned,
            **til_kwargs,
        ).ask()
        if til_str is None:
            sys.exit(0)
        til_måned = int(til_str)

        if eksisterende_zoner:
            afløser = questionary.confirm(
                "Afløser den en eksisterende zone i dette bed?",
                default=True,
            ).ask()
            if afløser is None:
                sys.exit(0)

            if afløser:
                zone_valg = []
                for i, z in enumerate(eksisterende_zoner):
                    znavn = z.get("navn", f"Zone {i+1}")
                    if "plante_id" in z:
                        p = plante_db.get(z["plante_id"], {})
                        pnavn = p.get("sort") or p.get("navn", z["plante_id"])
                        label = f"{znavn}  [{pnavn}]"
                    elif "afgrøder" in z:
                        navne = []
                        for a in z.get("afgrøder", []):
                            p = plante_db.get(a.get("plante_id", ""), {})
                            navne.append(p.get("sort") or p.get("navn", a.get("plante_id", "?")))
                        label = f"{znavn}  [{' → '.join(navne)}]"
                    else:
                        label = znavn
                    zone_valg.append(questionary.Choice(title=label, value=i))

                afløser_zone_idx = questionary.select(
                    "Hvilken zone afløser den?",
                    choices=zone_valg,
                ).ask()
                if afløser_zone_idx is None:
                    sys.exit(0)

    # ── 5. Bredde (kun ny zone) ───────────────────────────────────────────────
    zone_bredde = None
    if afløser_zone_idx is None:
        def _valider_bredde(v):
            try:
                f = float(v.replace(",", "."))
            except ValueError:
                return "Indtast et tal, fx 0.25"
            if f <= 0 or f > 1.0:
                return "Bredden skal være et tal mellem 0 og 1"
            return True

        bredde_hint = (f"ledig: {ledig:.2f} ({ledig*100:.0f}%)"
                       if ledig > 0 else "bedet er fuldt optaget")
        bredde_str = questionary.text(
            f"Bredde 0–1  [{bredde_hint}]:",
            validate=_valider_bredde,
        ).ask()
        if bredde_str is None:
            sys.exit(0)
        zone_bredde = round(float(bredde_str.replace(",", ".")), 4)

        if zone_bredde > ledig + 0.001:
            ny_total = round(optaget + zone_bredde, 4)
            ok = questionary.confirm(
                f"⚠️  Zonen ({zone_bredde}) overstiger den ledige plads ({ledig:.2f}). "
                f"Total bliver {ny_total}. Vil du fortsætte?",
                default=False,
            ).ask()
            if not ok:
                sys.exit(0)

    # ── 6. Byg zone eller modificér eksisterende ─────────────────────────────
    ny_zone = None

    if afløser_zone_idx is not None:
        eks_zone = eksisterende_zoner[afløser_zone_idx]

        if "plante_id" in eks_zone:
            eks_pid   = eks_zone["plante_id"]
            eks_p     = plante_db.get(eks_pid, {})
            eks_navn  = eks_p.get("sort") or eks_p.get("navn", eks_pid)

            _eks_fra_forslag = eks_p.get("udplantning") or eks_p.get("direkte") or eks_p.get("indendørs")
            _eks_til_forslag = eks_p.get("høst_til") or eks_p.get("høst_fra")
            print(f"\nFor at konvertere til sædskifte skal vi vide perioden for '{eks_navn}'.")
            eks_fra_str = questionary.text(
                f"Fra hvilken måned er '{eks_navn}' i jorden? (1–12):",
                validate=_valider_måned,
                **( {"default": str(_eks_fra_forslag)} if _eks_fra_forslag else {} ),
            ).ask()
            if eks_fra_str is None:
                sys.exit(0)
            eks_til_str = questionary.text(
                f"Til hvilken måned er '{eks_navn}' i jorden? (1–12):",
                validate=_valider_måned,
                **( {"default": str(_eks_til_forslag)} if _eks_til_forslag else {} ),
            ).ask()
            if eks_til_str is None:
                sys.exit(0)

            a1 = CommentedMap()
            a1["plante_id"] = eks_pid
            a1["fra"]       = int(eks_fra_str)
            a1["til"]       = int(eks_til_str)
            a2 = CommentedMap()
            a2["plante_id"] = valgt_plante["id"]
            a2["fra"]       = fra_måned
            a2["til"]       = til_måned
            ny_afgrøder = CommentedSeq()
            ny_afgrøder.extend([a1, a2])

            del eks_zone["plante_id"]
            if "antal" in eks_zone:
                del eks_zone["antal"]
            eks_zone["afgrøder"] = ny_afgrøder
            old_navn = eks_zone.get("navn", eks_navn)
            eks_zone["navn"] = f"{old_navn} → {zone_navn}"

        else:
            ny_afgrøde = CommentedMap()
            ny_afgrøde["plante_id"] = valgt_plante["id"]
            ny_afgrøde["fra"]       = fra_måned
            ny_afgrøde["til"]       = til_måned
            eks_zone["afgrøder"].append(ny_afgrøde)
            eks_zone["navn"] = f"{eks_zone.get('navn', '')} → {zone_navn}"

        preview_obj = eks_zone
        bekræft_tekst = (
            f"Tilføj '{zone_navn}' ({MÅNEDER[fra_måned-1]}–{MÅNEDER[til_måned-1]}) "
            f"til zone '{eks_zone.get('navn', '?')}' i bed '{valgt_bed.get('navn', valgt_bed_id)}'?"
        )
    else:
        ny_zone = CommentedMap()
        ny_zone["navn"]   = zone_navn
        ny_zone["bredde"] = zone_bredde

        if er_efterafgrøde:
            a = CommentedMap()
            a["plante_id"] = valgt_plante["id"]
            a["fra"]       = fra_måned
            a["til"]       = til_måned
            ny_afgrøder = CommentedSeq()
            ny_afgrøder.append(a)
            ny_zone["afgrøder"] = ny_afgrøder
            periode = f" ({MÅNEDER[fra_måned-1]}–{MÅNEDER[til_måned-1]})"
        else:
            ny_zone["plante_id"] = valgt_plante["id"]
            periode = ""

        preview_obj   = ny_zone
        bekræft_tekst = (
            f"Plant '{zone_navn}'{periode} i bed '{valgt_bed.get('navn', valgt_bed_id)}'?"
        )

    # ── 7. Preview og bekræft ─────────────────────────────────────────────────
    buf = io.StringIO()
    ry.dump({"__z__": preview_obj}, buf)
    zone_lines = [
        (l[2:] if l.startswith("  ") else l)
        for l in buf.getvalue().splitlines()
        if not l.startswith("__z__:")
    ]
    print("\n── YAML-preview ──────────────────────────────────────────")
    print("\n".join(zone_lines))
    print("──────────────────────────────────────────────────────────\n")

    ok = questionary.confirm(bekræft_tekst, default=True).ask()
    if not ok:
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    # ── 8. Skriv til YAML-fil ─────────────────────────────────────────────────
    if ny_zone is not None:
        for bed in zone_data["bede"]:
            if bed.get("id") == valgt_bed_id:
                if "zoner" not in bed or bed["zoner"] is None:
                    bed["zoner"] = CommentedSeq()
                bed["zoner"].append(ny_zone)
                break

    with open(DATA_MAPPE / valgt_fil, "w", encoding="utf-8") as fh:
        ry.dump(zone_data, fh)

    if afløser_zone_idx is not None:
        print(f"✅ '{zone_navn}' ({valgt_plante['id']}) tilføjet som efterafgrøde i "
              f"'{valgt_bed.get('navn', valgt_bed_id)}'")
    else:
        print(f"✅ '{zone_navn}' ({valgt_plante['id']}) plantet i "
              f"'{valgt_bed.get('navn', valgt_bed_id)}'")
    print("   Kør 'have build' for at opdatere sitet.")


def riv_en_plante_op():
    """Interaktiv wizard til at fjerne en zone fra et eksisterende bed."""
    import io
    import questionary
    from ruamel.yaml import YAML as RuamelYAML

    ry = RuamelYAML()
    ry.preserve_quotes  = True
    ry.default_flow_style = False
    ry.width = 120

    plante_db = byg_plante_db()

    # ── 1. Vælg område ────────────────────────────────────────────────────────
    yaml_filer = sorted(
        f for f in os.listdir(DATA_MAPPE)
        if f.endswith(".yaml") and f not in {"almanak.yaml", "entries.yaml"}
    )
    if not yaml_filer:
        print(f"❌ Ingen zone-YAML-filer fundet i {DATA_MAPPE}/")
        sys.exit(1)

    fil_data: dict = {}
    fil_valg = []
    for fil in yaml_filer:
        with open(DATA_MAPPE / fil, encoding="utf-8") as fh:
            data = ry.load(fh)
        fil_data[fil] = data
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        titel = meta.get("titel", fil)
        fil_valg.append(questionary.Choice(title=f"{titel}  ({fil})", value=fil))

    valgt_fil = questionary.select(
        "Hvilket område vil du rive op i?",
        choices=fil_valg,
    ).ask()
    if not valgt_fil:
        sys.exit(0)

    zone_data = fil_data[valgt_fil]

    # ── 2. Vælg bed ───────────────────────────────────────────────────────────
    bede = zone_data.get("bede", []) if isinstance(zone_data, dict) else []
    if not bede:
        print(f"❌ Ingen bede fundet i {valgt_fil}")
        sys.exit(1)

    bed_valg = []
    for bed in bede:
        bid   = bed.get("id", "?")
        bnavn = bed.get("navn", bid)
        antal = len(bed.get("zoner") or [])
        bed_valg.append(questionary.Choice(
            title=f"{bnavn}  [{antal} zone{'r' if antal != 1 else ''}]",
            value=bid,
        ))

    valgt_bed_id = questionary.select(
        "Hvilket bed vil du rive op i?",
        choices=bed_valg,
    ).ask()
    if not valgt_bed_id:
        sys.exit(0)

    valgt_bed = next(b for b in bede if b.get("id") == valgt_bed_id)
    zoner = valgt_bed.get("zoner") or []
    if not zoner:
        print(f"❌ Bedet '{valgt_bed.get('navn', valgt_bed_id)}' har ingen zoner.")
        sys.exit(1)

    # ── 3. Vælg zone ──────────────────────────────────────────────────────────
    def _zone_label(z):
        zone_navn = z.get("navn", "?")
        pid = z.get("plante_id")
        if pid:
            p = plante_db.get(pid, {})
            plante_navn = p.get("sort") or p.get("navn") or pid
            return f"{zone_navn}  ({plante_navn})"
        if z.get("afgrøder"):
            navne = []
            for a in z.get("afgrøder", []):
                p = plante_db.get(a.get("plante_id", ""), {})
                navne.append(p.get("sort") or p.get("navn", a.get("plante_id", "?")))
            return f"{zone_navn}  ({' → '.join(navne)})"
        return zone_navn

    zone_valg = [
        questionary.Choice(title=_zone_label(z), value=i)
        for i, z in enumerate(zoner)
    ]

    valgt_idx = questionary.select(
        "Hvilken zone vil du rive op?",
        choices=zone_valg,
    ).ask()
    if valgt_idx is None:
        sys.exit(0)

    valgt_zone = zoner[valgt_idx]

    # ── 4. Enkelt afgrøde eller hele zonen? (kun ved sædskifte) ──────────────
    afgrøder = valgt_zone.get("afgrøder") or []
    fjern_afgrøde_idx = None

    if afgrøder:
        fjern_hvad = questionary.select(
            "Zonen er et sædskifte. Hvad vil du fjerne?",
            choices=[
                questionary.Choice(title="Kun én bestemt afgrøde", value="afgrøde"),
                questionary.Choice(title="Hele zonen", value="zone"),
            ],
        ).ask()
        if fjern_hvad is None:
            sys.exit(0)

        if fjern_hvad == "afgrøde":
            afgrøde_valg = []
            for i, a in enumerate(afgrøder):
                pid   = a.get("plante_id", "?")
                p     = plante_db.get(pid, {})
                pnavn = p.get("sort") or p.get("navn", pid)
                fra   = a.get("fra")
                til   = a.get("til")
                if fra and til:
                    label = f"{pnavn}  ({MÅNEDER[fra-1]}–{MÅNEDER[til-1]})"
                else:
                    label = pnavn
                afgrøde_valg.append(questionary.Choice(title=label, value=i))

            fjern_afgrøde_idx = questionary.select(
                "Hvilken afgrøde vil du fjerne?",
                choices=afgrøde_valg,
            ).ask()
            if fjern_afgrøde_idx is None:
                sys.exit(0)

    # ── 5. Preview og bekræft ─────────────────────────────────────────────────
    if fjern_afgrøde_idx is not None:
        preview_obj   = afgrøder[fjern_afgrøde_idx]
        overskrift    = "── Fjerner denne afgrøde ────────────────────────────────"
        a             = afgrøder[fjern_afgrøde_idx]
        pid           = a.get("plante_id", "?")
        p             = plante_db.get(pid, {})
        pnavn         = p.get("sort") or p.get("navn", pid)
        fra, til      = a.get("fra"), a.get("til")
        periode       = f" ({MÅNEDER[fra-1]}–{MÅNEDER[til-1]})" if fra and til else ""
        bekræft_tekst = (
            f"Fjern '{pnavn}'{periode} fra zone "
            f"'{valgt_zone.get('navn', '?')}' i bed '{valgt_bed.get('navn', valgt_bed_id)}'?"
        )
    else:
        preview_obj   = valgt_zone
        overskrift    = "── Fjerner denne zone ────────────────────────────────────"
        bekræft_tekst = (
            f"Fjern '{_zone_label(valgt_zone)}' fra bed '{valgt_bed.get('navn', valgt_bed_id)}'?"
        )

    buf = io.StringIO()
    ry.dump({"__z__": preview_obj}, buf)
    zone_lines = [
        (l[2:] if l.startswith("  ") else l)
        for l in buf.getvalue().splitlines()
        if not l.startswith("__z__:")
    ]
    print(f"\n{overskrift}")
    print("\n".join(zone_lines))
    print("──────────────────────────────────────────────────────────\n")

    ok = questionary.confirm(bekræft_tekst, default=False).ask()
    if not ok:
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    # ── 6. Skriv til YAML-fil ─────────────────────────────────────────────────
    for bed in zone_data["bede"]:
        if bed.get("id") == valgt_bed_id:
            if fjern_afgrøde_idx is not None:
                resterende = [a for i, a in enumerate(afgrøder) if i != fjern_afgrøde_idx]
                if len(resterende) == 0:
                    bed["zoner"].pop(valgt_idx)
                elif len(resterende) == 1:
                    del valgt_zone["afgrøder"]
                    valgt_zone["plante_id"] = resterende[0]["plante_id"]
                else:
                    valgt_zone["afgrøder"].pop(fjern_afgrøde_idx)
            else:
                bed["zoner"].pop(valgt_idx)
            break

    with open(DATA_MAPPE / valgt_fil, "w", encoding="utf-8") as fh:
        ry.dump(zone_data, fh)

    if fjern_afgrøde_idx is not None:
        print(f"✅ '{pnavn}'{periode} fjernet fra zone '{valgt_zone.get('navn', '?')}' "
              f"i '{valgt_bed.get('navn', valgt_bed_id)}'")
    else:
        print(f"✅ '{_zone_label(valgt_zone)}' fjernet fra '{valgt_bed.get('navn', valgt_bed_id)}'")
    print("   Kør 'have build' for at opdatere sitet.")


def ret_en_plante():
    """Interaktiv wizard til at rette en zone i et eksisterende bed."""
    import io
    import questionary
    from ruamel.yaml import YAML as RuamelYAML

    ry = RuamelYAML()
    ry.preserve_quotes  = True
    ry.default_flow_style = False
    ry.width = 120

    plante_db = byg_plante_db()

    # ── 1. Vælg område ────────────────────────────────────────────────────────
    yaml_filer = sorted(
        f for f in os.listdir(DATA_MAPPE)
        if f.endswith(".yaml") and f not in {"almanak.yaml", "entries.yaml"}
    )
    if not yaml_filer:
        print(f"❌ Ingen zone-YAML-filer fundet i {DATA_MAPPE}/")
        sys.exit(1)

    fil_data: dict = {}
    fil_valg = []
    for fil in yaml_filer:
        with open(DATA_MAPPE / fil, encoding="utf-8") as fh:
            data = ry.load(fh)
        fil_data[fil] = data
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        titel = meta.get("titel", fil)
        fil_valg.append(questionary.Choice(title=f"{titel}  ({fil})", value=fil))

    valgt_fil = questionary.select("Hvilket område vil du rette i?", choices=fil_valg).ask()
    if not valgt_fil:
        sys.exit(0)

    zone_data = fil_data[valgt_fil]

    # ── 2. Vælg bed ───────────────────────────────────────────────────────────
    bede = zone_data.get("bede", []) if isinstance(zone_data, dict) else []
    if not bede:
        print(f"❌ Ingen bede fundet i {valgt_fil}")
        sys.exit(1)

    bed_valg = []
    for bed in bede:
        bid   = bed.get("id", "?")
        bnavn = bed.get("navn", bid)
        antal = len(bed.get("zoner") or [])
        bed_valg.append(questionary.Choice(
            title=f"{bnavn}  [{antal} zone{'r' if antal != 1 else ''}]",
            value=bid,
        ))

    valgt_bed_id = questionary.select("Hvilket bed vil du rette i?", choices=bed_valg).ask()
    if not valgt_bed_id:
        sys.exit(0)

    valgt_bed = next(b for b in bede if b.get("id") == valgt_bed_id)
    zoner = valgt_bed.get("zoner") or []
    if not zoner:
        print(f"❌ Bedet '{valgt_bed.get('navn', valgt_bed_id)}' har ingen zoner.")
        sys.exit(1)

    # ── 3. Vælg zone ──────────────────────────────────────────────────────────
    def _zone_label(z):
        znavn = z.get("navn", "?")
        pid   = z.get("plante_id")
        if pid:
            p = plante_db.get(pid, {})
            return f"{znavn}  ({p.get('sort') or p.get('navn') or pid})"
        afg = z.get("afgrøder")
        if afg:
            navne = []
            for a in afg:
                p = plante_db.get(a.get("plante_id", ""), {})
                navne.append(p.get("sort") or p.get("navn", a.get("plante_id", "?")))
            return f"{znavn}  ({' → '.join(navne)})"
        return znavn

    zone_valg = [
        questionary.Choice(title=_zone_label(z), value=i)
        for i, z in enumerate(zoner)
    ]

    valgt_idx = questionary.select("Hvilken zone vil du rette?", choices=zone_valg).ask()
    if valgt_idx is None:
        sys.exit(0)

    valgt_zone = zoner[valgt_idx]

    # ── 4. Indsaml ændringer ──────────────────────────────────────────────────
    def _valider_måned(v):
        try:
            m = int(v)
        except ValueError:
            return "Indtast et tal fra 1 til 12"
        return True if 1 <= m <= 12 else "Måneden skal være mellem 1 og 12"

    def _valider_bredde(v):
        try:
            f = float(v.replace(",", "."))
        except ValueError:
            return "Indtast et tal, fx 0.25"
        return True if 0 < f <= 1.0 else "Bredden skal være et tal mellem 0 og 1"

    def _søg_og_vælg_plante():
        valgt = None
        while valgt is None:
            søg = questionary.text("Søg efter plante (navn, sort eller id):").ask()
            if søg is None:
                return None
            hits = _søg_planter(søg, plante_db)
            if not hits:
                print(f"  Ingen planter matcher '{søg}'. Prøv igen.")
                continue
            if len(hits) == 1:
                valgt = hits[0]
            else:
                labels = [_plante_label(p) for p in hits]
                valgt_label = questionary.select("Vælg plante:", choices=labels).ask()
                if not valgt_label:
                    return None
                valgt = hits[labels.index(valgt_label)]
        return valgt

    from ruamel.yaml.comments import CommentedSeq, CommentedMap

    ændr_navn           = None
    ændr_bredde         = None
    ændr_pid            = None   # nyt plante_id (simpel zone, ingen datoer)
    ændr_konverter      = None   # {pid, fra, til} — konvertér simpel → afgrøde-format
    ændr_afgrøde        = None   # {idx, pid, fra, til} — ret én afgrøde i sædskifte

    # Navn
    gammelt_navn = valgt_zone.get("navn", "")
    nyt_navn = (questionary.text("Zone-navn:", default=gammelt_navn).ask() or "").strip()
    if nyt_navn is None:
        sys.exit(0)
    if nyt_navn and nyt_navn != gammelt_navn:
        ændr_navn = nyt_navn

    # Bredde
    gammel_bredde = valgt_zone.get("bredde", "")
    ny_bredde_str = questionary.text(
        "Bredde (0–1):",
        default=str(gammel_bredde),
        validate=_valider_bredde,
    ).ask()
    if ny_bredde_str is None:
        sys.exit(0)
    ny_bredde = round(float(ny_bredde_str.replace(",", ".")), 4)
    if ny_bredde != gammel_bredde:
        ændr_bredde = ny_bredde

    # ── Plante og datoer — simpel zone (plante_id) ───────────────────────────
    if valgt_zone.get("plante_id"):
        eks_p    = plante_db.get(valgt_zone["plante_id"], {})
        eks_navn = eks_p.get("sort") or eks_p.get("navn", valgt_zone["plante_id"])

        # Skift plante?
        ny_pid_til_brug = valgt_zone["plante_id"]
        if questionary.confirm(f"Skift plante (nu: {eks_navn})?", default=False).ask():
            ny_plante = _søg_og_vælg_plante()
            if ny_plante is None:
                sys.exit(0)
            ny_pid_til_brug = ny_plante["id"]
            ændr_pid = ny_pid_til_brug

        # Tilføj periode (fra/til)?
        har_periode = questionary.confirm(
            "Tilføj såtid/planteperiode (fra/til måneder)?",
            default=False,
        ).ask()
        if har_periode is None:
            sys.exit(0)
        if har_periode:
            fra_str = questionary.text(
                f"Fra hvilken måned er planten i jorden? (1–12):",
                validate=_valider_måned,
            ).ask()
            if fra_str is None:
                sys.exit(0)
            til_str = questionary.text(
                f"Til hvilken måned er planten i jorden? (1–12):",
                validate=_valider_måned,
            ).ask()
            if til_str is None:
                sys.exit(0)
            ændr_konverter = {"pid": ny_pid_til_brug, "fra": int(fra_str), "til": int(til_str)}
            ændr_pid = None  # håndteres via ændr_konverter

    # ── Afgrøde og datoer — sædskifte-zone (afgrøder) ───────────────────────
    elif valgt_zone.get("afgrøder"):
        afgrøder = valgt_zone["afgrøder"]

        afgrøde_valg = []
        for i, a in enumerate(afgrøder):
            ap     = plante_db.get(a.get("plante_id", ""), {})
            apnavn = ap.get("sort") or ap.get("navn", a.get("plante_id", "?"))
            fra, til = a.get("fra"), a.get("til")
            label  = f"{apnavn}  ({MÅNEDER[fra-1]}–{MÅNEDER[til-1]})" if fra and til else apnavn
            afgrøde_valg.append(questionary.Choice(title=label, value=i))

        afgrøde_idx = questionary.select(
            "Hvilken afgrøde vil du redigere?", choices=afgrøde_valg
        ).ask()
        if afgrøde_idx is None:
            sys.exit(0)

        afg        = afgrøder[afgrøde_idx]
        eks_ap     = plante_db.get(afg.get("plante_id", ""), {})
        eks_apnavn = eks_ap.get("sort") or eks_ap.get("navn", afg.get("plante_id", "?"))

        ny_apid = afg.get("plante_id")
        if questionary.confirm(f"Skift plante (nu: {eks_apnavn})?", default=False).ask():
            ny_plante = _søg_og_vælg_plante()
            if ny_plante is None:
                sys.exit(0)
            ny_apid = ny_plante["id"]

        fra_str = questionary.text(
            "Fra måned (1–12):",
            default=str(afg.get("fra", "")),
            validate=_valider_måned,
        ).ask()
        if fra_str is None:
            sys.exit(0)
        til_str = questionary.text(
            "Til måned (1–12):",
            default=str(afg.get("til", "")),
            validate=_valider_måned,
        ).ask()
        if til_str is None:
            sys.exit(0)

        ændr_afgrøde = {"idx": afgrøde_idx, "pid": ny_apid,
                        "fra": int(fra_str), "til": int(til_str)}

    # ── 5. Anvend ændringer på in-memory struktur ─────────────────────────────
    if ændr_navn   is not None: valgt_zone["navn"]      = ændr_navn
    if ændr_bredde is not None: valgt_zone["bredde"]    = ændr_bredde

    if ændr_konverter is not None:
        # Konvertér simpel plante_id → afgrøde-format med periode
        a = CommentedMap()
        a["plante_id"] = ændr_konverter["pid"]
        a["fra"]       = ændr_konverter["fra"]
        a["til"]       = ændr_konverter["til"]
        ny_afgrøder = CommentedSeq()
        ny_afgrøder.append(a)
        del valgt_zone["plante_id"]
        if "antal" in valgt_zone:
            del valgt_zone["antal"]
        valgt_zone["afgrøder"] = ny_afgrøder
    elif ændr_pid is not None:
        valgt_zone["plante_id"] = ændr_pid

    if ændr_afgrøde is not None:
        afg = valgt_zone["afgrøder"][ændr_afgrøde["idx"]]
        afg["plante_id"] = ændr_afgrøde["pid"]
        afg["fra"]       = ændr_afgrøde["fra"]
        afg["til"]       = ændr_afgrøde["til"]

    # ── 6. Preview og bekræft ─────────────────────────────────────────────────
    buf = io.StringIO()
    ry.dump({"__z__": valgt_zone}, buf)
    zone_lines = [
        (l[2:] if l.startswith("  ") else l)
        for l in buf.getvalue().splitlines()
        if not l.startswith("__z__:")
    ]
    print("\n── YAML-preview ──────────────────────────────────────────")
    print("\n".join(zone_lines))
    print("──────────────────────────────────────────────────────────\n")

    ok = questionary.confirm(
        f"Gem ændringer til zone '{valgt_zone.get('navn', '?')}' "
        f"i bed '{valgt_bed.get('navn', valgt_bed_id)}'?",
        default=True,
    ).ask()
    if not ok:
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    # ── 7. Skriv til YAML-fil ─────────────────────────────────────────────────
    with open(DATA_MAPPE / valgt_fil, "w", encoding="utf-8") as fh:
        ry.dump(zone_data, fh)

    print(f"✅ Zone '{valgt_zone.get('navn', '?')}' opdateret i '{valgt_bed.get('navn', valgt_bed_id)}'")
    print("   Kør 'have build' for at opdatere sitet.")


def ret_bed():
    """Interaktiv wizard til at omfordele zone-bredder og tilføje nye zoner i et bed."""
    import questionary
    from ruamel.yaml import YAML as RuamelYAML
    from ruamel.yaml.comments import CommentedSeq, CommentedMap

    ry = RuamelYAML()
    ry.preserve_quotes   = True
    ry.default_flow_style = False
    ry.width = 120

    plante_db = byg_plante_db()

    # ── 1. Vælg område ────────────────────────────────────────────────────────
    yaml_filer = sorted(
        f for f in os.listdir(DATA_MAPPE)
        if f.endswith(".yaml") and f not in {"almanak.yaml", "entries.yaml"}
    )
    if not yaml_filer:
        print(f"❌ Ingen zone-YAML-filer fundet i {DATA_MAPPE}/")
        sys.exit(1)

    fil_data: dict = {}
    fil_valg = []
    for fil in yaml_filer:
        with open(DATA_MAPPE / fil, encoding="utf-8") as fh:
            data = ry.load(fh)
        fil_data[fil] = data
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        titel = meta.get("titel", fil)
        fil_valg.append(questionary.Choice(title=f"{titel}  ({fil})", value=fil))

    valgt_fil = questionary.select("Hvilket område vil du rette i?", choices=fil_valg).ask()
    if not valgt_fil:
        sys.exit(0)

    zone_data = fil_data[valgt_fil]

    # ── 2. Vælg bed ───────────────────────────────────────────────────────────
    bede = zone_data.get("bede", []) if isinstance(zone_data, dict) else []
    if not bede:
        print(f"❌ Ingen bede fundet i {valgt_fil}")
        sys.exit(1)

    bed_valg = []
    for bed in bede:
        bid   = bed.get("id", "?")
        bnavn = bed.get("navn", bid)
        bcm   = bed.get("bredde_cm", "?")
        dcm   = bed.get("dybde_cm",  "?")
        antal = len(bed.get("zoner") or [])
        bed_valg.append(questionary.Choice(
            title=f"{bnavn}  [{bcm}×{dcm} cm — {antal} zone{'r' if antal != 1 else ''}]",
            value=bid,
        ))

    valgt_bed_id = questionary.select("Hvilket bed vil du rette?", choices=bed_valg).ask()
    if not valgt_bed_id:
        sys.exit(0)

    valgt_bed = next(b for b in bede if b.get("id") == valgt_bed_id)
    if "zoner" not in valgt_bed or valgt_bed["zoner"] is None:
        valgt_bed["zoner"] = CommentedSeq()
    zoner = valgt_bed["zoner"]

    # ── 3. Vis nuværende zoner ────────────────────────────────────────────────
    def _zone_info(z, i, mærke=""):
        znavn  = z.get("navn", f"Zone {i+1}")
        bredde = z.get("bredde")
        bredde_txt = f"{bredde:.2f} — {bredde*100:.0f}%" if bredde else "—"
        pid = z.get("plante_id")
        if pid:
            p = plante_db.get(pid, {})
            pnavn = p.get("sort") or p.get("navn") or pid
            return f"  {i+1}. {znavn:<28} ({pnavn})  [{bredde_txt}]{mærke}"
        afg = z.get("afgrøder")
        if afg:
            navne = []
            for a in afg:
                p = plante_db.get(a.get("plante_id", ""), {})
                navne.append(p.get("sort") or p.get("navn", a.get("plante_id", "?")))
            return f"  {i+1}. {znavn:<28} ({' → '.join(navne)})  [{bredde_txt}]{mærke}"
        return f"  {i+1}. {znavn:<28} [{bredde_txt}]{mærke}"

    print(f"\nNuværende zoner i '{valgt_bed.get('navn', valgt_bed_id)}':")
    for i, z in enumerate(zoner):
        print(_zone_info(z, i))
    print()

    # ── 4. Tilføj nye zoner (loop) ────────────────────────────────────────────
    def _søg_og_vælg_plante():
        valgt = None
        while valgt is None:
            søg = questionary.text("Søg efter plante (navn, sort eller id):").ask()
            if søg is None:
                return None
            hits = _søg_planter(søg, plante_db)
            if not hits:
                print(f"  Ingen planter matcher '{søg}'. Prøv igen.")
                continue
            if len(hits) == 1:
                valgt = hits[0]
            else:
                labels = [_plante_label(p) for p in hits]
                valgt_label = questionary.select("Vælg plante:", choices=labels).ask()
                if not valgt_label:
                    return None
                valgt = hits[labels.index(valgt_label)]
        return valgt

    nye_zoner: list = []
    while True:
        tilføj = questionary.confirm("Tilføj en ny zone?", default=False).ask()
        if not tilføj:
            break

        ny_navn = (questionary.text("Navn på ny zone:").ask() or "").strip()
        if not ny_navn:
            sys.exit(0)

        med_plante = questionary.confirm(
            "Tilføj plante nu? (ellers: brug 'have plant-en-plante' bagefter)",
            default=True,
        ).ask()
        if med_plante is None:
            sys.exit(0)

        ny_zone = CommentedMap()
        ny_zone["navn"] = ny_navn

        if med_plante:
            ny_plante = _søg_og_vælg_plante()
            if ny_plante is None:
                sys.exit(0)
            ny_zone["plante_id"] = ny_plante["id"]

        nye_zoner.append(ny_zone)
        print(f"  ✓ '{ny_navn}' tilføjet")

    n_eksisterende = len(zoner)
    alle_zoner     = list(zoner) + nye_zoner
    n              = len(alle_zoner)

    if n == 0:
        print("❌ Ingen zoner at fordele.")
        sys.exit(1)

    # ── 5. Ratio-input ────────────────────────────────────────────────────────
    print(f"\nAlle {n} zoner — angiv nyt ratio:")
    for i, z in enumerate(alle_zoner):
        mærke = "  ← ny" if i >= n_eksisterende else ""
        print(_zone_info(z, i, mærke))

    # Byg forslag ud fra nuværende bredder (afrundet til hele tal)
    eks_bredder = [z.get("bredde", 0) for z in zoner]
    if all(b > 0 for b in eks_bredder):
        eks_sum = sum(eks_bredder)
        forslag_tal = [round(b / eks_sum * 100) for b in eks_bredder]
        forslag_tal += [round(100 / n)] * len(nye_zoner)
    else:
        forslag_tal = [1] * n
    default_ratio = ":".join(str(t) for t in forslag_tal)

    def _valider_ratio(v):
        parts = [p.strip() for p in v.replace(" ", ":").split(":") if p.strip()]
        if len(parts) != n:
            return f"Angiv præcis {n} værdier (én per zone), adskilt af ':'"
        try:
            vals = [float(p.replace(",", ".")) for p in parts]
        except ValueError:
            return "Alle værdier skal være tal"
        if any(val <= 0 for val in vals):
            return "Alle værdier skal være positive"
        return True

    ratio_str = questionary.text(
        f"Ratio (fx '{default_ratio}'):",
        default=default_ratio,
        validate=_valider_ratio,
    ).ask()
    if ratio_str is None:
        sys.exit(0)

    parts  = [p.strip() for p in ratio_str.replace(" ", ":").split(":") if p.strip()]
    vals   = [float(p.replace(",", ".")) for p in parts]
    total  = sum(vals)
    bredder = [round(v / total, 4) for v in vals]
    # Ret afrundingsfejl så summen er præcis 1.0
    rest = round(1.0 - sum(bredder), 4)
    if rest:
        bredder[-1] = round(bredder[-1] + rest, 4)

    # ── 6. Preview ────────────────────────────────────────────────────────────
    print("\n── Ny fordeling ──────────────────────────────────────────")
    for i, z in enumerate(alle_zoner):
        znavn  = z.get("navn", f"Zone {i+1}")
        b      = bredder[i]
        mærke  = "  ← ny" if i >= n_eksisterende else ""
        print(f"  {i+1}. {znavn:<30} {b:.4f}  ({b*100:.1f}%){mærke}")
    print("──────────────────────────────────────────────────────────\n")

    ok = questionary.confirm(
        f"Gem ny fordeling i '{valgt_bed.get('navn', valgt_bed_id)}'?",
        default=True,
    ).ask()
    if not ok:
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    # ── 7. Anvend og skriv ────────────────────────────────────────────────────
    for i, z in enumerate(alle_zoner):
        z["bredde"] = bredder[i]
    for z in nye_zoner:
        zoner.append(z)

    with open(DATA_MAPPE / valgt_fil, "w", encoding="utf-8") as fh:
        ry.dump(zone_data, fh)

    print(f"✅ '{valgt_bed.get('navn', valgt_bed_id)}' opdateret")
    if nye_zoner:
        print(f"   {len(nye_zoner)} ny{'e' if len(nye_zoner) > 1 else ''} zone{'r' if len(nye_zoner) > 1 else ''} tilføjet")
    print("   Kør 'have build' for at opdatere sitet.")


# ── Vejrdata ───────────────────────────────────────────────────────────────────

def hent_vejr(år: int, force: bool = False):
    """Hent historisk vejrdata fra Open-Meteo og skriv månedlig statistik til almanak.yaml."""
    try:
        import requests
    except ImportError:
        print("❌ requests er ikke installeret — kør: pip install requests")
        sys.exit(1)

    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    lok = _config.get("lokation")
    if not lok:
        print(
            "❌ Mangler 'lokation' i haven.yaml. Tilføj:\n\n"
            "  lokation:\n"
            "    breddegrad: 55.67\n"
            "    længdegrad: 12.56\n"
            "    navn: \"København NV\""
        )
        sys.exit(1)

    breddegrad = lok["breddegrad"]
    længdegrad = lok["længdegrad"]
    sted_navn  = lok.get("navn", f"{breddegrad}, {længdegrad}")

    i_dag       = datetime.date.today()
    start_dato  = datetime.date(år, 1, 1)
    if force:
        slut_dato = i_dag
    else:
        slut_dato = i_dag.replace(day=1) - datetime.timedelta(days=1)

    if slut_dato < start_dato:
        print(f"ℹ️  Ingen afsluttede måneder at hente for {år} endnu")
        return

    almanak_sti = sti(_config, "data") / str(år) / "almanak.yaml"
    if not almanak_sti.exists():
        print(f"❌ Filen findes ikke: {almanak_sti}")
        sys.exit(1)

    print(f"📡 Henter vejrdata for {sted_navn} ({start_dato} → {slut_dato})…")
    resp = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude":   breddegrad,
            "longitude":  længdegrad,
            "start_date": start_dato.isoformat(),
            "end_date":   slut_dato.isoformat(),
            "daily":      "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum",
            "timezone":   "Europe/Copenhagen",
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"❌ API-fejl {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)

    daily      = resp.json().get("daily", {})
    datoer     = daily.get("time", [])
    t_max      = daily.get("temperature_2m_max", [])
    t_min      = daily.get("temperature_2m_min", [])
    t_mean     = daily.get("temperature_2m_mean", [])
    nedbør_raw = daily.get("precipitation_sum", [])

    måneds_rå: dict[str, dict] = {}
    for i, dato_str in enumerate(datoer):
        måned_navn = MÅNEDER_LANG[datetime.date.fromisoformat(dato_str).month - 1]
        d = måneds_rå.setdefault(måned_navn, {"mean": [], "min": [], "max": [], "ned": []})
        d["mean"].append(t_mean[i])
        d["min"].append(t_min[i])
        d["max"].append(t_max[i])
        d["ned"].append(nedbør_raw[i] if nedbør_raw[i] is not None else 0.0)

    ryaml = YAML()
    ryaml.preserve_quotes  = True
    ryaml.default_flow_style = False
    ryaml.width = 120
    with open(almanak_sti, encoding="utf-8") as f:
        alm = ryaml.load(f) or {}

    if "temperatur" not in alm:
        alm["temperatur"] = {}

    temp_sek = alm["temperatur"]
    skrevne  = []

    def _flow_seq(vals):
        s = CommentedSeq([round(v, 1) if v is not None else None for v in vals])
        s.fa.set_flow_style()
        return s

    for måned_navn, d in måneds_rå.items():
        mean_vals = [v for v in d["mean"] if v is not None]
        if not mean_vals:
            continue

        existing = temp_sek.get(måned_navn)
        har_daglige = existing is not None and existing.get("daglige")

        if har_daglige and not force:
            continue

        daglige_cm = CommentedMap()
        daglige_cm["middel"] = _flow_seq(d["mean"])
        daglige_cm["min"]    = _flow_seq(d["min"])
        daglige_cm["nedbør"] = _flow_seq(d["ned"])

        if existing is not None and not force:
            existing["daglige"] = daglige_cm
            print(f"  ✓ {måned_navn} {år}: daglige data tilføjet")
        else:
            min_vals = [v for v in d["min"] if v is not None]
            max_vals = [v for v in d["max"] if v is not None]
            m = CommentedMap()
            m["middel"]    = round(sum(mean_vals) / len(mean_vals), 1)
            m["min"]       = round(min(min_vals), 1) if min_vals else None
            m["max"]       = round(max(max_vals), 1) if max_vals else None
            m["nedbør_mm"] = round(sum(d["ned"]), 1)
            m["daglige"]   = daglige_cm
            temp_sek[måned_navn] = m
            print(f"  ✓ {måned_navn} {år} skrevet")
        skrevne.append(måned_navn)

    if not skrevne:
        print("ℹ️  Ingen nye måneder at skrive (brug --force for at overskrive eksisterende)")
        return

    with open(almanak_sti, "w", encoding="utf-8") as f:
        ryaml.dump(alm, f)

    print(f"\n✅ {len(skrevne)} måned(er) skrevet til {almanak_sti.name}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # hent-fotos delegerer til haven.fotos inkl. alle dens flags
    if len(sys.argv) >= 2 and sys.argv[1] == "hent-fotos":
        subprocess.run([sys.executable, "-m", "haven.fotos"] + sys.argv[2:])
        sys.exit(0)

    # hent-havefotos delegerer til haven.havefotos inkl. alle dens flags
    if len(sys.argv) >= 2 and sys.argv[1] == "hent-havefotos":
        subprocess.run([sys.executable, "-m", "haven.havefotos"] + sys.argv[2:])
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="have — generer HTML + indeks for hele haven.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Eksempler:\n  have build\n  have deploy\n  have init\n  have check"
    )
    parser.add_argument("--version", action="version",
                        version=f"have {__version__}")
    subparsers = parser.add_subparsers(dest="kommando")

    # Subkommando: init
    init_parser = subparsers.add_parser("init", help="Sæt aktuelle mappe op som haveprojekt")
    init_parser.add_argument("--ja", "-j", action="store_true",
                             help="Acceptér alle defaults uden at spørge (til CI og test)")

    # Subkommando: område
    subparsers.add_parser("område", help="Opret nyt havområde i aktuelle projekt")

    # Subkommando: check
    subparsers.add_parser("opdater-schema", help="Opdater plante_id-enum i bed.schema.json fra planter.yaml")
    check_parser = subparsers.add_parser("check", help="Validér planter.yaml og krydsreferencér mod bede")
    check_parser.add_argument("--strict", action="store_true",
                              help="Behandl advarsler som fejl (nyttigt inden upload)")
    check_parser.add_argument("--farver", action="store_true",
                              help="Vis farvetabel for alle planter")

    # Subkommando: nyt-år
    nyt_år_parser = subparsers.add_parser("nyt-år", help="Klargør ny sæson (fx: have nyt-år 2027)")
    nyt_år_parser.add_argument("år", type=int, help="Det nye år (fx 2027)")

    # Subkommando: ny-plante
    subparsers.add_parser("ny-plante", help="Opret ny plante i planter.yaml (interaktiv wizard)")

    subparsers.add_parser("ret-i-plante-yaml", help="Ret en eksisterende plante i planter.yaml (interaktiv wizard)")

    # Subkommando: hent-fotos
    subparsers.add_parser("hent-fotos", help="Hent plantefotos fra Wikimedia")

    # Subkommando: hent-havefotos
    subparsers.add_parser("hent-havefotos", help="Tjek og synkronisér almanakfotos i entries")

    # Subkommando: nyt-bed
    subparsers.add_parser("nyt-bed", help="Tilføj nyt bed til en zone-YAML-fil (interaktiv wizard)")

    # Subkommando: ny-entry
    subparsers.add_parser("ny-entry", help="Opret ny dagbogsentry (interaktiv wizard)")

    # Subkommando: plant-en-plante
    subparsers.add_parser("plant-en-plante", help="Plant en plante i et eksisterende bed (interaktiv wizard)")

    subparsers.add_parser("riv-en-plante-op", help="Fjern en zone/plante fra et eksisterende bed (interaktiv wizard)")

    subparsers.add_parser("ret-en-plante", help="Ret en eksisterende zone/plante i et bed (interaktiv wizard)")

    subparsers.add_parser("ret-bed", help="Omfordel zone-bredder og tilføj nye zoner med ratio (interaktiv wizard)")

    # Subkommando: hons — hønsemodul med underkommandoer
    hons_parser = subparsers.add_parser("hons", help="Hønsemodul — observationer og dyreregister")
    hons_sub = hons_parser.add_subparsers(dest="hons_kommando")
    hons_sub.add_parser("ny-obs", help="Registrér en hønse-observation (interaktiv wizard)")
    hons_sub.add_parser("ny-høne", help="Tilføj ny høne til dyr.yaml (interaktiv wizard)")

    # Subkommando: build (alias for default)
    subparsers.add_parser("build", help="Generer alle HTML-sider (alias for: have uden argumenter)")

    # Subkommando: deploy
    subparsers.add_parser("deploy", help="Generer alle sider og upload til server (protokol sat i haven.yaml)")

    # Subkommando: hent-vejr
    hent_vejr_parser = subparsers.add_parser("hent-vejr", help="Hent historisk vejrdata fra Open-Meteo og skriv til almanak.yaml")
    hent_vejr_parser.add_argument("--år", type=int, default=datetime.date.today().year,
                                  help="Årstal der hentes for (standard: indeværende år)")
    hent_vejr_parser.add_argument("--force", action="store_true",
                                  help="Overskriv eksisterende måneder og inkludér indeværende måned")

    # Subkommando: watch
    watch_parser = subparsers.add_parser("watch", help="Filwatcher der genbygger ved ændringer (livereload)")
    watch_parser.add_argument("--port", type=int, default=5500, help="Port til livereload-server (standard: 5500)")

    # Standard: generer
    parser.add_argument("yaml", nargs="*", default=None)
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    yaml_filer = args.yaml if args.yaml else _find_yaml_filer()

    if args.kommando == "init":
        init_projekt(ja=args.ja)
        sys.exit(0)

    if args.kommando == "område":
        nyt_område()
        sys.exit(0)

    if args.kommando == "opdater-schema":
        PLANTE_DB.update(byg_plante_db(PLANTER_FIL))
        opdater_schema_plante_ids(PLANTE_DB)
        opdater_schema_planter()
        sys.exit(0)

    if args.kommando == "check":
        check(yaml_filer, strict=getattr(args, "strict", False),
              farver=getattr(args, "farver", False))
        sys.exit(0)

    if args.kommando == "nyt-år":
        nyt_år(args.år)
        sys.exit(0)

    if args.kommando == "ny-plante":
        ny_plante()
        sys.exit(0)

    if args.kommando == "ret-i-plante-yaml":
        ret_i_plante_yaml()
        sys.exit(0)

    if args.kommando == "nyt-bed":
        nyt_bed()
        sys.exit(0)

    if args.kommando == "ny-entry":
        ny_entry()
        sys.exit(0)

    if args.kommando == "plant-en-plante":
        plant_en_plante()
        sys.exit(0)

    if args.kommando == "riv-en-plante-op":
        riv_en_plante_op()
        sys.exit(0)

    if args.kommando == "ret-en-plante":
        ret_en_plante()
        sys.exit(0)

    if args.kommando == "ret-bed":
        ret_bed()
        sys.exit(0)

    if args.kommando == "hons":
        hk = getattr(args, "hons_kommando", None)
        if hk == "ny-obs":
            hons_ny_obs()
        elif hk == "ny-høne":
            hons_ny_høne()
        else:
            hons_parser.print_help()
        sys.exit(0)

    if args.kommando == "hent-vejr":
        hent_vejr(args.år, force=args.force)
        sys.exit(0)

    if args.kommando == "deploy":
        upload_filer = generer_alle(_find_yaml_filer())
        if DEPLOY_PROTOKOL == "ftp":
            upload_ftp(upload_filer)
        elif DEPLOY_PROTOKOL == "sftp":
            upload(upload_filer)
        else:
            print("ℹ️  Upload sprunget over — sæt deploy.protokol til 'sftp' eller 'ftp' i haven.yaml")
        sys.exit(0)

    if args.kommando == "watch":
        from livereload import Server
        import subprocess as _sp

        def _byg():
            _sp.run(["have", "build"])

        _server = Server()
        _server.watch("data/**/*.yaml", _byg)
        _server.watch("data/*.yaml", _byg)
        _server.watch("out/**/*.html")
        _server.serve(root="out/", port=args.port, open_url_delay=1)
        sys.exit(0)

    upload_filer = generer_alle(yaml_filer)



if __name__ == "__main__":
    main()
