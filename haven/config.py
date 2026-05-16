"""Config-loader for haven.

Stiller load_config() til rådighed for både have.py og scripts/.
Finder haven.yaml relativt til denne fils placering, ikke til cwd.
"""

from pathlib import Path
import os
import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CONFIG_FIL = PROJECT_ROOT / "haven.yaml"

load_dotenv(PROJECT_ROOT / ".env", override=True)


def load_config() -> dict:
    if not CONFIG_FIL.exists():
        raise FileNotFoundError(
            f"haven.yaml ikke fundet på {CONFIG_FIL}. "
            f"Opret den i projektroden — se README.md for skema."
        )
    with open(CONFIG_FIL, encoding="utf-8") as f:
        return yaml.safe_load(f)


def data_mappe(config: dict) -> Path:
    return PROJECT_ROOT / config["stier"]["data"] / str(config["aktivt_år"])


def out_mappe(config: dict) -> Path:
    return PROJECT_ROOT / config["stier"]["out"] / str(config["aktivt_år"])


def sti(config: dict, navn: str) -> Path:
    return PROJECT_ROOT / config["stier"][navn]


def sftp_adgangskode() -> str:
    return os.environ.get("HAVE_SFTP_KODE", "")


def ftp_adgangskode() -> str:
    return os.environ.get("HAVE_FTP_KODE", "")
