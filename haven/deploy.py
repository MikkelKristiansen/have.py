"""haven.deploy — upload (SFTP/FTP via lftp) + haven.yaml-opdatering.

Sideløbende handler-modul i cli-opdelingen (se briefs/cli-opdeling.md, fase 5).
Afhænger af kontekst (SFTP_*/FTP_*/OUT_MAPPE) + stdlib.
normaliser_protokoller + GYLDIGE_PROTOKOLLER bor i kontekst (fase 1).
"""

import os
import subprocess
import sys

from .kontekst import (
    OUT_MAPPE,
    SFTP_HOST, SFTP_BRUGER, SFTP_MAPPE, SFTP_KODE,
    FTP_HOST, FTP_BRUGER, FTP_MAPPE, FTP_KODE,
)

__all__ = [
    "upload", "upload_ftp",
    "_opdater_haven_yaml", "_opdater_ftp_config",
]


def _opdater_haven_yaml(fn, arbejdsmappe: str = "."):
    """Læs, modificér og skriv haven.yaml — bevarer kommentarer via ruamel.yaml."""
    from ruamel.yaml import YAML
    sti = os.path.join(arbejdsmappe, "haven.yaml")
    ryaml = YAML()
    ryaml.preserve_quotes = True
    with open(sti, encoding="utf-8") as f:
        cfg = ryaml.load(f)
    fn(cfg)
    with open(sti, "w", encoding="utf-8") as f:
        ryaml.dump(cfg, f)


def _opdater_ftp_config(host, bruger, kode, mappe, arbejdsmappe: str = "."):
    """Skriv FTP-konfiguration (host/bruger/mappe) til haven.yaml."""
    def _opdater(cfg):
        ftp = cfg.setdefault("deploy", {}).setdefault("ftp", {})
        ftp["host"]   = host
        ftp["bruger"] = bruger
        ftp["mappe"]  = mappe
    _opdater_haven_yaml(_opdater, arbejdsmappe)


def _lftp_q(værdi) -> str:
    """Dobbelt-citér en streng til brug i en lftp-kommando (escaper \\ og ")."""
    s = str(værdi).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _kør_lftp(script: str) -> None:
    """Kør et lftp-kommandoscript via stdin.

    Credentials sendes via stdin (user-kommandoen), IKKE som argv — så
    adgangskoden ikke kan aflæses i procestabellen (ps/proc) under upload.
    """
    try:
        result = subprocess.run(
            ["lftp"], input=script, text=True, capture_output=True,
        )
    except FileNotFoundError:
        print("❌ lftp er ikke installeret — kør: sudo pacman -S lftp")
        sys.exit(1)

    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        print(f"❌ lftp-fejl (exit {result.returncode}):")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        sys.exit(1)
    print("✅ Alle filer uploadet via lftp.")


def upload_ftp(_filer):
    """Upload hele out/-mappen til FTP-server via lftp mirror (kun ændrede filer)."""
    if not FTP_KODE:
        print("❌ HAVE_FTP_KODE er ikke sat — kør: export HAVE_FTP_KODE=ditpassword")
        sys.exit(1)
    if not FTP_MAPPE or FTP_MAPPE.strip("/ ") == "":
        print("❌ deploy.ftp.mappe er ikke sat (eller er '/') — afbryder.\n"
              "   'mirror --delete' ville ellers spejle mod serverens rod og kunne\n"
              "   slette alt der ikke findes lokalt. Sæt en undermappe i haven.yaml.")
        sys.exit(1)

    out_rod = OUT_MAPPE.parent
    print(f"  ↑ {out_rod}/ → {FTP_BRUGER}@{FTP_HOST}:{FTP_MAPPE}/")
    script = "\n".join([
        f"open {_lftp_q(f'ftp://{FTP_HOST}')}",
        f"user {_lftp_q(FTP_BRUGER)} {_lftp_q(FTP_KODE)}",
        f"mirror -R --delete --verbose {_lftp_q(f'{out_rod}/')} {_lftp_q(f'{FTP_MAPPE}/')}",
        "bye",
        "",
    ])
    _kør_lftp(script)


def upload(filer):
    """Upload HTML-filer og fotos til server via lftp + SFTP."""
    if not SFTP_KODE:
        print("❌ HAVE_SFTP_KODE er ikke sat — kør: export HAVE_SFTP_KODE=ditpassword")
        sys.exit(1)
    if not SFTP_MAPPE or SFTP_MAPPE.strip("/ ") == "":
        print("❌ deploy.sftp.mappe er ikke sat (eller er '/') — afbryder.\n"
              "   'mirror --delete' ville ellers spejle mod serverens rod og kunne\n"
              "   slette alt der ikke findes lokalt. Sæt en undermappe i haven.yaml.")
        sys.exit(1)

    out_rod = OUT_MAPPE.parent
    print(f"  ↑ {out_rod}/ → {SFTP_BRUGER}@{SFTP_HOST}:{SFTP_MAPPE}/")
    script = "\n".join([
        "set sftp:connect-program \"ssh -o IdentityAgent=none\"",
        f"open {_lftp_q(f'sftp://{SFTP_HOST}')}",
        f"user {_lftp_q(SFTP_BRUGER)} {_lftp_q(SFTP_KODE)}",
        f"mirror -R --delete --verbose {_lftp_q(f'{out_rod}/')} {_lftp_q(f'{SFTP_MAPPE}/')}",
        "bye",
        "",
    ])
    _kør_lftp(script)

