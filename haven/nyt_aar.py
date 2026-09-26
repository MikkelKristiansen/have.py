"""haven.nyt_aar — 'have nyt-år': klargør en ny sæson ud fra den forrige.

Handler-modul, udskilt fra wizards.py 26. sep 2026. Her skal årsreviewet
også kobles på: det kører netop, når et nyt år sættes op, og skal ikke gøre
wizards.py (3.600+ linjer) endnu større.

Afhænger af kontekst (stier, sædskifte, PLANTE_DB), indlaes (plante-db,
familier) og scaffold (meta-standardfelter). questionary og ruamel
importeres lokalt i funktionerne, som i resten af handler-laget.
"""

import os
import sys

from .kontekst import (DATA_MAPPE, FOTOS_MAPPE, PLANTE_DB, ROTATION_CYKLUS,
                       TUNGE_FAMILIER)
from .indlaes import byg_plante_db, find_dominerende_familier
from .scaffold import _META_FELTER_DEFAULT

__all__ = ["nyt_år"]


# Nøgler i en årsfil, der beskriver det gamle år og ikke skal med i kopien.
# temperatur: skrevet af 'have hent-vejr', som springer måneder over, der
# allerede har data — et kopieret 2026-vejr ville aldrig blive erstattet.
_KUN_DET_GAMLE_ÅR = ("temperatur",)


def nyt_år(nyt_år_num: int):
    """Klargør data/<nyt_år>/ og fotos/entries/<nyt_år>/ til den kommende sæson."""
    import shutil
    data_rod = DATA_MAPPE.parent
    # Find seneste eksisterende år-mappe før det nye år — ikke nødvendigvis år−1,
    # så et oversprunget år (fx 2024 → nyt-år 2026) stadig finder 2024 som kilde.
    tidligere_år = sorted(
        (int(p.name) for p in data_rod.iterdir()
         if p.is_dir() and p.name.isdigit() and int(p.name) < nyt_år_num),
        reverse=True,
    )
    if not tidligere_år:
        print(f"❌ Ingen tidligere år-mappe fundet i {data_rod}/ at kopiere fra.")
        sys.exit(1)
    fra_mappe = data_rod / str(tidligere_år[0])
    # Absolut, ligesom fra_mappe — ellers havner det nye år i den mappe,
    # man tilfældigvis står i, når kommandoen køres.
    til_mappe = data_rod / str(nyt_år_num)

    # Tjek før spørgsmålet: det nytter ikke at svare ja til noget, der ikke kan lade sig gøre.
    if os.path.exists(til_mappe):
        print(f"❌ {til_mappe} findes allerede.")
        sys.exit(1)

    import questionary
    print(f"\nDette vil oprette {til_mappe}/ ved at kopiere alle filer fra {fra_mappe}/")
    print(f"og nulstille entries.yaml til tom liste.\n")
    if not questionary.confirm("Er du sikker?", default=False).ask():
        print("Afbrudt.")
        sys.exit(0)

    os.makedirs(til_mappe)

    # ruamel bevarer kommentarer og formatering når vi opdaterer meta i kopierne
    from ruamel.yaml import YAML
    ryaml = YAML()
    ryaml.preserve_quotes = True

    SPRING_OVER = {"entries.yaml"}
    kopierede = []
    for fil in sorted(os.listdir(fra_mappe)):
        if not fil.endswith(".yaml") or fil.startswith(".") or fil in SPRING_OVER:
            continue
        kilde = os.path.join(fra_mappe, fil)
        mål   = os.path.join(til_mappe, fil)
        shutil.copy(kilde, mål)
        # Opdatér meta.år og backfill manglende meta-felter i kopien (in-place round-trip)
        with open(mål, encoding="utf-8") as f:
            data = ryaml.load(f)
        if isinstance(data, dict) and "meta" in data:
            data["meta"]["år"] = nyt_år_num
            for felt, standard in _META_FELTER_DEFAULT.items():
                data["meta"].setdefault(felt, standard)
            for felt in _KUN_DET_GAMLE_ÅR:
                data.pop(felt, None)
            with open(mål, "w", encoding="utf-8") as f:
                ryaml.dump(data, f)
        kopierede.append(fil)
        print(f"  📄 {fil} kopieret og opdateret til år {nyt_år_num}")

    # Tom entries.yaml
    entries_sti = os.path.join(til_mappe, "entries.yaml")
    with open(entries_sti, "w", encoding="utf-8") as f:
        f.write(f"# Haveentries {nyt_år_num}\n# Tilføj noter og fotos her.\n\nentries: []\n")
    print(f"  📄 entries.yaml oprettet (tom)")

    # Opret fotos-mappe
    fotos_mappe = FOTOS_MAPPE / "entries" / str(nyt_år_num)
    os.makedirs(fotos_mappe, exist_ok=True)
    print(f"  📁 {fotos_mappe}/ oprettet")

    print(f"\n✅ {til_mappe}/ klar til sæson {nyt_år_num}")

    # ── Sædskifteforslag (valgfrit — kun hvis rotation.cyklus er sat) ──────────
    _sædskifteforslag(tidligere_år[0], nyt_år_num)

    print(f"\nNæste skridt: Sæt aktivt_år: {nyt_år_num} i haven.yaml og rediger dine bede-filer")


def _sædskifteforslag(kilde_år: int, nyt_år_num: int) -> None:
    """Rådgiv om sædskifte for tunge familier efter nyt-år-kopieringen.

    Læser kilde-årets bede, finder hvilke der har Solanaceae/Brassicaceae, og
    foreslår det næste bed i rotation.cyklus. Ingen ændringer i YAML — kun råd.
    Springes stille over hvis rotation.cyklus ikke er sat i haven.yaml.
    """
    if not ROTATION_CYKLUS:
        return
    import questionary
    if not PLANTE_DB:
        PLANTE_DB.update(byg_plante_db())

    forslag = []
    for i, bed_navn in enumerate(ROTATION_CYKLUS):
        tunge = find_dominerende_familier(kilde_år, bed_navn) & set(TUNGE_FAMILIER)
        if tunge:
            næste_bed = ROTATION_CYKLUS[(i + 1) % len(ROTATION_CYKLUS)]
            for familie in sorted(tunge):
                forslag.append((familie, bed_navn, næste_bed))
    if not forslag:
        return

    linje = "─" * 43
    print(f"\n{linje}")
    print(f"  Sædskifteforslag for {nyt_år_num}")
    print(linje)
    for familie, bed_navn, næste_bed in forslag:
        print(f"  {familie} ({TUNGE_FAMILIER[familie]}) er i {bed_navn} i {kilde_år}.")
        print(f"  → Anbefalet bed i {nyt_år_num}: {næste_bed}\n")
    print(linje)
    print("  Husk at opdatere dine bed-YAML'er manuelt.")
    print("  have check vil advare hvis de tunge familier")
    print("  forbliver i samme bed to år i træk.")
    print(linje)
    questionary.press_any_key_to_continue("Tryk Enter for at fortsætte …").ask()
