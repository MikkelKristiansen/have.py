"""haven.gennemgang.fakta — det faktuelle grundlag for et års gennemgang.

Samler, hvad året *var*: hvilke bede og sorter der stod hvor, hvad
dagbogen siger om dem, og hvilke tunge familier der stod i hvert område.
Intet her vurderer noget, og intet gemmes — det udledes af data/<år>/ hver
gang, så en rettelse i et indlæg slår igennem med det samme.

Læser kun gennem kontekst + indlaes. PLANTE_DB skal være fyldt af kalderen
(kommando.py), som i resten af have.py.
"""

from dataclasses import dataclass, field

from ..kontekst import _config, PLANTE_DB, SKADEDYR_DB, TUNGE_FAMILIER
from ..indlaes import (load_yaml, load_bed_yaml, _les_entries_mappe,
                       find_dominerende_familier, skadedyr_for_plante)
from .stier import DATA_ROD

__all__ = ["Afgrøde", "Bed", "Område", "Sted",
           "områder", "sorter", "indlæg", "indlæg_for_område", "indlæg_for_sort",
           "tunge_familier", "kendte_skadedyr"]


@dataclass
class Afgrøde:
    plante_id: str
    zone: str
    fra: int | None = None
    til: int | None = None


@dataclass
class Bed:
    id: str
    navn: str
    noter: str = ""
    afgrøder: list[Afgrøde] = field(default_factory=list)


@dataclass
class Område:
    fil: str          # filnavn uden .yaml, fx "højbedshaven"
    html_navn: str    # det id, dagbogsindlæggene bruger, fx "hoejbede"
    titel: str
    bede: list[Bed] = field(default_factory=list)
    # Områder uden bede (frugthaven) har kun en liste af planter.
    løse_planter: list[str] = field(default_factory=list)


@dataclass
class Sted:
    """Hvor en sort stod: et område, evt. et bed og en zone."""
    område: Område
    bed: Bed | None
    afgrøde: Afgrøde | None


def områder(år: int) -> list[Område]:
    """Årets planteområder i haven.yaml's rækkefølge. Husdyr (hønsene) er udeladt."""
    resultat = []
    for navn in _config.get("bede") or []:
        sti = DATA_ROD / str(år) / f"{navn}.yaml"
        if not sti.exists():
            continue
        data = load_bed_yaml(sti)
        meta = data.get("meta") or {}
        if meta.get("type") == "husdyr":
            continue
        område = Område(fil=navn,
                        html_navn=meta.get("html_navn", navn),
                        titel=meta.get("titel", navn))
        for b in data.get("bede") or []:
            bed = Bed(id=b.get("id", ""), navn=b.get("navn", b.get("id", "")),
                      noter=b.get("noter") or "")
            for zone in b.get("zoner") or []:
                for a in zone.get("afgrøder") or []:
                    if a.get("plante_id"):
                        bed.afgrøder.append(Afgrøde(a["plante_id"], zone.get("navn", ""),
                                                    a.get("fra"), a.get("til")))
            område.bede.append(bed)
        if not område.bede:
            område.løse_planter = list(data.get("kalender_planter") or [])
        resultat.append(område)
    return resultat


def sorter(alle_områder: list[Område]) -> dict[str, list[Sted]]:
    """plante_id → alle steder, sorten stod i året. Rækkefølge: første forekomst."""
    resultat: dict[str, list[Sted]] = {}
    for område in alle_områder:
        for bed in område.bede:
            for a in bed.afgrøder:
                resultat.setdefault(a.plante_id, []).append(Sted(område, bed, a))
        for pid in område.løse_planter:
            resultat.setdefault(pid, []).append(Sted(område, None, None))
    return resultat


def indlæg(år: int) -> list[dict]:
    """Årets dagbogsindlæg — markdown-filerne og evt. entries.yaml — sorteret efter dato."""
    år_mappe = DATA_ROD / str(år)
    alle = _les_entries_mappe(str(år_mappe / "entries" / "sektioner"))
    entries_fil = år_mappe / "entries.yaml"
    if entries_fil.exists():
        for e in load_yaml(entries_fil).get("entries") or []:
            e = dict(e)
            pid = e.get("plante_id")
            e["plante_id"] = [pid] if isinstance(pid, str) else list(pid or [])
            e.setdefault("område_id", e.get("zone"))
            alle.append(e)
    return sorted(alle, key=lambda e: str(e.get("dato", "")))


def indlæg_for_område(alle: list[dict], område: Område) -> list[dict]:
    return [e for e in alle if e.get("område_id") == område.html_navn]


def indlæg_for_sort(alle: list[dict], plante_id: str) -> list[dict]:
    return [e for e in alle if plante_id in e.get("plante_id", [])]


def tunge_familier(år: int, område: Område) -> dict[int, list[str]]:
    """Tunge familier (sædskiftet) i området i år og året før: {år: [etiketter]}.

    Et år uden data for området er udeladt — ellers ligner det "ingen tunge familier".
    """
    resultat = {}
    for å in (år - 1, år):
        if not (DATA_ROD / str(å) / f"{område.fil}.yaml").exists():
            continue
        familier = find_dominerende_familier(å, område.fil)
        resultat[å] = [TUNGE_FAMILIER[f] for f in sorted(familier) if f in TUNGE_FAMILIER]
    return resultat


def kendte_skadedyr(plante_id: str) -> list[dict]:
    """Skadedyr, der ifølge skadedyr.yaml rammer sorten (via familie eller direkte)."""
    plante = PLANTE_DB.get(plante_id)
    return skadedyr_for_plante(plante, SKADEDYR_DB) if plante else []
