"""haven.gennemgang.kommando — 'have gennemgang …' på kommandolinjen.

cli.py kalder kun tilføj_parser() og kør(); resten af argparse-opsætningen
bor her, så cli.py ikke vokser med hver ny underkommando.

  have gennemgang [--år N]            status: hvad er gjort, hvad mangler
  have gennemgang opret [--år N]      opret manglende skabeloner (overskriver aldrig)
  have gennemgang vis NAVN [--år N]   fakta om et bed (filnavn) eller en sort (plante_id)
  have gennemgang vejr [--år N]       årets vejr mod normalåret
"""

import argparse
import sys

from ..kontekst import AKTIVT_ÅR, PLANTE_DB
from ..indlaes import byg_plante_db, byg_skadedyr_db
from . import fakta, filer, status, vejr_normal, visning
from .stier import DATA_ROD, bed_fil

__all__ = ["tilføj_parser", "kør"]


def tilføj_parser(subparsers) -> None:
    fælles = argparse.ArgumentParser(add_help=False)
    # SUPPRESS: ellers overskriver underkommandoens standard et --år givet før den.
    fælles.add_argument("--år", type=int, default=argparse.SUPPRESS,
                        help=f"året, der gennemgås (standard: aktivt_år = {AKTIVT_ÅR})")

    p = subparsers.add_parser("gennemgang", parents=[fælles],
                              help="Årsgennemgang: evaluér året bed for bed, sort for sort")
    under = p.add_subparsers(dest="gennemgang_kommando")
    under.add_parser("opret", parents=[fælles],
                     help="Opret manglende filer i data/<år>/gennemgang/ (overskriver aldrig)")
    vis = under.add_parser("vis", parents=[fælles],
                           help="Vis fakta om et bed eller en sort")
    vis.add_argument("navn", help="bedfilens navn (fx højbedshaven-bed-1) eller et plante_id")
    under.add_parser("vejr", parents=[fælles], help="Årets vejr mod normalåret 1991–2020")


def _opret(år: int) -> None:
    områder = fakta.områder(år)
    oprettede = []
    for o in områder:
        for bed in (o.bede or [None]):
            if filer.opret_bed(år, o, bed):
                oprettede.append(bed_fil(år, o.fil, bed.id if bed else None).name)
    for pid in fakta.sorter(områder):
        if filer.opret_sort(år, pid, PLANTE_DB.get(pid)):
            oprettede.append(f"sorter/{pid}.md")
    if filer.opret_erfaringer(år):
        oprettede.append(f"erfaringer.md (afsnit ## {år})")
    visning.vis_oprettet(oprettede)


def _vis(år: int, navn: str) -> None:
    navn = navn.removesuffix(".md")
    områder = fakta.områder(år)
    alle_indlæg = fakta.indlæg(år)
    for o in områder:
        for bed in (o.bede or [None]):
            if bed_fil(år, o.fil, bed.id if bed else None).stem == navn:
                visning.vis_bed(år, o, bed, alle_indlæg)
                return
    sorter = fakta.sorter(områder)
    if navn in sorter:
        visning.vis_sort(år, navn, sorter[navn], alle_indlæg)
        return
    print(f"❌ '{navn}' er hverken et bed eller en sort i {år}.")
    print("   Se navnene med: have gennemgang")
    sys.exit(1)


def kør(args) -> None:
    år = getattr(args, "år", None) or AKTIVT_ÅR
    if not (DATA_ROD / str(år)).is_dir():
        print(f"❌ Der er ingen data for {år} ({DATA_ROD / str(år)} findes ikke).")
        sys.exit(1)
    PLANTE_DB.update(byg_plante_db())
    byg_skadedyr_db()

    hvad = args.gennemgang_kommando
    if hvad == "opret":
        _opret(år)
    elif hvad == "vis":
        _vis(år, args.navn)
    elif hvad == "vejr":
        visning.vis_vejr(år, vejr_normal.sammenlign(år))
    else:
        visning.vis_status(status.beregn(år))
