"""haven.gennemgang.filer — læs gennemgangens filer og opret skabeloner.

Filerne er markdown med en kort YAML-frontmatter, samme form som
entries/sektioner/*.md. Frontmatteren er det, maskinen skal kunne læse
(dom, køb, skadedyr); resten er fri tekst.

Skabelonerne skrives som tekst og ikke med yaml.dump, så kommentarerne med
de gyldige værdier kommer med. Der overskrives ALDRIG en eksisterende fil —
det er Mikkels tekst.
"""

import re
from pathlib import Path

import yaml

from .fakta import Område, Bed
from .stier import ERFARINGER_FIL, bed_fil, sort_fil

__all__ = ["DOMME_ETÅRIGE", "DOMME_FLERÅRIGE", "GYLDIGE_DOMME",
           "læs", "har_tekst", "opret_bed", "opret_sort", "opret_erfaringer",
           "erfaringer_har_år", "erfaringer_skrevet"]

DOMME_ETÅRIGE   = ("gentag", "skift-sort", "drop", "flyt")
DOMME_FLERÅRIGE = ("behold", "beskær", "forny", "fjern")
GYLDIGE_DOMME   = DOMME_ETÅRIGE + DOMME_FLERÅRIGE

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def læs(sti: Path) -> tuple[dict, str]:
    """(frontmatter, tekst). En fil uden gyldig frontmatter giver ({}, hele teksten)."""
    indhold = sti.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(indhold)
    if not m:
        return {}, indhold
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, indhold
    return (fm if isinstance(fm, dict) else {}), m.group(2)


def har_tekst(tekst: str) -> bool:
    """Står der andet end skabelonens overskrifter og kommentarer?"""
    for linje in tekst.splitlines():
        linje = linje.strip()
        if linje and not linje.startswith("#") and not linje.startswith("<!--"):
            return True
    return False


def _skriv_ny(sti: Path, indhold: str) -> bool:
    if sti.exists():
        return False
    sti.parent.mkdir(parents=True, exist_ok=True)
    sti.write_text(indhold, encoding="utf-8")
    return True


def opret_bed(år: int, område: Område, bed: Bed | None) -> bool:
    """Skabelon for et bed (eller et område uden bede). True hvis den blev oprettet."""
    titel = f"{område.titel} — {bed.navn}" if bed else område.titel
    bed_linje = f"bed_id: {bed.id}\n" if bed else ""
    indhold = (
        "---\n"
        f"område: {område.fil}\n"
        f"{bed_linje}"
        "færdig: false     # sæt til true, når bedet er gennemgået\n"
        "skadedyr: []      # id'er fra skadedyr.yaml\n"
        "køb: []           # jord, gødning, net, materialer — fx \"insektnet 2×5 m\"\n"
        "---\n\n"
        f"# {titel} {år}\n\n"
        "## Stedet\n"
        "<!-- Sol, skygge, vand, læ. Stod noget for tæt? -->\n\n"
        "## Jord og gødning\n\n"
        "## Skadedyr og sygdomme\n\n"
        "## Til næste år\n"
    )
    return _skriv_ny(bed_fil(år, område.fil, bed.id if bed else None), indhold)


def opret_sort(år: int, plante_id: str, plante: dict | None) -> bool:
    """Skabelon for en sort. True hvis den blev oprettet."""
    navn = plante_id
    if plante:
        navn = plante.get("navn", plante_id)
        if plante.get("sort"):
            navn += f" — {plante['sort']}"
    indhold = (
        "---\n"
        f"plante_id: {plante_id}\n"
        f"dom:              # {' | '.join(DOMME_ETÅRIGE)}\n"
        f"                  # flerårige: {' | '.join(DOMME_FLERÅRIGE)}\n"
        "erstat_med:       # plante_id — kun ved skift-sort\n"
        "skadedyr: []      # id'er fra skadedyr.yaml\n"
        "køb: []\n"
        "---\n\n"
        f"# {navn} {år}\n\n"
        "## Hvordan gik det?\n"
        "<!-- Spiring, vækst, smag, udbytte. Var det sorten eller året? -->\n\n"
        "## Næste år\n"
    )
    return _skriv_ny(sort_fil(år, plante_id), indhold)


def opret_erfaringer(år: int) -> bool:
    """Opret erfaringer.md og/eller årets afsnit. Rører aldrig eksisterende tekst."""
    if not ERFARINGER_FIL.exists():
        _skriv_ny(ERFARINGER_FIL, "# Erfaringer\n\n"
                  "Det, der stadig er rigtigt om fem år. Nyeste år øverst.\n")
    if erfaringer_har_år(år):
        return False
    # Nyt afsnit lige efter indledningen, så nyeste år står øverst.
    tekst = ERFARINGER_FIL.read_text(encoding="utf-8")
    afsnit = f"## {år}\n\n"
    m = re.search(r"^## ", tekst, re.MULTILINE)
    if m:
        tekst = tekst[:m.start()] + afsnit + tekst[m.start():]
    else:
        tekst = tekst.rstrip("\n") + "\n\n" + afsnit
    ERFARINGER_FIL.write_text(tekst, encoding="utf-8")
    return True


def _erfaringsafsnit(år: int) -> str | None:
    if not ERFARINGER_FIL.exists():
        return None
    tekst = ERFARINGER_FIL.read_text(encoding="utf-8")
    m = re.search(rf"^## {år}\s*$(.*?)(?=^## |\Z)", tekst, re.MULTILINE | re.DOTALL)
    return m.group(1) if m else None


def erfaringer_har_år(år: int) -> bool:
    return _erfaringsafsnit(år) is not None


def erfaringer_skrevet(år: int) -> bool:
    afsnit = _erfaringsafsnit(år)
    return bool(afsnit) and har_tekst(afsnit)
