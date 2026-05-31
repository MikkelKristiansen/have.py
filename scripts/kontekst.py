#!/usr/bin/env python3
"""Genererer en kompakt kontekstfil til brug i browser-Claude eller andre LLM-sessioner."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

BESKRIVELSE = """\
# haven – projektkontekst

## Hvad er det?
haven er en statisk sitegenerator til personlig haveplanlægning, skrevet i Python.
YAML-datafiler → responsivt HTML-site med planter, bede, dagbog og kalender.
Ingen database, ingen framework — rene tekstfiler og statisk HTML.
Sprog: dansk (kode, UI og dokumentation).

## Nøglefiler
- `haven/cli.py`        Hoved-entrypoint og al HTML-generering (~6000 linjer)
- `haven/models.py`     Pydantic-modeller (Plante, FotoModel)
- `haven/config.py`     Konfigurationsindlæsning (haven.yaml + .env)
- `haven/fotos.py`      Fotohåndtering og Wikimedia-integration
- `haven/wikidata.py`   Wikidata SPARQL-forespørgsler
- `haven/havefotos.py`  Dagbogsfotos (validering og synkronisering)
- `haven/templates/`    Jinja2-skabeloner (base, have, almanak, planter, søg)
- `scripts/byg-starter.py`  Bygger distribuerbar starter-pakke

## Datastruktur (3 YAML-typer)
1. `data/planter.yaml`           Global plantedatabase (deles på tværs af år)
2. `data/{år}/{bed}.yaml`        Havelayout for et specifikt år (ét bed pr. fil)
3. `data/{år}/almanak.yaml`      Årskalender med opgaver og noter

## CLI-kommandoer
```
have build          # Generer HTML til out/{aktivt_år}/
have watch          # Auto-rebuild ved YAML-ændringer
have check          # Valider YAML og krydsreferencer
have deploy         # build + upload (SFTP eller FTP)
have ny-plante      # Tilføj plante (interaktiv)
have ny-entry       # Ny dagbogsindtastning (interaktiv)
have ny-bed         # Nyt bed i en zone (interaktiv)
have nyt-år YYYY    # Klargør ny havesæson
have hent-fotos     # Hent plantefotos fra Wikimedia (dry-run)
```

## Validering (3 lag)
L1: YAML-syntaks (PyYAML)
L2: Struktur (Pydantic)
L3: Krydsreferencer (plant_id, fotostier)

## Konfiguration
`haven.yaml` i projektroden styrer aktivt år, bede og deploy-protokol.
Credentials (SFTP/FTP) kun i `.env`, aldrig i YAML.

## Stack
Python 3.11+, Jinja2, PyYAML, Pydantic, Pillow, ruamel-yaml, questionary, livereload
"""


def git_log(antal: int = 15) -> str:
    try:
        resultat = subprocess.run(
            ["git", "log", f"--max-count={antal}", "--pretty=format:%h %s (%ad)", "--date=short"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return resultat.stdout.strip()
    except subprocess.CalledProcessError:
        return "(kunne ikke hente git log)"


def git_status() -> str:
    try:
        resultat = subprocess.run(
            ["git", "status", "--short"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return resultat.stdout.strip() or "(ingen ucommittede ændringer)"
    except subprocess.CalledProcessError:
        return "(kunne ikke hente git status)"


def byg_kontekst(antal_commits: int = 15) -> str:
    linjer = [
        BESKRIVELSE,
        "## Seneste commits",
        "```",
        git_log(antal_commits),
        "```",
        "",
        "## Nuværende status",
        "```",
        git_status(),
        "```",
    ]
    return "\n".join(linjer)


def main() -> None:
    antal = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    kontekst = byg_kontekst(antal)

    ud_fil = ROOT / "KONTEKST.md"
    ud_fil.write_text(kontekst, encoding="utf-8")
    print(f"Kontekst skrevet til {ud_fil}")
    print(f"({kontekst.count(chr(10))} linjer, {len(kontekst)} tegn)")


if __name__ == "__main__":
    main()
