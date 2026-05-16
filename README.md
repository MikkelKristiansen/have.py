# haven — starter

En tom have-skabelon klar til at komme i gang med
[haven](https://github.com/mikkeljk/have.py).

## Kom i gang

Forudsætter Python 3.11 eller nyere.

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
have init
```

Wizarden guider dig igennem opsætning af haven — navn, haveafsnit,
undertitler og deploy-konfiguration.

Kør derefter:

```bash
have build
```

Sitet ligger i `out/`. Åbn `out/index.html` i en browser.

## Daglig brug

```bash
have build           # byg sitet
have watch           # byg automatisk ved ændringer
have check           # validér YAML og krydsreferencér planter mod bede
have nyt-år 2027     # opret ny sæson
have ny-plante       # tilføj plante til planter.yaml (interaktiv wizard)
have ny-entry        # opret dagbogspost (interaktiv wizard)
have nyt-bed         # opret nyt bed i en havezone, fx. et nyt bed i et højbed
have hent-fotos      # hent plantefotos fra Wikimedia Commons
have deploy          # byg + upload til server
```

## YAML-filer

Indholdet redigeres i tre typer filer:

| Fil | Beskrivelse |
|-----|-------------|
| `data/planter.yaml` | Fælles plantedatabase med kalenderdata og fotos |
| `data/{år}/{bed}.yaml` | Ét haveafsnit med bede, zoner og planter |
| `data/{år}/almanak.yaml` | Månedsvise begivenheder og noter |

Se den fulde feltdokumentation i [`docs/skema.md`](docs/skema.md).

## Konfiguration

`haven.yaml` er din lokale konfigurationsfil og er ikke inkluderet i repositoriet.
Kopiér eksempelfilen og tilpas den:

```bash
cp haven.example.yaml haven.yaml
```

Rediger `haven.yaml` og sæt mindst `aktivt_år` og `bede` til dine egne værdier.
Se kommentarerne i filen for forklaring af hvert felt.

## Adgangskoder til deploy

```bash
cp .env.eksempel .env
# Rediger .env og indsæt adgangskode
```

## Licens

Se `LICENSE` (kode, MIT) og `LICENSE-INDHOLD.md` (indhold, CC BY 4.0).
