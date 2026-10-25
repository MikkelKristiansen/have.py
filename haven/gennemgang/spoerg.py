"""haven.gennemgang.spoerg — 'have gennemgang dom': vælg dommen med piletasterne.

Dommen er et lukket sæt værdier, så den vælges fra en liste i stedet for at
blive skrevet i hånden. Den frie tekst under frontmatteren skriver Mikkel
stadig selv i filen.

Uden plante_id går den gennem alle sorter, der mangler en gyldig dom. Hvert
valg gemmes med det samme, så Ctrl-C mister intet.

Spørgsmålene stilles her; al anden udskrift ligger i visning.py, og
skrivningen i filer.sæt_felter().
"""

import questionary

from ..kontekst import PLANTE_DB
from . import fakta, status, visning
from .filer import DOMME_ETÅRIGE, DOMME_FLERÅRIGE, læs, sæt_felter
from .stier import sort_fil

__all__ = ["kør_dom"]

_SPRING_OVER = "__spring_over__"


def _vælg_dom(nuværende: str | None) -> str | None:
    """Den valgte dom, _SPRING_OVER eller None (Ctrl-C)."""
    valg = [questionary.Choice(d, value=d) for d in DOMME_ETÅRIGE]
    valg.append(questionary.Separator("── flerårige ──"))
    valg += [questionary.Choice(d, value=d) for d in DOMME_FLERÅRIGE]
    valg.append(questionary.Choice("(spring over)", value=_SPRING_OVER))
    forvalgt = next((c for c in valg if getattr(c, "value", None) == nuværende), None)
    return questionary.select("Dom:", choices=valg, default=forvalgt).ask()


def _vælg_erstatning(nuværende: str | None) -> str | None:
    """plante_id for den nye sort, "" (kan vente) eller None (Ctrl-C)."""
    navne = {pid: f"{p.get('navn', pid)}{' — ' + p['sort'] if p.get('sort') else ''}"
             for pid, p in PLANTE_DB.items()}
    svar = questionary.autocomplete(
        "Erstat med (plante_id, tom = afgør senere):",
        choices=sorted(navne), meta_information=navne, default=nuværende or "",
        validate=lambda t: t.strip() == "" or t.strip() in PLANTE_DB
                           or "Ukendt plante_id — vælg fra listen",
    ).ask()
    return None if svar is None else svar.strip()


def _én_sort(år: int, plante_id: str, nr: int, i_alt: int, alle_indlæg: list) -> bool:
    """Spørg om én sort og gem svaret. False, hvis Mikkel afbrød."""
    sti = sort_fil(år, plante_id)
    fm, _ = læs(sti)
    visning.vis_dom_hoved(år, plante_id, nr, i_alt, alle_indlæg)

    dom = _vælg_dom(fm.get("dom"))
    if dom is None:
        return False
    if dom == _SPRING_OVER:
        return True

    erstat_med = None
    if dom == "skift-sort":
        erstat_med = _vælg_erstatning(fm.get("erstat_med"))
        if erstat_med is None:
            return False
    # Ved andre domme ryddes en gammel erstat_med, så den ikke hænger ved.
    sæt_felter(sti, {"dom": dom, "erstat_med": erstat_med})
    visning.vis_dom_gemt(f"sorter/{sti.name}", dom, erstat_med)
    return True


def kør_dom(år: int, plante_id: str | None) -> bool:
    """False, hvis plante_id er ukendt eller filen mangler."""
    områder = fakta.områder(år)
    if plante_id:
        if plante_id not in fakta.sorter(områder):
            visning.vis_dom_besked(f"❌ '{plante_id}' er ikke en sort i {år}.")
            return False
        if not sort_fil(år, plante_id).exists():
            visning.vis_dom_besked("❌ Filen mangler — kør først: have gennemgang opret")
            return False
        _én_sort(år, plante_id, 1, 1, fakta.indlæg(år))
        return True

    punkter = status.beregn(år).sorter
    mangler_fil = [p for p in punkter if p.tilstand == status.MANGLER]
    if mangler_fil:
        visning.vis_dom_besked(f"ℹ️  {len(mangler_fil)} sort(er) har ingen fil endnu "
                               "— kør: have gennemgang opret")
    uden_dom = [p for p in punkter if p.tilstand == status.I_GANG]
    if not uden_dom:
        visning.vis_dom_besked("✅ Alle sorter har en dom.")
        return True

    alle_indlæg = fakta.indlæg(år)
    for nr, p in enumerate(uden_dom, 1):
        if not _én_sort(år, p.navn, nr, len(uden_dom), alle_indlæg):
            visning.vis_dom_besked("\nAfbrudt — det valgte er gemt.")
            break
    return True
