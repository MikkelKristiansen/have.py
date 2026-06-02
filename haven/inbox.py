"""have hent-inbox — hent dagbogsindlæg fra have-inbox-webappen og behandl dem.

have-inbox er en selvstændig Flask-app (på RPi5/YunoHost), hvor man fra telefonen
opretter dagbogsindlæg med foto. Indlæggene gemmes råt i en inbox-mappe på serveren:

    inbox/{dato}_{tid}/entry.yaml   + 01.jpg

Dette modul henter mappen via SFTP/SSH (nøgle-auth, som git-remoten), laver hvert
indlæg til en rigtig entry via cli.opret_entry (navngivning, thumbnail, dublet-suffiks),
bygger sitet og rydder inboxen på serveren.

    have hent-inbox            # dry-run: vis hvad der ligger i inboxen
    have hent-inbox --skriv    # importér, byg site og ryd serverens inbox

Konfiguration i haven.yaml under 'inbox:' (host, bruger, sti).

Lagdeling (efter cli-opdelingen, briefs/cli-opdeling.md): importerer fra render-/
handler-lagene, ikke fra cli — opret-kerner fra wizards, byg-orkestratoren fra byg,
fil-opdagelse fra indlaes og lftp-quoting fra deploy.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from .wizards import opret_entry, opret_hons_entry
from .byg import generer_alle
from .indlaes import _find_yaml_filer
from .deploy import _lftp_q
from .config import load_config

_cfg = load_config()
_inbox = _cfg.get("inbox", {}) or {}
INBOX_HOST = _inbox.get("host", "")
INBOX_BRUGER = _inbox.get("bruger", "")
INBOX_STI = (_inbox.get("sti", "") or "").rstrip("/")

# Tom adgangskode i URL'en (':@') → lftp prøver ikke at hente password (vi bruger
# SSH-nøgle via connect-program); det undgår en misvisende "GetPass failed"-linje.
_SFTP_URL = f"sftp://{INBOX_BRUGER}:@{INBOX_HOST}"

# Fælles lftp-indstillinger: brug systemets ssh (nøgle-auth) og sæt timeouts, så en
# stall fejler frem for at hænge i det uendelige.
_LFTP_OPTS = [
    'set sftp:connect-program "ssh -a -x -o BatchMode=yes"',
    "set net:timeout 15",
    "set net:max-retries 2",
    "set net:reconnect-interval-base 5",
]


def _kør_lftp(linjer: list[str]) -> int:
    """Kør et lftp-script og returnér exit-koden. Output streames live (ikke buffret),
    så en overførsel ikke ser frossen ud."""
    script = "\n".join([*_LFTP_OPTS, *linjer, "bye", ""])
    try:
        r = subprocess.run(["lftp"], input=script, text=True)
    except FileNotFoundError:
        print("❌ lftp er ikke installeret — kør: sudo pacman -S lftp")
        sys.exit(1)
    return r.returncode


def hent_ned(lokal: Path) -> int:
    """Spejl serverens inbox ned i en lokal mappe (remote → local)."""
    return _kør_lftp([
        f"open {_lftp_q(_SFTP_URL)}",
        f"mirror --verbose {_lftp_q(INBOX_STI + '/')} {_lftp_q(str(lokal) + '/')}",
    ])


def ryd_på_server(navne: list[str]) -> int:
    """Fjern de behandlede indlægs-mapper på serveren."""
    cmds = [f"open {_lftp_q(_SFTP_URL)}"]
    cmds += [f"rm -r {_lftp_q(f'{INBOX_STI}/{navn}')}" for navn in navne]
    return _kør_lftp(cmds)


def _find_foto(mappe: Path, data: dict):
    """Returnér sti til første foto i mappen, eller None (advarer hvis refereret men mangler)."""
    fotos = data.get("fotos") or []
    if not fotos:
        return None
    fp = mappe / fotos[0]
    if fp.exists():
        return str(fp)
    print(f"      ⚠️  foto {fotos[0]} mangler i mappen — gemmes uden foto")
    return None


def _læs_entry(mappe: Path):
    """Læs og valider ét indlæg. Returnér (felter, fejltekst-eller-None).

    felter['kind'] er 'dagbog' eller 'hons' og bestemmer hvordan det importeres.
    """
    ey = mappe / "entry.yaml"
    if not ey.exists():
        return None, "ingen entry.yaml"
    try:
        data = yaml.safe_load(ey.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return None, f"ugyldig YAML ({e})"

    typ = data.get("type", "dagbog")
    dato = data.get("dato")
    if not dato:
        return None, "mangler dato"
    foto_kilde = _find_foto(mappe, data)

    if typ == "dagbog":
        zone = data.get("zone")
        tekst = (data.get("tekst") or "").strip()
        if not (zone and tekst):
            return None, "mangler zone eller tekst"
        plante_id = data.get("plante_id") or []
        if isinstance(plante_id, str):
            plante_id = [plante_id]
        return {"kind": "dagbog", "dato": str(dato), "zone": str(zone),
                "tekst": tekst, "plante_id": plante_id, "foto_kilde": foto_kilde}, None

    if typ == "hons":
        hons_type = str(data.get("hons_type") or "note")
        tekst = (data.get("tekst") or "").strip()
        høne = data.get("høne") or None
        ekstra = {}
        if data.get("æg") not in (None, ""):
            ekstra["æg"] = data.get("æg")
        if not (tekst or høne or ekstra):
            return None, "tomt hønse-indlæg (hverken tekst, høne eller data)"
        return {"kind": "hons", "dato": str(dato), "hons_type": hons_type,
                "høne": høne, "noter": tekst, "ekstra": ekstra, "foto_kilde": foto_kilde}, None

    return None, f"type {typ!r} understøttes ikke"


def _rel(sti) -> str:
    s = str(sti)
    return str(Path(s).relative_to(Path.cwd())) if s.startswith(str(Path.cwd())) else s


def behandl(lokal: Path, skriv: bool) -> list[str]:
    """Gennemgå (og evt. importér) alle indlæg i den nedhentede mappe.
    Returnér navnene på de mapper der blev behandlet succesfuldt."""
    mapper = sorted(d for d in lokal.iterdir() if d.is_dir())
    behandlede = []
    for mappe in mapper:
        felter, fejl = _læs_entry(mappe)
        if fejl:
            print(f"  ⚠️  {mappe.name}: {fejl} — springer over")
            continue
        flag = " + foto" if felter["foto_kilde"] else ""

        if felter["kind"] == "dagbog":
            uddrag = felter["tekst"].splitlines()[0][:60]
            print(f"  • [dagbog] {felter['dato']} / {felter['zone']} / "
                  f"{len(felter['plante_id'])} plante(r){flag}: {uddrag}")
            if skriv:
                sti = opret_entry(
                    felter["dato"], felter["zone"], felter["tekst"],
                    plante_id=felter["plante_id"], foto_kilde=felter["foto_kilde"],
                    _generer=False,
                )
                print(f"      → {_rel(sti)}")
        else:  # hons
            hl = felter["høne"] or "flokken"
            uddrag = felter["noter"].splitlines()[0][:50] if felter["noter"] else ""
            print(f"  • [høns/{felter['hons_type']}] {felter['dato']} / {hl}{flag}: {uddrag}")
            if skriv:
                sti = opret_hons_entry(
                    felter["dato"], felter["hons_type"], høne=felter["høne"],
                    noter=felter["noter"], foto_kilde=felter["foto_kilde"],
                    ekstra=felter["ekstra"], _generer=False,
                )
                print(f"      → {_rel(sti)}")
        behandlede.append(mappe.name)
    return behandlede


def main():
    ap = argparse.ArgumentParser(
        prog="have hent-inbox",
        description="Hent dagbogsindlæg fra have-inbox-webappen og behandl dem.",
    )
    ap.add_argument("--skriv", action="store_true",
                    help="Importér til data/, byg site og ryd inboxen på serveren "
                         "(uden flaget: dry-run der kun viser indholdet).")
    args = ap.parse_args()

    if not (INBOX_HOST and INBOX_BRUGER and INBOX_STI):
        print("❌ Mangler inbox-konfiguration i haven.yaml.\n"
              "   Tilføj fx:\n"
              "     inbox:\n"
              "       host: server.eksempel\n"
              "       bruger: brugernavn\n"
              "       sti: /home/yunohost.app/have_inbox/inbox")
        sys.exit(1)

    print(f"📥 Henter inbox fra {INBOX_BRUGER}@{INBOX_HOST}:{INBOX_STI}")
    with tempfile.TemporaryDirectory(prefix="have-inbox-") as tmp:
        lokal = Path(tmp)
        if hent_ned(lokal) != 0:
            print("❌ Kunne ikke hente fra serveren (tjek SSH-adgang og sti).")
            sys.exit(1)

        mapper = [d for d in lokal.iterdir() if d.is_dir()]
        if not mapper:
            print("✅ Inboxen er tom — intet at hente.")
            sys.exit(0)

        print(f"\nFundet {len(mapper)} indlæg i inboxen:")
        behandlede = behandl(lokal, args.skriv)

        if not args.skriv:
            print(f"\nℹ️  Dry-run — intet gemt. Kør 'have hent-inbox --skriv' for at "
                  f"importere, bygge og rydde serverens inbox.")
            sys.exit(0)

        if not behandlede:
            print("\n⚠️  Ingen indlæg kunne behandles — serveren ryddes ikke.")
            sys.exit(1)

        print("\n🔨 Bygger site...")
        generer_alle(_find_yaml_filer())

        print("🧹 Rydder inbox på serveren...")
        if ryd_på_server(behandlede) == 0:
            print(f"\n✅ {len(behandlede)} indlæg importeret, site bygget og inbox ryddet.")
        else:
            print(f"\n⚠️  {len(behandlede)} indlæg importeret og site bygget, men oprydningen "
                  f"på serveren fejlede — fjern mapperne manuelt.")
            sys.exit(1)


if __name__ == "__main__":
    main()
