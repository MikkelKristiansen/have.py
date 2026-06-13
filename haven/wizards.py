"""haven.wizards — interaktive CLI-wizards + ikke-interaktive opret-kerner.

Handler-modul i cli-opdelingen (se briefs/cli-opdeling.md, fase 5). Samler alle
interaktive kommandoer (init, nyt-område, nyt-år, ny-entry, ny-plante, ret-*,
ny-bed, hønse-wizards) samt de ikke-interaktive kerner opret_entry/opret_hons_entry/
opret_plante (sidstnævnte bruges også af hent-inbox i fase 6).

Afhænger af de lavere lag (kontekst, indlaes, scaffold, soeg, hoens, deploy) +
config + models + wikidata. opret_entry/opret_hons_entry kalder orkestratoren
generer_alle via lazy import (bryder cyklen; repointes til .byg i fase 6).
"""

import os
import sys
import subprocess
import datetime
from pathlib import Path

import yaml

from .config import sti, PROJECT_ROOT, data_mappe, out_mappe
from .models import Plante, FotoModel, Høne
from .wikidata import (wikidata_søg, wikidata_hent_plantedata,
                       wikidata_hent_foto_url, wikidata_hent_foto_metadata)
from .kontekst import *          # noqa: F401,F403  konstanter + PLANTE_DB/DYR_DB/HONS_TYPER
from .kontekst import _config    # noqa: F401
from .indlaes import *           # noqa: F401,F403  load_yaml, db-byggere, slug, _les_entries_mappe
from .scaffold import *          # noqa: F401,F403  init-skabeloner + _lav_*
from .soeg import *              # noqa: F401,F403  _søg_planter, _plante_label, generer_søg_json
from .hoens import *             # noqa: F401,F403  _markér_dyr_inaktiv, generer_hons_*
from .deploy import *            # noqa: F401,F403  _opdater_haven_yaml/_opdater_ftp_config

__all__ = [
    "init_projekt", "nyt_område", "nyt_år",
    "opret_entry", "opret_hons_entry", "ny_entry", "ret_entry",
    "opret_plante", "ny_plante", "ret_i_plante_yaml", "ret_foto", "nyt_bed",
    "hons_ny_høne", "hons_ny_obs", "plant_en_plante",
    "riv_en_plante_op", "ret_en_plante", "ret_bed",
    "wizard_ny_frø",
]


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
        # ruamel bevarer kommentarer og formatering i den eksisterende almanak
        from ruamel.yaml import YAML
        ryaml = YAML()
        ryaml.preserve_quotes = True
        with open(ALMANAK_FIL, encoding="utf-8") as f:
            data = ryaml.load(f) or {}
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
            ryaml.dump(data, f)
        print(f"✅ Opdateret: {ALMANAK_FIL}")
    else:
        print(f"ℹ️  {ALMANAK_FIL} ikke fundet — spring almanak over.")

    print(f"\n   Husk at tilføje til bede-listen i haven.yaml:")
    print(f'   - {om["html_navn"]}')


# ── Nyt år ────────────────────────────────────────────────────────────────────

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
    fotos_mappe = os.path.join("fotos", "entries", str(nyt_år_num))
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
        fotos_entries_kilde = FOTOS_MAPPE / "entries" / str(AKTIVT_ÅR)
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
        # Lazy import: byg importerer render-laget (ikke wizards), så en top-level
        # import ville også gå — men lazy holder importgrafen triviel og robust.
        from .byg import generer_alle
        generer_alle()

    return str(sti)


def opret_hons_entry(dato: str, hons_type: str, høne=None, noter: str = "",
                     foto_kilde: str = None, ekstra: dict = None,
                     _generer: bool = True) -> str:
    """Opretter en hønse-entry som YAML i entries/hons/. Returnerer stien.

    Spejler opret_entry: foto kopieres til fotos/entries/{år}/ med thumbnail.
    ekstra = dict med type-specifikke felter (fx {'æg': 3}). Tomme værdier dropppes.
    """
    import shutil
    entries_mappe = os.path.join(DATA_MAPPE, "entries", "hons")
    os.makedirs(entries_mappe, exist_ok=True)

    basis = f"{dato}-{hons_type}"
    sti   = os.path.join(entries_mappe, f"{basis}.yaml")
    n     = 2
    while os.path.exists(sti):
        sti = os.path.join(entries_mappe, f"{basis}-{n}.yaml")
        n  += 1

    foto_navn = None
    if foto_kilde:
        fotos_entries_kilde = FOTOS_MAPPE / "entries" / str(AKTIVT_ÅR)
        os.makedirs(fotos_entries_kilde, exist_ok=True)
        ext       = os.path.splitext(foto_kilde)[1]
        foto_navn = os.path.splitext(os.path.basename(sti))[0] + ext
        foto_dest = os.path.join(fotos_entries_kilde, foto_navn)
        shutil.copy2(foto_kilde, foto_dest)
        try:
            from PIL import Image, ImageOps
            foto_dest_sti = Path(foto_dest)
            thumbs_mappe = foto_dest_sti.parent / "thumbs"
            thumbs_mappe.mkdir(exist_ok=True)
            with Image.open(foto_dest_sti) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((400, 400))
                if foto_dest_sti.suffix.lower() in (".jpg", ".jpeg"):
                    img.save(thumbs_mappe / foto_dest_sti.name, "JPEG", quality=82, optimize=True)
                else:
                    img.save(thumbs_mappe / foto_dest_sti.name, optimize=True)
        except Exception as e:
            print(f"⚠️  Thumbnail ikke genereret: {e}")

    entry: dict = {"dato": dato, "type": hons_type}
    if høne:
        entry["høne"] = høne
    for k, v in (ekstra or {}).items():
        if v not in (None, ""):
            entry[k] = v
    if noter:
        entry["noter"] = noter
    if foto_navn:
        entry["foto"] = foto_navn

    with open(sti, "w", encoding="utf-8") as f:
        yaml.dump(entry, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if _generer:
        # Lazy import: byg importerer render-laget (ikke wizards), så en top-level
        # import ville også gå — men lazy holder importgrafen triviel og robust.
        from .byg import generer_alle
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
    zoner = []  # (html_navn, titel, er_husdyr)
    for yaml_sti in yaml_filer:
        if not os.path.exists(yaml_sti):
            continue
        meta = load_yaml(yaml_sti).get("meta", {})
        html_navn = meta.get("html_navn")
        if html_navn:
            er_husdyr = meta.get("type") == "husdyr"
            zoner.append((html_navn, meta.get("titel", html_navn), er_husdyr))

    zone = questionary.select(
        "Zone:",
        choices=[
            questionary.Choice(title=f"{zone_titel} ({zone_id})", value=zone_id)
            for zone_id, zone_titel, _ in zoner
        ],
    ).ask()
    if zone is None:
        sys.exit(0)

    zone_er_husdyr = next((hd for zid, _, hd in zoner if zid == zone), False)

    if zone_er_husdyr:
        hons_ny_obs(dato=dato_input)
        return
    else:
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
        plante_id = valgte_planter

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


# ── ret-entry ─────────────────────────────────────────────────────────────────

def _hons_entry_label(data: dict) -> str:
    """Kort beskrivende linje til listet valg af en hønse-entry."""
    t = data.get("type", "?")
    cfg = HONS_TYPER.get(t, {})
    ikon = cfg.get("ikon", "●")
    label = cfg.get("label", t)
    dato = data.get("dato", "?")
    ekstra = ""
    if t == "æglægning":
        ekstra = f" — {data.get('æg', '?')} æg"
    elif t == "ruge-start":
        ekstra = f" — {data.get('æg_antal', '?')} æg til rugning"
    elif t == "foderkøb":
        dele = []
        if "mængde_kg" in data:
            dele.append(f"{data['mængde_kg']} kg")
        if "foder_type" in data:
            dele.append(str(data["foder_type"]))
        if dele:
            ekstra = " — " + " ".join(dele)
    elif t == "sundhedsobs":
        obs = data.get("observation", "")
        if obs:
            ekstra = f" — {obs[:40]}"
    elif t == "dødsfald":
        if data.get("høne"):
            ekstra = f" — {data['høne']}"
    elif t == "fjerfældning":
        if data.get("fase"):
            ekstra = f" — {data['fase']}"
    elif t == "note":
        noter = data.get("noter", "")
        if noter:
            ekstra = f" — {noter[:40]}"
    return f"{dato}  {ikon} {label}{ekstra}"


def _ret_hons_entry():
    """Wizard til at rette i en eksisterende hønse-entry."""
    import io
    import re as _re
    import questionary
    from ruamel.yaml import YAML as RuamelYAML

    hons_mappe = DATA_MAPPE / "entries" / "hons"
    if not hons_mappe.exists():
        print("Ingen hønse-entries fundet.")
        return

    filer = sorted(hons_mappe.glob("*.yaml"), reverse=True)
    if not filer:
        print("Ingen hønse-entries fundet.")
        return

    entries = []
    for entry_sti in filer:
        try:
            with open(entry_sti, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict):
                entries.append((entry_sti, data))
        except Exception:
            pass

    if not entries:
        print("Ingen hønse-entries kunne læses.")
        return

    valg = questionary.select(
        "Vælg entry at rette:",
        choices=[
            questionary.Choice(title=_hons_entry_label(d), value=(p, d))
            for p, d in entries
        ],
    ).ask()
    if valg is None:
        sys.exit(0)

    entry_sti, data = valg
    t = data.get("type", "")

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

    ny = dict(data)

    if t == "æglægning":
        antal = questionary.text(
            "Antal æg:", default=str(ny.get("æg", 0)), validate=_heltal
        ).ask()
        if antal is None:
            sys.exit(0)
        ny["æg"] = int(antal)

    elif t == "ruge-start":
        db = byg_dyr_db()
        aktive = [d for d in db.values() if d.get("aktiv", True)]
        if aktive:
            labels = {f"{_dyr_label(d)} [{d['id']}]": d["id"] for d in aktive}
            nuv_høne = ny.get("høne", "")
            # find nøglen der svarer til nuværende høne-id
            nuv_label = next((k for k, v in labels.items() if v == nuv_høne), "")
            høne_valg = questionary.autocomplete(
                "Høne (rugende, tom = ingen):",
                choices=list(labels.keys()),
                default=nuv_label,
                validate=lambda v: True if not v.strip() else (v in labels)
                    or "Vælg en høne fra listen (Tab for forslag)",
            ).ask()
            if høne_valg is None:
                sys.exit(0)
            stripped = høne_valg.strip()
            if stripped:
                ny["høne"] = labels.get(stripped, stripped)
            else:
                ny.pop("høne", None)

        antal = questionary.text(
            "Antal æg lagt til rugning:",
            default=str(ny.get("æg_antal", 0)),
            validate=_heltal,
        ).ask()
        if antal is None:
            sys.exit(0)
        ny["æg_antal"] = int(antal)

        nuv_klæk = str(ny.get("forventet_klæk", ""))
        klæk = questionary.text(
            "Forventet klæk (YYYY-MM-DD):",
            default=nuv_klæk,
            validate=lambda v: bool(_re.match(r"^\d{4}-\d{2}-\d{2}$", v))
                or "Ugyldigt datoformat",
        ).ask()
        if klæk is None:
            sys.exit(0)
        ny["forventet_klæk"] = klæk

    elif t == "foderkøb":
        foder = questionary.text("Foder-type:", default=ny.get("foder_type", "")).ask()
        if foder is None:
            sys.exit(0)
        if foder.strip():
            ny["foder_type"] = foder.strip()
        else:
            ny.pop("foder_type", None)

        mængde = questionary.text(
            "Mængde i kg:", default=str(ny.get("mængde_kg", "")), validate=_tal
        ).ask()
        if mængde is None:
            sys.exit(0)
        if mængde.strip():
            tal = float(mængde.replace(",", "."))
            ny["mængde_kg"] = int(tal) if tal == int(tal) else tal
        else:
            ny.pop("mængde_kg", None)

        pris = questionary.text(
            "Pris i kr:", default=str(ny.get("pris", "")), validate=_tal
        ).ask()
        if pris is None:
            sys.exit(0)
        if pris.strip():
            tal = float(pris.replace(",", "."))
            ny["pris"] = int(tal) if tal == int(tal) else tal
        else:
            ny.pop("pris", None)

        butik = questionary.text("Butik:", default=ny.get("butik", "")).ask()
        if butik is None:
            sys.exit(0)
        if butik.strip():
            ny["butik"] = butik.strip()
        else:
            ny.pop("butik", None)

    elif t == "sundhedsobs":
        obs = questionary.text(
            "Observation:",
            default=ny.get("observation", ""),
            validate=lambda v: bool(v.strip()) or "Observation er påkrævet",
        ).ask()
        if not obs:
            sys.exit(0)
        ny["observation"] = obs.strip()

        handling = questionary.text("Handling:", default=ny.get("handling", "")).ask()
        if handling is None:
            sys.exit(0)
        if handling.strip():
            ny["handling"] = handling.strip()
        else:
            ny.pop("handling", None)

    elif t == "dødsfald":
        årsag = questionary.text(
            "Årsag:", default=ny.get("årsag", "ukendt")
        ).ask()
        if årsag is None:
            sys.exit(0)
        if årsag.strip():
            ny["årsag"] = årsag.strip()
        else:
            ny.pop("årsag", None)

    elif t == "fjerfældning":
        fase = questionary.select(
            "Fase:",
            choices=["start", "slut"],
            default=ny.get("fase", "start"),
        ).ask()
        if fase is None:
            sys.exit(0)
        ny["fase"] = fase

    # Noter — fælles for alle typer
    noter = questionary.text("Noter:", default=ny.get("noter", "") or "").ask()
    if noter is None:
        sys.exit(0)
    if noter.strip():
        ny["noter"] = noter.strip()
    else:
        ny.pop("noter", None)

    # Preview
    ry = RuamelYAML()
    ry.default_flow_style = False
    ry.width = 120
    ry.allow_unicode = True
    buf = io.StringIO()
    ry.dump(ny, buf)
    print(f"\n── Entry-preview ({entry_sti.name}) ─────────────────────────────")
    print(buf.getvalue().rstrip())
    print("──────────────────────────────────────────────────────────\n")

    if not questionary.confirm("Gem rettelserne?", default=True).ask():
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    with open(entry_sti, "w", encoding="utf-8") as fh:
        ry.dump(ny, fh)
    print(f"✓ Entry opdateret: {entry_sti}")

    from .byg import generer_alle
    generer_alle()


def _ret_dagbog_entry():
    """Wizard til at rette i en eksisterende dagbogsentry (.md med YAML-frontmatter)."""
    import questionary

    sektioner_mappe = DATA_MAPPE / "entries" / "sektioner"
    if not sektioner_mappe.exists():
        print("Ingen dagbogsindlæg fundet.")
        return

    filer = sorted(sektioner_mappe.glob("*.md"), reverse=True)
    if not filer:
        print("Ingen dagbogsindlæg fundet.")
        return

    def _parse_md(p: Path):
        tekst = p.read_text(encoding="utf-8")
        dele = tekst.split("---", 2)
        if len(dele) < 3:
            return {}, tekst
        try:
            fm = yaml.safe_load(dele[1]) or {}
        except Exception:
            fm = {}
        return fm, dele[2].lstrip("\n")

    choices = []
    for p in filer:
        fm, krop = _parse_md(p)
        dato = fm.get("dato", "?")
        zone = fm.get("zone", "?")
        preview = krop.strip()[:50].replace("\n", " ")
        choices.append(questionary.Choice(
            title=f"{dato}  {zone} — {preview}",
            value=p,
        ))

    if not choices:
        print("Ingen dagbogsindlæg kunne læses.")
        return

    valgt = questionary.select("Vælg entry at rette:", choices=choices).ask()
    if valgt is None:
        sys.exit(0)

    fm, krop = _parse_md(valgt)

    ny_tekst = questionary.text(
        "Tekst:",
        default=krop.strip(),
        validate=lambda v: bool(v.strip()) or "Tekst er påkrævet",
    ).ask()
    if not ny_tekst:
        sys.exit(0)

    plante_data = load_yaml(PLANTER_FIL)
    planter = plante_data if isinstance(plante_data, list) else plante_data.get("planter", [])
    nuv_ids = fm.get("plante_id") or []
    if isinstance(nuv_ids, str):
        nuv_ids = [nuv_ids]

    plante_choices = [
        questionary.Choice(
            title=f"{p.get('navn', '?')} ({p.get('id', '?')})",
            value=p.get("id"),
            checked=p.get("id") in nuv_ids,
        )
        for p in sorted(planter, key=lambda p: p.get("navn", "").lower())
    ]
    nye_planter = questionary.checkbox(
        "Planter (mellemrum = vælg, Enter = bekræft):",
        choices=plante_choices,
    ).ask()
    if nye_planter is None:
        sys.exit(0)

    ny_fm = dict(fm)
    if not nye_planter:
        ny_fm.pop("plante_id", None)
    elif len(nye_planter) == 1:
        ny_fm["plante_id"] = nye_planter[0]
    else:
        ny_fm["plante_id"] = nye_planter

    # Serialisér frontmatter manuelt for at bevare felternes rækkefølge
    fm_linjer = ["---"]
    for k, v in ny_fm.items():
        if isinstance(v, list):
            fm_linjer.append(f"{k}:")
            for item in v:
                fm_linjer.append(f"  - {item}")
        else:
            fm_linjer.append(f"{k}: {v}")
    fm_linjer.append("---")

    nyt_indhold = "\n".join(fm_linjer) + "\n\n" + ny_tekst.strip() + "\n"

    print(f"\n── Entry-preview ({valgt.name}) ──────────────────────────────────")
    print(nyt_indhold.rstrip())
    print("──────────────────────────────────────────────────────────\n")

    if not questionary.confirm("Gem rettelserne?", default=True).ask():
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    valgt.write_text(nyt_indhold, encoding="utf-8")
    print(f"✓ Entry opdateret: {valgt}")

    from .byg import generer_alle
    generer_alle()


def ret_entry():
    """Interaktiv wizard til at rette i en eksisterende dagbogs- eller hønse-entry."""
    import questionary

    type_valg = questionary.select(
        "Hvilken type entry vil du rette?",
        choices=[
            questionary.Choice("🐔 Hønseobservation", value="hons"),
            questionary.Choice("📖 Dagbogsentry", value="dagbog"),
        ],
    ).ask()
    if type_valg is None:
        sys.exit(0)

    if type_valg == "hons":
        _ret_hons_entry()
    else:
        _ret_dagbog_entry()


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

    # ── familie ───────────────────────────────────────────────────────────────
    # Driver familiebaserede skadedyr-opslag på plante-siden — spørg altid, så
    # feltet ikke kun udfyldes når Wikidata leverer det.
    familie_input = questionary.text(
        "Familie (fx 'Natskygge', Enter = ingen):",
        default=auto_familie or "",
    ).ask()
    familie = ((familie_input or "").strip() or auto_familie or None)

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

    # ── skadedyr (plantespecifikke) ───────────────────────────────────────────
    # Familie-baserede skadedyr arves automatisk via 'familie'; her vælges kun
    # eventuelle plantespecifikke skadedyr ud over familien.
    skadedyr_ids = []
    from .indlaes import load_skadedyr
    sk_db = load_skadedyr()
    if sk_db and questionary.confirm(
        "Tilføj plantespecifikke skadedyr? (familie-skadedyr kommer automatisk)",
        default=False,
    ).ask():
        skadedyr_ids = questionary.checkbox(
            "Vælg skadedyr:",
            choices=[questionary.Choice(title=f"{s.get('navn', sid)} [{sid}]", value=sid)
                     for sid, s in sk_db.items()],
        ).ask() or []

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
    if familie:
        plante["familie"] = familie
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
    # Tom nabo-skabelon skrives med, så feltet er synligt i planter.yaml og
    # minder om at udfylde gode/dårlige naboer manuelt senere.
    plante["naboer"] = {"gode": [], "dårlige": []}
    if skadedyr_ids:
        plante["skadedyr_ids"] = skadedyr_ids

    gem_pid, yaml_blok = opret_plante(plante)
    print(f"\n✓ Plante gemt: {gem_pid}")
    print(f"  Fil: {PLANTER_FIL}\n")
    print("─" * 40)
    print(yaml_blok.rstrip())
    print("─" * 40)
    if not familie:
        print("\n  ℹ️  Ingen familie sat — uden den vises familiebaserede skadedyr ikke.")
    print("\n  💡 Husk at udfylde naboer.gode / naboer.dårlige i planter.yaml.")
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
        ("wikidata",     "Wikidata Q-id"),
        ("naboer",       "Naboer (gode/dårlige)"),
        ("skadedyr_ids", "Skadedyr (plantespecifikke)"),
    ]

    def _felt_label(felt, label):
        v = valgt_plante.get(felt)
        if felt == "foto" and isinstance(v, dict):
            return f"{label}  [{v.get('fil', '?')}]"
        if felt == "naboer":
            n = len((v or {}).get("gode") or []) + len((v or {}).get("dårlige") or [])
            return f"{label}  [{n} nabo(er)]" if n else f"{label}  (ingen)"
        if felt == "skadedyr_ids":
            n = len(v or [])
            return f"{label}  [{n}]" if n else f"{label}  (ingen)"
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

        elif felt == "wikidata":
            ny_val = (questionary.text(
                "Wikidata Q-id (fx 'Q25415', Enter = fjern):",
                default=str(nuværende or ""),
                validate=lambda v: (not v.strip()) or bool(_re.match(r"^Q\d+$", v.strip()))
                    or "format: Q efterfulgt af tal",
            ).ask() or "").strip()
            ændringer["wikidata"] = ny_val or None

        elif felt == "skadedyr_ids":
            from .indlaes import load_skadedyr
            sk_db = load_skadedyr()
            if not sk_db:
                print("  Ingen skadedyr i skadedyr.yaml — springer feltet over.")
            else:
                nuv_ids = set(nuværende or [])
                valgt_sk = questionary.checkbox(
                    "Plantespecifikke skadedyr (familie-skadedyr kommer automatisk):",
                    choices=[
                        questionary.Choice(
                            title=f"{s.get('navn', sid)} [{sid}]",
                            value=sid,
                            checked=(sid in nuv_ids),
                        )
                        for sid, s in sk_db.items()
                    ],
                ).ask()
                if valgt_sk is not None:
                    ændringer["skadedyr_ids"] = valgt_sk or None

        elif felt == "naboer":
            nuv = nuværende if isinstance(nuværende, dict) else {}
            resultat: dict = {}
            for gruppe, etiket, ental in (
                ("gode", "Gode naboer 👍", "god"),
                ("dårlige", "Dårlige naboer 👎", "dårlig"),
            ):
                liste = [dict(n) for n in (nuv.get(gruppe) or [])]
                print(f"  {etiket}:")
                if liste:
                    for n in liste:
                        note = f" — {n.get('note')}" if n.get("note") else ""
                        print(f"    • {n.get('plante_id')}{note}")
                else:
                    print("    (ingen)")
                if liste and questionary.confirm(f"  Ryd alle {gruppe} naboer?", default=False).ask():
                    liste = []
                while questionary.confirm(f"  Tilføj en {ental} nabo?", default=False).ask():
                    søg_n = (questionary.text("    Søg plante (navn/sort/id):").ask() or "").strip()
                    if not søg_n:
                        continue
                    hits_n = _søg_planter(søg_n, db)
                    if not hits_n:
                        print(f"    Ingen planter matcher '{søg_n}'.")
                        continue
                    if len(hits_n) == 1:
                        valgt_n = hits_n[0]
                    else:
                        valgt_n = questionary.select(
                            "    Vælg:",
                            choices=[questionary.Choice(title=_plante_label(p), value=p) for p in hits_n],
                        ).ask()
                        if valgt_n is None:
                            continue
                    note = (questionary.text("    Note (Enter = ingen):").ask() or "").strip()
                    post = {"plante_id": valgt_n["id"]}
                    if note:
                        post["note"] = note
                    liste.append(post)
                    print(f"    ✓ tilføjet {valgt_n['id']}")
                if liste:
                    resultat[gruppe] = liste
            ændringer["naboer"] = resultat or None

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


def ret_foto():
    """Interaktiv wizard: ret foto for en plante (planter.yaml) eller høne (dyr.yaml).

    Kan importere en lokal billedfil (kopieres til fotos/planter/ hhv. fotos/dyr/,
    optimeres til ≤1200px JPEG + thumbnail via optimer_foto) og/eller rette
    foto-metadata (kilde/url/licens/forfatter). Skriver tilbage med ruamel.yaml så
    øvrig struktur og kommentarer bevares.
    """
    import io as _io
    import shutil as _shutil
    import questionary
    from ruamel.yaml import YAML as RuamelYAML
    from ruamel.yaml.comments import CommentedMap

    ry = RuamelYAML()
    ry.preserve_quotes = True
    ry.default_flow_style = False
    ry.width = 120

    # ── 1. Plante eller høne? ──────────────────────────────────────────────────
    slags = questionary.select(
        "Hvad vil du rette foto for?",
        choices=[
            questionary.Choice(title="🌿 Plante (planter.yaml)", value="plante"),
            questionary.Choice(title="🐔 Høne/dyr (dyr.yaml)", value="dyr"),
        ],
    ).ask()
    if not slags:
        sys.exit(0)

    if slags == "plante":
        fil        = PLANTER_FIL
        db         = byg_plante_db(PLANTER_FIL)
        foto_mappe = FOTOS_MAPPE / "planter"
        label_fn   = _plante_label
        data_nøgle = "planter"
    else:
        fil        = DYR_FIL
        db         = byg_dyr_db(DYR_FIL)
        foto_mappe = FOTOS_MAPPE / "dyr"
        label_fn   = lambda d: f"{_dyr_label(d)} [{d.get('id', '?')}]"
        data_nøgle = "dyr"

    if not db:
        print(f"❌ Ingen poster fundet i {fil}")
        sys.exit(1)

    # ── 2. Vælg post ───────────────────────────────────────────────────────────
    if slags == "plante":
        valgt = None
        while valgt is None:
            søg = questionary.text("Søg efter plante (navn, sort eller id):").ask()
            if søg is None:
                sys.exit(0)
            hits = _søg_planter(søg, db)
            if not hits:
                print(f"  Ingen planter matcher '{søg}'. Prøv igen.")
                continue
            if len(hits) == 1:
                valgt = hits[0]
            else:
                valgt = questionary.select(
                    "Vælg plante:",
                    choices=[questionary.Choice(title=_plante_label(p), value=p) for p in hits],
                ).ask()
                if valgt is None:
                    sys.exit(0)
    else:
        valgt = questionary.select(
            "Vælg høne:",
            choices=[
                questionary.Choice(title=label_fn(d), value=d)
                for d in sorted(db.values(), key=lambda d: _dyr_label(d).lower())
            ],
        ).ask()
        if valgt is None:
            sys.exit(0)

    post_id = valgt["id"]
    print(f"\n  Redigerer foto for: {label_fn(valgt)}")

    nuværende = valgt.get("foto") if isinstance(valgt.get("foto"), dict) else {}
    if nuværende:
        print("  Nuværende foto:")
        for k in ("fil", "kilde", "url", "licens", "forfatter"):
            if nuværende.get(k):
                print(f"    {k}: {nuværende[k]}")
    else:
        print("  (intet foto sat)")
    print()

    # ── 3. Importér evt. ny billedfil ──────────────────────────────────────────
    nyt_filnavn = nuværende.get("fil") or ""
    kilde_sti = (questionary.text(
        f"Sti til ny billedfil (Enter = behold '{nyt_filnavn or '—'}'):",
    ).ask() or "").strip()

    if kilde_sti:
        kilde_path = Path(os.path.expanduser(kilde_sti))
        if not kilde_path.is_file():
            print(f"❌ Filen eksisterer ikke: {kilde_sti!r}")
            sys.exit(1)
        foto_mappe.mkdir(parents=True, exist_ok=True)
        dest = foto_mappe / f"{post_id}{kilde_path.suffix.lower()}"
        _shutil.copy2(kilde_path, dest)
        try:
            from .fotos import optimer_foto
            gem_sti = optimer_foto(dest)
        except Exception as e:
            print(f"⚠️  Kunne ikke optimere billedet ({e}) — beholder original.")
            gem_sti = dest
        nyt_filnavn = gem_sti.name
        print(f"  💾 Gemt: {foto_mappe.name}/{nyt_filnavn}")

    if not nyt_filnavn:
        print("❌ Intet filnavn — afbrudt.")
        sys.exit(0)

    # ── 4. Ret metadata ────────────────────────────────────────────────────────
    print("  Metadata (Enter = behold; mellemrum + Enter = fjern feltet):")

    def _meta(prompt: str, felt: str):
        svar = questionary.text(f"  {prompt}:", default=nuværende.get(felt, "") or "").ask()
        if svar is None:
            sys.exit(0)
        return svar.strip()

    forfatter = _meta("Forfatter", "forfatter")
    licens    = _meta("Licens (fx 'eget værk', 'CC BY-SA 4.0')", "licens")
    kilde     = _meta("Kilde-URL", "kilde")
    url       = _meta("Direkte billed-URL (url)", "url")

    # ── 5. Byg foto-dict i FotoModel-feltrækkefølge ────────────────────────────
    nyt_foto = CommentedMap()
    nyt_foto["fil"] = nyt_filnavn
    if kilde:
        nyt_foto["kilde"] = kilde
    if url:
        nyt_foto["url"] = url
    if licens:
        nyt_foto["licens"] = licens
    if forfatter:
        nyt_foto["forfatter"] = forfatter

    buf = _io.StringIO()
    ry.dump({"foto": nyt_foto}, buf)
    print("\n── Nyt foto ──────────────────────────────────────────────")
    print(buf.getvalue().rstrip())
    print("──────────────────────────────────────────────────────────\n")
    if not questionary.confirm(f"Gem til {fil.name}?", default=True).ask():
        print("Afbrudt — ingen ændringer gemt.")
        sys.exit(0)

    # ── 6. Skriv tilbage med ruamel.yaml (bevarer struktur) ────────────────────
    with open(fil, encoding="utf-8") as fh:
        rå_data = ry.load(fh)

    poster = rå_data if isinstance(rå_data, list) else rå_data.get(data_nøgle, [])
    post = next((p for p in poster if p.get("id") == post_id), None)
    if post is None:
        print(f"❌ Kunne ikke finde {post_id!r} i {fil.name} — afbrudt.")
        sys.exit(1)
    post["foto"] = nyt_foto

    buf = _io.StringIO()
    ry.dump(rå_data, buf)
    fil.write_text(buf.getvalue(), encoding="utf-8")

    print(f"\n✓ Foto opdateret for {label_fn(valgt)} i {fil.name}")
    print("  Kør 'have' for at opdatere sitet, eller 'have check' for at validere.")


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

    navn = questionary.text("Navn (kan være tom):").ask()
    if navn is None:
        sys.exit(0)
    navn = navn.strip()

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

    noter = questionary.text("Noter (kan være tom):").ask()
    if noter is None:
        sys.exit(0)
    noter = noter.strip()

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
    if navn:
        ny["navn"] = navn
    ny["race"] = race
    if farve:
        ny["farve"] = farve
    if fødsel:
        ny["fødselsdato"] = fødsel
    ny["aktiv"] = True
    if noter:
        ny["noter"] = noter

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


def hons_ny_obs(dato: str = None):
    """Wizard: registrér en hønse-observation som YAML-entry i entries/hons/.

    dato: hvis angivet springes dato-spørgsmålet over (bruges når ny_entry allerede har indsamlet det).
    """
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

    # 2. Dato (springes over hvis allerede indsamlet af kalderen)
    if dato is None:
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


def wizard_ny_frø():
    """Interaktiv wizard til at oprette en ny frøpost i data/frø.yaml."""
    import questionary
    from ruamel.yaml import YAML
    from io import StringIO
    from .kontekst import FRØ_FIL

    db = byg_plante_db(PLANTER_FIL)
    kendte_ids = sorted(db.keys())

    i_år = datetime.date.today().year

    # ── 1. plante_id (valgfri) ────────────────────────────────────────────────
    pid_svar = questionary.autocomplete(
        "Plante-id (valgfri — Enter = spring over):",
        choices=[""] + kendte_ids,
        default="",
    ).ask()
    pid = (pid_svar or "").strip() or None

    # ── 2. navn ───────────────────────────────────────────────────────────────
    default_navn = db[pid].get("navn", pid) if pid and pid in db else ""
    navn = (questionary.text(
        "Navn (fx 'Gulerod'):",
        default=default_navn,
        validate=lambda v: bool(v.strip()) or "Navn er påkrævet",
    ).ask() or "").strip()
    if not navn:
        sys.exit(0)

    # ── 3. sort ───────────────────────────────────────────────────────────────
    default_sort = db[pid].get("sort", "") if pid and pid in db else ""
    sort = (questionary.text(
        "Sort (fx 'Nantes 2', Enter = ingen):",
        default=default_sort or "",
    ).ask() or "").strip() or None

    # ── 4. kilde ─────────────────────────────────────────────────────────────
    kilde_type = questionary.select(
        "Hvorfra kommer frøet?",
        choices=["Firma/butik", "Egenindsamlet/byttet/andet"],
    ).ask()
    firma = None
    kilde = None
    if kilde_type and "Firma" in kilde_type:
        firma = (questionary.text("Firmanavn (fx 'Frøsamlerne'):").ask() or "").strip() or None
    else:
        kilde = (questionary.text("Kilde (fx 'egenindsamlet', 'byttet'):").ask() or "").strip() or None

    # ── 5. år ────────────────────────────────────────────────────────────────
    år_svar = questionary.text(
        "År (købt/høstet):",
        default=str(i_år),
        validate=lambda v: v.strip().isdigit() or "Skriv et årstal",
    ).ask()
    år = int(år_svar.strip()) if år_svar else i_år

    # ── 6. bedst_før ──────────────────────────────────────────────────────────
    bedst_svar = questionary.text(
        "Bedst før (årstal):",
        default=str(år + 3),
        validate=lambda v: v.strip().isdigit() or "Skriv et årstal",
    ).ask()
    bedst_før = int(bedst_svar.strip()) if bedst_svar else år + 3

    # ── 7. rest ───────────────────────────────────────────────────────────────
    rest = questionary.select(
        "Restmængde:",
        choices=["fuld", "lav"],
        default="fuld",
    ).ask() or "fuld"

    # ── 8. pris ───────────────────────────────────────────────────────────────
    pris_svar = (questionary.text("Pris i DKK (Enter = spring over):").ask() or "").strip()
    pris = int(pris_svar) if pris_svar.isdigit() else None

    # ── 9. noter ──────────────────────────────────────────────────────────────
    noter = (questionary.text("Noter (Enter = ingen):").ask() or "").strip() or None

    # ── Byg og gem ─────────────────────────────────────────────────────────────
    post: dict = {"navn": navn}
    if pid:
        post = {"plante_id": pid, **post}
    if sort:
        post["sort"] = sort
    if firma:
        post["firma"] = firma
    if kilde:
        post["kilde"] = kilde
    post["år"] = år
    post["bedst_før"] = bedst_før
    post["rest"] = rest
    if pris is not None:
        post["pris"] = pris
    if noter:
        post["noter"] = noter

    ryaml = YAML()
    ryaml.preserve_quotes = True
    if FRØ_FIL.exists():
        data = ryaml.load(FRØ_FIL.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    if "frø" not in data or data["frø"] is None:
        data["frø"] = []
    data["frø"].append(post)

    buf = StringIO()
    ryaml.dump(data, buf)
    FRØ_FIL.write_text(buf.getvalue(), encoding="utf-8")

    display_navn = f"{navn}{' ' + sort if sort else ''}"
    print(f"\n✅ Frøpost gemt: {display_navn} → {FRØ_FIL}")
    print("   Kør 'have build' for at opdatere siden.")
    print("   Kør 'have build' for at opdatere sitet.")
