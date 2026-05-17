# Changelog

Alle bemærkelsesværdige ændringer i dette projekt dokumenteres her.
Format følger [Keep a Changelog](https://keepachangelog.com/da/1.0.0/).

## [Ikke udgivet]

### Tilføjet
- `have plant-en-plante` — ny interaktiv wizard til at plante en plante i et eksisterende bed. Guider brugeren gennem valg af område → bed (med visning af ledig bredde) → plantsøgning → zonenavn og bredde. Advarer hvis bredden overstiger tilgængelig plads.
- `have ny-entry` advarer nu hvis det indtastede dato-år afviger fra `aktivt_år` — brugeren kan bekræfte og fortsætte.
- `lokation`-felt tilføjet til `haven.example.yaml` med eksempelkoordinater (bruges af `have hent-vejr`).
- Integrationstest (`tests/test_integration.py`) der smoke-tester `init → nyt-år → build` i isoleret temp-mappe.

### Rettet
- `scripts/byg-starter.py` refererede til `haven.eksempel.yaml` i stedet for `haven.example.yaml`.
- `haven/config.py` understøtter nu `HAVEN_ROOTDIR`-miljøvariabel til at overstyre projektroden (bruges af tests).

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
