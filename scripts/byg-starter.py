#!/usr/bin/env python3
"""
byg-starter.py — Byg haven-starter-v{version}.tar.gz til distribution.

Kør fra projektroden:
    python scripts/byg-starter.py
    python scripts/byg-starter.py --version 0.7.0

Starteren er tom — brugeren kører "have init" efter installation.
"""

import argparse
import shutil
import tarfile
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# Enkeltfiler der kopieres direkte
FRAMEWORK_FILER = [
    "pyproject.toml",
    "LICENSE",
    "LICENSE-INDHOLD.md",
    ".gitignore",
    ".env.eksempel",
]


def læs_version() -> str:
    """Læs __version__ fra haven/__init__.py uden at importere modulet."""
    for linje in (PROJECT_ROOT / "haven" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if linje.startswith("__version__"):
            return linje.split('"')[1]
    raise RuntimeError("Kunne ikke finde __version__ i haven/__init__.py")


def byg(version: str, output_mappe: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        starter = Path(tmpdir) / "haven-starter"
        starter.mkdir()

        # haven/-pakke
        shutil.copytree(
            PROJECT_ROOT / "haven", starter / "haven",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

        # Enkeltfiler
        for navn in FRAMEWORK_FILER:
            src = PROJECT_ROOT / navn
            if src.exists():
                shutil.copy2(src, starter / navn)
            else:
                print(f"  ⚠ Mangler: {navn}")

        # docs/ (templates og static er pakkedata i haven/)
        shutil.copytree(PROJECT_ROOT / "docs", starter / "docs")

        # data/-mappe — planter.yaml genereres af have init
        (starter / "data").mkdir()

        # Fotos-struktur med placeholder
        (starter / "fotos" / "planter").mkdir(parents=True)
        (starter / "fotos" / "entries").mkdir(parents=True)
        shutil.copy2(
            PROJECT_ROOT / "fotos" / "planter" / "placeholder.jpg",
            starter / "fotos" / "planter" / "placeholder.jpg",
        )

        # Sanitiseret haven.yaml (fra haven.eksempel.yaml)
        shutil.copy2(PROJECT_ROOT / "haven.eksempel.yaml", starter / "haven.yaml")

        # Starter-README (fra docs/starter-readme.md)
        shutil.copy2(PROJECT_ROOT / "docs" / "starter-readme.md", starter / "README.md")

        # Pack tar.gz
        output_mappe.mkdir(parents=True, exist_ok=True)
        output = output_mappe / f"haven-starter-v{version}.tar.gz"
        with tarfile.open(output, "w:gz") as tar:
            tar.add(starter, arcname="haven-starter")

        størrelse = output.stat().st_size // 1024
        print(f"✓ {output} ({størrelse} KB)")
        return output


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Versionsnummer (standard: læses fra have.py)",
    )
    parser.add_argument(
        "--dir",
        default=None,
        metavar="MAPPE",
        help="Output-mappe til tar.gz (standard: projektroden)",
    )
    args = parser.parse_args()

    version = args.version or læs_version()
    output_mappe = Path(args.dir).expanduser().resolve() if args.dir else PROJECT_ROOT
    print(f"Bygger haven-starter v{version}...")
    byg(version, output_mappe)


if __name__ == "__main__":
    main()
