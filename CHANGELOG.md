# Changelog

Alle bemærkelsesværdige ændringer i dette projekt dokumenteres her.
Format følger [Keep a Changelog](https://keepachangelog.com/da/1.0.0/).

## [1.0.0] — 2026-05-18

### Tilføjet
- `have plant-en-plante` — wizard til at plante en afgrøde i en zone med visning af ledig bredde.
- `have riv-en-plante-op` — wizard til at fjerne en afgrøde fra en zone.
- `have ret-i-plante-yaml` — rediger plantedata direkte fra terminalen.
- Efterafgrøde-understøttelse i plant- og riv-wizards.
- Bed-navigation med månedsvælger og succession-tidslinje.
- Zone-hover-effekt og pil-indikator (`›`) i bedvisningen.
- Auto-optimering af for store fotos ved `have hent-havefotos`.
- `have ny-entry` advarer hvis dato-år afviger fra `aktivt_år`.
- `lokation`-felt i `haven.example.yaml` til brug med `have hent-vejr`.
- Integrationstest der smoke-tester `init → nyt-år → build`.

### Rettet
- `have watch` kaldte `python have.py` i stedet for `have build` — rettet.
- Skjulte filer (`.`-prefix) springes nu over ved YAML-indlæsning og `nyt-år`.
- Overlappende afgrøder: senest-startende afgrøde vises nu (sidst-starter-vinder).
- Forældede referencer i `have check` rettet (`hent_plantefotos.py` → `have hent-fotos`, `have.py` → `haven.yaml`).
- `scripts/byg-starter.py` refererede til `haven.eksempel.yaml` i stedet for `haven.example.yaml`.
- `haven/config.py` understøtter nu `HAVEN_ROOTDIR`-miljøvariabel til brug i tests.

## [0.9.0] — 2025-05-10

### Tilføjet
- `have hent-vejr` — henter historisk vejrdata fra Open-Meteo og skriver månedlig statistik til `almanak.yaml`.
- Vejr-sparklines og daglige vejrgrafer per måned på almanaksiden.
- Tab-completion via `argcomplete`.
- Eksempel-entries i `init` og eksempeldata.

### Rettet
- Tomme områder skjules nu i samlet arkiv.
- Samlet arkiv viser nu korrekt planter fra zoner med direkte `plante_id`.
- Manglende `valgt_plante`-reference i `nyt-bed` print-sætning.
