"""haven.kontekst — delte konstanter og modul-global tilstand.

Lavniveau-modul i cli-opdelingen (se briefs/cli-opdeling.md): samler alle
konstanter afledt af haven.yaml plus de mutérbare databaser PLANTE_DB/DYR_DB.
Alle højere lag importerer herfra. Modulet importerer kun fra config + models
(roden af DAG'en) og må ALDRIG importere fra render-laget.

VIGTIGT: PLANTE_DB/DYR_DB skal deles som *samme objekt*. Importér dem og mutér
kun in-place (.update()/.clear()) — re-bind dem aldrig i andre moduler.
"""

import sys

from .config import (
    load_config, data_mappe, out_mappe, sti,
    sftp_adgangskode, ftp_adgangskode, rotation_cyklus,
)

_config = load_config()

AKTIVT_ÅR   = _config["aktivt_år"]
DATA_MAPPE  = data_mappe(_config)
OUT_MAPPE   = out_mappe(_config)
FOTOS_MAPPE = sti(_config, "fotos")   # absolut — så foto-skrivning er uafhængig af cwd
PLANTER_FIL  = sti(_config, "data") / "planter.yaml"
DYR_FIL      = sti(_config, "data") / "dyr.yaml"
FRØ_FIL      = sti(_config, "data") / "frø.yaml"
SKADEDYR_FIL = sti(_config, "data") / "skadedyr.yaml"
ALMANAK_FIL = DATA_MAPPE / "almanak.yaml"
ENTRIES_FIL = DATA_MAPPE / "entries.yaml"

YAML_FILER_DEFAULT = [
    DATA_MAPPE / f"{bed}.yaml" for bed in _config["bede"]
]

BASE_URL = _config["site"]["basis_url"]

GYLDIGE_PROTOKOLLER = ("ftp", "sftp")


def normaliser_protokoller(rå) -> list:
    """Normalisér deploy.protokol (streng eller liste) til en ordnet liste af
    gyldige protokoller. 'ingen'/tom → []. Dubletter og ukendte værdier filtreres."""
    if rå is None:
        return []
    værdier = [rå] if isinstance(rå, str) else list(rå)
    ud: list = []
    for v in værdier:
        v = str(v).strip().lower()
        if v in ("", "ingen"):
            continue
        if v in GYLDIGE_PROTOKOLLER:
            if v not in ud:
                ud.append(v)
        else:
            print(f"[ADVARSEL] Ukendt deploy-protokol: {v!r} — ignoreres "
                  f"(gyldige: {', '.join(GYLDIGE_PROTOKOLLER)})", file=sys.stderr)
    return ud


_deploy = _config.get("deploy", {})
DEPLOY_PROTOKOLLER = normaliser_protokoller(_deploy.get("protokol", "ingen"))

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

# ── Sædskifte ────────────────────────────────────────────────────────────────
# rotation.cyklus i haven.yaml: bede i rotationsrækkefølge (cirkulær). Tom = slået fra.
ROTATION_CYKLUS = rotation_cyklus(_config)
# Tunge familier der ikke bør gå igen i samme bed to år i træk → dansk etiket.
TUNGE_FAMILIER = {
    "Solanaceae":   "kartofler/tomater",
    "Brassicaceae": "kål",
}

MÅNEDER      = ["Jan","Feb","Mar","Apr","Maj","Jun","Jul","Aug","Sep","Okt","Nov","Dec"]
MÅNEDER_LANG = ["januar","februar","marts","april","maj","juni",
                "juli","august","september","oktober","november","december"]

# ── Mutérbare databaser ──────────────────────────────────────────────────────
# Populeres i main/generer_alle via .update(); muteres KUN in-place.

PLANTE_DB: dict = {}    # Populeres i main via PLANTE_DB.update(byg_plante_db())
DYR_DB: dict = {}       # Populeres i generer_alle via DYR_DB.update(byg_dyr_db())
SKADEDYR_DB: dict = {}  # Populeres i generer_alle via byg_skadedyr_db()


# Hønse-entry-typer: ikon + dansk label. Styrer både wizard-valg og visning.
HONS_TYPER = {
    "note":         {"ikon": "📝", "label": "Note"},
    "æglægning":    {"ikon": "🥚", "label": "Æglægning"},
    "ruge-start":   {"ikon": "🐣", "label": "Rugestart"},
    "foderkøb":     {"ikon": "🌾", "label": "Foderkøb"},
    "sundhedsobs":  {"ikon": "🩺", "label": "Sundhedsobservation"},
    "dødsfald":     {"ikon": "🪦", "label": "Dødsfald"},
    "fjerfældning": {"ikon": "🪶", "label": "Fjerfældning"},
}
