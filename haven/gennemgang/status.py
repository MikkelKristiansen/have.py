"""haven.gennemgang.status — hvad er gjort, og hvad mangler?

Status udledes af filernes indhold hver gang. Der er ingen tjekliste ved
siden af, der kan komme ud af trit:

  bed   færdig, når frontmatter har færdig: true
  sort  færdig, når frontmatter har en gyldig dom
  år    erfaringer færdige, når data/erfaringer.md har tekst under '## <år>'

Ingen udskrift her — se visning.py.
"""

import datetime
from dataclasses import dataclass, field
from pathlib import Path

from ..kontekst import AKTIVT_ÅR, SKADEDYR_DB
from . import fakta
from .filer import GYLDIGE_DOMME, læs, erfaringer_skrevet
from .stier import bed_fil, sort_fil

__all__ = ["MANGLER", "I_GANG", "FÆRDIG", "Punkt", "Status", "beregn"]

MANGLER = "mangler fil"
I_GANG  = "i gang"
FÆRDIG  = "færdig"


@dataclass
class Punkt:
    navn: str          # det, der vises: "Højbed 1" eller "kartoffel-sava"
    sti: Path
    tilstand: str      # MANGLER / I_GANG / FÆRDIG
    problemer: list[str] = field(default_factory=list)


@dataclass
class Status:
    år: int
    bede: list[Punkt]
    sorter: list[Punkt]
    erfaringer: bool
    påmindelser: list[str]

    def næste(self) -> Punkt | str | None:
        """Det næste, der skal gennemgås, i den foreslåede rækkefølge."""
        for p in self.bede + self.sorter:
            if p.tilstand != FÆRDIG:
                return p
        if not self.erfaringer:
            return "erfaringer"
        return None


def _ukendte_skadedyr(fm: dict) -> list[str]:
    ids = fm.get("skadedyr") or []
    if not isinstance(ids, list):
        return ["skadedyr: skal være en liste"]
    return [f"ukendt skadedyr: {sid}" for sid in ids if sid not in SKADEDYR_DB]


def _bed_punkt(navn: str, sti: Path) -> Punkt:
    if not sti.exists():
        return Punkt(navn, sti, MANGLER)
    fm, _ = læs(sti)
    tilstand = FÆRDIG if fm.get("færdig") is True else I_GANG
    return Punkt(navn, sti, tilstand, _ukendte_skadedyr(fm))


def _sort_punkt(plante_id: str, sti: Path) -> Punkt:
    if not sti.exists():
        return Punkt(plante_id, sti, MANGLER)
    fm, _ = læs(sti)
    problemer = _ukendte_skadedyr(fm)
    dom = fm.get("dom")
    if dom is None:
        tilstand = I_GANG
    elif dom not in GYLDIGE_DOMME:
        tilstand = I_GANG
        problemer.append(f"ukendt dom: {dom}")
    else:
        tilstand = FÆRDIG
        if dom == "skift-sort" and not fm.get("erstat_med"):
            problemer.append("skift-sort uden erstat_med (kan vente til planen)")
    return Punkt(plante_id, sti, tilstand, problemer)


def _påmindelser(år: int, i_dag: datetime.date) -> list[str]:
    if AKTIVT_ÅR == år and i_dag >= datetime.date(år + 1, 1, 1):
        return [f"Det er {i_dag.year} — husk at sætte aktivt_år: {år + 1} i haven.yaml"]
    return []


def beregn(år: int, i_dag: datetime.date | None = None) -> Status:
    områder = fakta.områder(år)
    bede = []
    for o in områder:
        if o.bede:
            for b in o.bede:
                bede.append(_bed_punkt(f"{o.titel} — {b.navn}", bed_fil(år, o.fil, b.id)))
        else:
            bede.append(_bed_punkt(o.titel, bed_fil(år, o.fil, None)))
    sorter = [_sort_punkt(pid, sort_fil(år, pid)) for pid in fakta.sorter(områder)]
    return Status(år, bede, sorter, erfaringer_skrevet(år),
                  _påmindelser(år, i_dag or datetime.date.today()))
