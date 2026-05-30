# Changelog

Alle bemærkelsesværdige ændringer i dette projekt dokumenteres her.
Format følger [Keep a Changelog](https://keepachangelog.com/da/1.0.0/).

## [1.1.0] — 2026-05-30

### Tilføjet
- **Høns-modul** — ny zone-type `husdyr` til registrering af en hønseflok.
  - `data/dyr.yaml` — dyreregister indlæst til `DYR_DB` (samme mønster som `planter.yaml`/`PLANTE_DB`).
  - Zone-fil `data/{år}/hons.yaml` med `meta.type: husdyr` aktiverer hønse-template og hønse-ICS. Zoner uden `type` behandles som hidtil (plantezoner).
  - Hønse-entries i `data/{år}/entries/hons/` som YAML-filer med typerne `æglægning`, `ruge-start`, `foderkøb`, `sundhedsobs`, `dødsfald` og `fjerfældning`.
  - `have hons ny-obs` — wizard til at registrere en observation. Ved `ruge-start` beregnes `forventet_klæk` (dato + 21 dage); felter der refererer en høne bruger autocomplete over aktive høner. Ved `dødsfald` markeres hønen `aktiv: false` i `dyr.yaml`.
  - `have hons ny-høne` — wizard til at tilføje en høne; `id` genereres som `slug(race-farve)-løbenummer`.
  - HTML-side (`hons.html`) med høne-register og kronologisk observationslog, integreret i navigationen som øvrige zoner.
  - `hons-{år}.ics` — ICS-kalender med forventede klækninger fra `ruge-start`-entries.

### Rettet
- Build crashede (`AttributeError` i `kontrast_farve`) hvis en plante havde `farve: null`. `aktiv_afgrøde`/`zone_succession` coalescer nu None til standardfarven, og `kontrast_farve` håndterer manglende/ugyldig hex robust.

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
