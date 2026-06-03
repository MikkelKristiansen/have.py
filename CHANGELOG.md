# Changelog

Alle bemærkelsesværdige ændringer i dette projekt dokumenteres her.
Format følger [Keep a Changelog](https://keepachangelog.com/da/1.0.0/).

## [Unreleased]

## [1.2.0] — 2026-06-03

### Tilføjet
- **Æglægnings-graf på Hønsehuset** — ugentlige søjler (ISO-uge × antal æg) vises
  som inline SVG mellem høne-register og observationslog på `hons.html`. Ingen JS,
  ingen eksterne afhængigheder — deterministisk ren Python, samme mønster som
  vejr-SVG'erne i almanakken.
  Nøgletal: total, snit pr. uge, bedste dag og (hvis aktive høner > 0) æg pr. høne pr. uge.
  Sektionen vises kun når der er registrerede æglægninger.
- **Frøsamling** — `data/frø.yaml` (rod-niveau, år-uafhængig som `planter.yaml`) med
  oversigtsside `frø.html`, wizard `have ny-frø` og inbox-understøttelse for
  `type: frøindkøb`. `have check` validerer blødt. Nav-link vises kun når filen eksisterer.
- **Naboer og skadedyr i planteregisteret** — nye valgfrie felter `naboer` og `skadedyr`
  på plante-niveau i `planter.yaml`. Vises i en `<details>`-accordion på hvert plantekort.
  `have check` advarer blødt ved ukendte nabo-`plante_id`'er.
- **Naboadvarsler i bed-visningen** — tilstødende zoner med kendte naborelationer vises
  med grønne/gule badges direkte i bed-layoutet (`have.html`).

## [1.1.1] — 2026-06-02

### Tilføjet
- **Accordion-sektioner** — bede i sektionsoversigten kan foldes ud/ind via `<details>`.
  JavaScript åbner automatisk bede med aktive afgrøder i den aktuelle måned og lukker øvrige.
- **Accordion i havealmanak** — almanakdelen i `have.html` (indlejret pr. bed-YAML-side)
  bruger nu `<details>`/`<summary>` med `open` på den aktuelle måned, svarende til `almanak.html`.
  `aktuel_måned` tilføjet til `generer_html`-konteksten.
- **"Fold alle ud/sammen"-knap** — ny knap ved Havealmanak (`have.html`) og
  Månedsoversigt (`almanak.html`). Fælles JavaScript i `base.html` håndterer toggle og
  opdaterer knapteksten dynamisk via `toggle`-eventet.
- **Id-forslag i `have ny-plante`** — navn og sort spørges nu før id. Wizarden
  foreslår automatisk et slugificeret id via `plante_id(navn, sort)`.
- **`slugify()` og `plante_id()`** — nye hjælpefunktioner i `cli.py` til
  konsistent slugificering (æ→ae, ø→oe, å→aa, kun a-z/0-9/bindestreg).
- **`entries/sektioner/`-mappe** — markdown-entries for bede og havezoner flyttes
  til `data/{år}/entries/sektioner/` (hønse-entries forbliver i `entries/hons/`).
  `generer_html`, `generer_almanak` og `opret_entry` opdateret tilsvarende.

### Ændret
- **`cli.py` opdelt i moduler** — den ~6.500 linjers `cli.py` er opdelt i et lagdelt
  modulhierarki (se `briefs/cli-opdeling.md`): `kontekst`, `indlaes`, `validering`,
  `skabeloner`, render-laget (`generering`, `feeds`, `soeg`, `hoens`, `almanak`),
  `byg` (orkestrator), samt handlerne `scaffold`, `deploy`, `vejr`, `wizards`.
  `cli.py` er nu kun entry point (argparse + dispatch, ~310 linjer). `inbox.py`'s
  imports repointet fra `cli` til de nye moduler. Ren intern refaktorering uden
  adfærdsændring — byg-output er byte-identisk (pånær iCal-tidsstempler).

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
