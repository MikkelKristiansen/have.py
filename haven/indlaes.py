"""haven.indlaes — indlæsning af YAML + opbygning af databaser + slug-helpers.

Lavniveau-modul i cli-opdelingen (se briefs/cli-opdeling.md, fase 2). Indeholder
YAML-loaderne, plante-/dyre-databaseopbygning, opslag og slug/id-konventionen.
Afhænger kun af kontekst + models + stdlib.

`skriv_hvis_ændret` (lavniveau fil-IO, søskende til load_yaml) bor her — ikke i
generering.py som brief-tabellen først foreslog — så højere lag (validering,
generering, wizards, deploy) alle kan importere den uden at bryde DAG'en.

VIGTIGT: opslag_plante læser PLANTE_DB (importeret fra kontekst) — det skal være
*samme objekt*; muteres aldrig her.
"""

import os
import sys
from pathlib import Path

import yaml

from .kontekst import (
    PLANTER_FIL, DYR_FIL, FRØ_FIL, PLANTE_DB, DATA_MAPPE, YAML_FILER_DEFAULT,
)

__all__ = [
    "load_yaml", "normaliser_bed_data", "load_bed_yaml", "skriv_hvis_ændret",
    "byg_plante_db", "byg_dyr_db", "load_frø", "opslag_plante", "berig_kalender_planter",
    "_dyr_label", "_slug", "slugify", "plante_id",
    "_find_yaml_filer", "_les_entries_mappe",
]


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
        # safe_load returnerer None for tomme/kommentar-kun filer; normalisér til {}
        # så kaldere trygt kan .get(...) uden NoneType-crash.
        return yaml.safe_load(tekst) or {}
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


def skriv_hvis_ændret(sti: Path, indhold: str) -> bool:
    sti = Path(sti)
    if sti.exists() and sti.read_text(encoding="utf-8") == indhold:
        return False
    sti.write_text(indhold, encoding="utf-8")
    return True


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


def load_frø() -> tuple[list, list]:
    """Returnerer (aktive, arkiverede) frøposter fra data/frø.yaml.

    Returnerer to tomme lister hvis filen mangler — frøsamlingen er valgfri.
    Aktive = rest != 'tom'; arkiverede = rest == 'tom'.
    """
    if not FRØ_FIL.exists():
        return [], []
    data = load_yaml(FRØ_FIL)
    alle = data.get("frø") or []
    aktive     = [f for f in alle if str(f.get("rest", "")) != "tom"]
    arkiverede = [f for f in alle if str(f.get("rest", "")) == "tom"]
    return aktive, arkiverede


def _dyr_label(d: dict) -> str:
    """Vis et dyr som 'navn' eller 'race farve' (til lister og overskrifter)."""
    navn = str(d.get("navn", "")).strip()
    if navn:
        return navn
    dele = [str(d.get("race", "")).strip(), str(d.get("farve", "")).strip()]
    return " ".join(p for p in dele if p) or d.get("id", "?")


# ── Slug / id-konvention ─────────────────────────────────────────────────────────

def _slug(tekst):
    """Lav et filnavn-venligt slug fra dansk tekst.

    Delegerer til slugify (samme translitteration/normalisering) og falder
    tilbage til "have" ved tom streng, så filnavne aldrig bliver tomme.
    """
    return slugify(tekst) or "have"


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


# ── Fil-opdagelse + entries-mappe ────────────────────────────────────────────────

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
