#!/usr/bin/env python3
"""
have.py — Generer HTML-plan for køkkenhaven via Jinja2-skabeloner.
Læser YAML-filer og producerer HTML til webbrug og print via browser.

Brug:
  python3 have.py                    # generer HTML lokalt
  python3 have.py min.yaml           # brug alternativ YAML-fil
"""

import sys
import os
import argparse
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
    with open(sti, encoding="utf-8") as f:
        data = yaml.safe_load(f)
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
        data = load_yaml(yaml_sti)
        fil = yaml_sti.name

        for bed in data.get("bede", []):
            bed_navn = bed.get("navn") or bed.get("id") or "?"
            for zone in bed.get("zoner", []):
                for kilde in zone.get("afgrøder", [zone]):
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
    hex_farve = hex_farve.lstrip("#")
    r, g, b = (int(hex_farve[i:i+2], 16) / 255 for i in (0, 2, 4))
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
            pid = afgrøde.get("plante_id") or zone.get("plante_id")
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
            result.setdefault("farve",  p.get("farve", "#c8e6c9"))
            result["efterfølger"] = efterfølger
            return result

        afgrøder = zone.get("afgrøder")
        if not afgrøder:
            return _beret(zone)
        for i, a in enumerate(afgrøder):
            fra, til = a.get("fra", 1), a.get("til", 12)
            aktiv = (fra <= måned <= til) if fra <= til else (måned >= fra or måned <= til)
            if aktiv:
                return _beret(a, afgrøder[i + 1] if i + 1 < len(afgrøder) else None)
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

    import markdown as _md
    _md_exts = ["fenced_code"]
    env.filters["md"]             = lambda t: _md.markdown(str(t), extensions=_md_exts)
    env.filters["aktiv_afgrøde"]  = aktiv_afgrøde
    env.filters["kalender_celle"] = kalender_celle
    env.filters["dato_fmt"]       = dato_fmt
    env.filters["splitlines"]     = splitlines
    env.filters["kontrast_farve"] = kontrast_farve
    return env


# ── YAML ───────────────────────────────────────────────────────────────────────

def load_yaml(sti):
    with open(sti, encoding="utf-8") as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"❌ YAML-fejl i {sti}:")
            if hasattr(e, "problem_mark"):
                m = e.problem_mark
                print(f"   Linje {m.line + 1}, kolonne {m.column + 1}: {e.problem}")
            else:
                print(f"   {e}")
            sys.exit(1)


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
    data      = load_yaml(yaml_sti)
    html_navn = data["meta"].get("html_navn", yaml_sti.replace(".yaml", ""))

    # Filtrér planter til kun dem der er relevante for denne side
    relevante_ids = set()
    for bed in data.get("bede", []):
        for zone in bed.get("zoner", []):
            for kilde in zone.get("afgrøder", [zone]):
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
                try:
                    måned_nr = int(str(e_kopi["dato"]).split("-")[1])
                    almanak_måneder[måned_nr - 1]["entries"].append(e_kopi)
                except (KeyError, IndexError, ValueError):
                    pass
        # Indlæs entries fra markdown-mappe
        entries_mappe = os.path.join(_data_mappe, "entries")
        for e in _les_entries_mappe(entries_mappe):
            if (e.get("zone") or e.get("område_id", "")) != html_navn:
                continue
            e_kopi = dict(e)
            if hasattr(e_kopi.get("dato"), "isoformat"):
                e_kopi["dato"] = e_kopi["dato"].isoformat()
            try:
                måned_nr = int(str(e_kopi["dato"]).split("-")[1])
                almanak_måneder[måned_nr - 1]["entries"].append(e_kopi)
            except (KeyError, IndexError, ValueError):
                pass
        # Sortér entries nyeste først
        for mån in almanak_måneder:
            mån["entries"].sort(key=lambda e: str(e["dato"]), reverse=True)
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
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(html_sti, output):
        print(f"✅ HTML genereret: {html_sti}")
    else:
        print(f"ℹ️  HTML uændret: {html_sti}")



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
    område_titler: dict[str, str] = {}
    for oid, alm in projekter_data:
        yaml_sti_søg = next((y for y in YAML_FILER_DEFAULT if oid in str(y)), None)
        if yaml_sti_søg and os.path.exists(yaml_sti_søg):
            meta = load_yaml(yaml_sti_søg).get("meta", {})
            område_titler[oid] = meta.get("titel", oid)

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
            måneder[måned_nr - 1]["entries"].append(e_kopi)

    # Indlæs entries fra markdown-mappe
    entries_mappe_md = Path(_entries_fil).parent / "entries"
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
        måneder[måned_nr - 1]["entries"].append(e_kopi)

    # Sortér entries inden for hver måned
    for mån in måneder:
        mån["entries"].sort(key=lambda e: str(e["dato"]), reverse=True)

    return måneder


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
    if os.path.exists(_almanak_fil):
        alm = load_yaml(_almanak_fil)
        år_fra_yaml = alm.get("meta", {}).get("år")
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
        data  = load_yaml(yaml_sti)
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
                for kilde in zone.get("afgrøder", [zone]):
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
            if yaml_fil.name in ("almanak.yaml", "entries.yaml", "planter.yaml"):
                continue
            data = load_yaml(str(yaml_fil))
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
                    afgrøder_liste = zone.get("afgrøder") or []
                    if not afgrøder_liste and zone.get("plante_id"):
                        afgrøder_liste = [zone]
                    for afgrøde in afgrøder_liste:
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
          f"hent_plantefotos.py kan ikke søge dem")
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
            E(f"{yaml_sti} mangler — ret YAML_FILER_DEFAULT i have.py "
              f"eller opret filen med: have område")
            continue

        data  = load_yaml(yaml_sti)
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
              f"opdatér meta.år i filen eller AKTIVT_ÅR i have.py")

        # plante_id krydsreferencer
        ukendte = []
        for bed in data.get("bede", []):
            bed_navn = bed.get("navn", "?")
            for zone in bed.get("zoner", []):
                for kilde in zone.get("afgrøder", [zone]):
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


def _find_yaml_filer():
    """Find projektets YAML-filer i DATA_MAPPE automatisk. Fallback: YAML_FILER_DEFAULT."""
    SYSTEM_FILER = {"planter.yaml", "almanak.yaml", "entries.yaml"}
    if os.path.isdir(DATA_MAPPE):
        filer = sorted(
            os.path.join(DATA_MAPPE, f)
            for f in os.listdir(DATA_MAPPE)
            if f.endswith(".yaml") and f not in SYSTEM_FILER
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
        or any(f for f in os.listdir("data") if f.endswith(".yaml") and f != "planter.yaml")
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

    with open(os.path.join(data_år_sti, "entries.yaml"), "w", encoding="utf-8") as f:
        f.write(f"# Haveentries {år}\n# Tilføj noter og fotos her.\n\nentries: []\n")

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
        if not fil.endswith(".yaml") or fil in SPRING_OVER:
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
        if f.endswith(".yaml")
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
                  f"(ret YAML_FILER_DEFAULT eller kør: have område)",
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
                plante_id: str = None, foto_kilde: str = None,
                _generer: bool = True) -> str:
    """Opretter en dagbogsentry som markdown-fil. Returnerer stien til filen."""
    import shutil
    entries_mappe = os.path.join(DATA_MAPPE, "entries")
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

    linjer = ["---", f"dato: {dato}", f"zone: {zone}"]
    if plante_id:
        linjer.append(f"plante_id: {plante_id}")
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
    plante_choices = [questionary.Choice(title="(ingen)", value=None)]
    plante_choices += [
        questionary.Choice(title=f"{p.get('navn', '?')} ({p.get('id', '?')})", value=p.get("id"))
        for p in planter
    ]
    plante_id = questionary.select("Plante (valgfri):", choices=plante_choices).ask()

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

    # ── id ────────────────────────────────────────────────────────────────────
    def _valider_pid(v):
        v = v.strip()
        if not v:
            return "id er påkrævet"
        if not _re.match(r"^[a-z0-9-]+$", v):
            return "id må kun indeholde [a-z0-9-]"
        if v in kendte_ids:
            return f"{v!r} eksisterer allerede"
        return True

    pid = (questionary.text("Plante-id (fx 'spinat'):", validate=_valider_pid).ask() or "").strip()
    if not pid:
        sys.exit(0)

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
    plante["foto"] = foto

    gem_pid, yaml_blok = opret_plante(plante)
    print(f"\n✓ Plante gemt: {gem_pid}")
    print(f"  Fil: {PLANTER_FIL}\n")
    print("─" * 40)
    print(yaml_blok.rstrip())
    print("─" * 40)
    print("\n  Redigér planter.yaml direkte for at justere værdierne.")
    print("  Kør 'have' for at opdatere sitet, eller 'have check' for at validere.")


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
            plante_id = fm.get("plante_id")
            plante = plante_db.get(plante_id, {}) if plante_id else {}
            navn = None
            if plante:
                navn = plante.get("navn", "")
                sort = plante.get("sort", "")
                if sort:
                    navn = f"{navn} – {sort}"
            bed_titel = zone_titler.get(zone, zone)
            søg_data.append({
                "type":      "entry",
                "år":        år,
                "dato":      dato_str,
                "bed":       zone,
                "bed_titel": bed_titel,
                "plante_id": plante_id,
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
                d = load_yaml(str(yaml_fil))
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
                        pids: set[str] = set()
                        if zone.get("plante_id"):
                            pids.add(zone["plante_id"])
                        for afg in zone.get("afgrøder", []):
                            if afg.get("plante_id"):
                                pids.add(afg["plante_id"])
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

    entries_del  = [e for e in søg_data if e["type"] == "entry"]
    bedeplaner_del = [e for e in søg_data if e["type"] == "bedeplan"]
    entries_del.sort(key=lambda e: e["dato"], reverse=True)
    bedeplaner_del.sort(key=lambda e: (-e["år"], e["bed"], e.get("navn", "")))
    søg_data = entries_del + bedeplaner_del
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
            if len(resultater) >= maks:
                break
    return resultater


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
        print(f"  ✓ Zone '{zone_navn}' tilføjet ({valgt_plante['id'] if 'plante_id' in zone else 'sædskifte'})")

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
        description="have.py — generer HTML + indeks for hele haven.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Eksempler:\n  python3 have.py\n  python3 have.py deploy\n  python3 have.py init"
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

    # Subkommando: hent-fotos
    subparsers.add_parser("hent-fotos", help="Hent plantefotos fra Wikimedia")

    # Subkommando: hent-havefotos
    subparsers.add_parser("hent-havefotos", help="Tjek og synkronisér almanakfotos i entries")

    # Subkommando: nyt-bed
    subparsers.add_parser("nyt-bed", help="Tilføj nyt bed til en zone-YAML-fil (interaktiv wizard)")

    # Subkommando: ny-entry
    subparsers.add_parser("ny-entry", help="Opret ny dagbogsentry (interaktiv wizard)")

    # Subkommando: build (alias for default)
    subparsers.add_parser("build", help="Generer alle HTML-sider (alias for: have uden argumenter)")

    # Subkommando: deploy
    subparsers.add_parser("deploy", help="Generer alle sider og upload til server (protokol sat i haven.yaml)")

    # Subkommando: watch
    watch_parser = subparsers.add_parser("watch", help="Filwatcher der genbygger ved ændringer (livereload)")
    watch_parser.add_argument("--port", type=int, default=5500, help="Port til livereload-server (standard: 5500)")

    # Standard: generer
    parser.add_argument("yaml", nargs="*", default=None)
    args = parser.parse_args()

    yaml_filer = args.yaml if args.yaml else _find_yaml_filer()

    if args.kommando == "init":
        init_projekt(ja=args.ja)
        sys.exit(0)

    if args.kommando == "område":
        nyt_område()
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

    if args.kommando == "nyt-bed":
        nyt_bed()
        sys.exit(0)

    if args.kommando == "ny-entry":
        ny_entry()
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
            _sp.run(["python", "have.py"])

        _server = Server()
        _server.watch("data/*.yaml", _byg)
        _server.watch("out/*.html")
        _server.serve(root="out/", port=args.port, open_url_delay=1)
        sys.exit(0)

    upload_filer = generer_alle(yaml_filer)



if __name__ == "__main__":
    main()
