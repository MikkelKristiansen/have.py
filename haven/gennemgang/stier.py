"""haven.gennemgang.stier — hvor gennemgangens filer bor, og hvad de hedder.

Ét sted for navnereglerne, så status, opret og visning aldrig er uenige om,
hvilken fil der hører til et bed eller en sort.

  data/<år>/gennemgang/bede/<områdefil>-<bed_id>.md   ét pr. bed
  data/<år>/gennemgang/bede/<områdefil>.md            område uden bede (frugthaven)
  data/<år>/gennemgang/sorter/<plante_id>.md          én pr. sort
  data/erfaringer.md                                  vokser år for år
"""

from pathlib import Path

from ..config import PROJECT_ROOT
from ..kontekst import DATA_MAPPE

__all__ = ["DATA_ROD", "ERFARINGER_FIL", "CACHE_MAPPE",
           "gennemgang_mappe", "bed_mappe", "sort_mappe",
           "bed_fil", "sort_fil"]

# DATA_MAPPE er data/<aktivt_år>; gennemgangen kan handle om et andet år.
DATA_ROD       = DATA_MAPPE.parent
ERFARINGER_FIL = DATA_ROD / "erfaringer.md"
# Prikmappe: Drive synker den ikke, så hver maskine har sin egen cache.
CACHE_MAPPE    = PROJECT_ROOT / ".cache"


def gennemgang_mappe(år: int) -> Path:
    return DATA_ROD / str(år) / "gennemgang"


def bed_mappe(år: int) -> Path:
    return gennemgang_mappe(år) / "bede"


def sort_mappe(år: int) -> Path:
    return gennemgang_mappe(år) / "sorter"


def bed_fil(år: int, områdefil: str, bed_id: str | None) -> Path:
    """Fil for et bed — eller for hele området, når det ikke har bede."""
    navn = f"{områdefil}-{bed_id}" if bed_id else områdefil
    return bed_mappe(år) / f"{navn}.md"


def sort_fil(år: int, plante_id: str) -> Path:
    return sort_mappe(år) / f"{plante_id}.md"
