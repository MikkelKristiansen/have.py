# Kom i gang med have.py på 5 minutter

have.py laver et responsivt website ud af nogle tekstfiler. Du beskriver dine
planter og bede i YAML-filer, og have.py bygger et site du kan planlægge,
dokumentere og dele din have med — sæson for sæson.

**Det eneste krav er Python 3.11 eller nyere.** Outputtet er rene HTML-filer:
ingen database, ingen server-software. Du behøver kun en browser for at se det —
og et hvilket som helst sted der kan vise filer, hvis du vil lægge det online.

---

## 1. Installér · 1 min

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
```

> Bruger du start-skabelonen, er der allerede en `haven.yaml`. Kloner du i stedet
> kode-repoet, så lav din egen først: `cp haven.example.yaml haven.yaml`

## 2. Sæt haven op · 1 min

```bash
have init
```

Wizarden spørger om havens navn, hvilke haveafsnit du vil have med (højbede,
drivhus, frugthave, krydderurter …) og — hvis du vil — en deploy-server (tryk
bare Enter for at springe over). Den skriver dine YAML-filer i `data/`.

## 3. Byg sitet · 30 sek

```bash
have build
```

Sitet ligger nu i `out/`. Åbn **`out/index.html`** i din browser — der er din have.

## 4. Tilføj din første plante · valgfrit, 2 min

```bash
have ny-plante          # interaktiv: navn, latinsk navn, så- og høstkalender …
have plant-en-plante    # placér planten i et af dine bede
have build              # byg igen og genindlæs siden i browseren
```

> Tip: `have watch` bygger automatisk hver gang du gemmer en YAML-fil — lad den
> køre mens du arbejder.

## 5. Læg det online · valgfrit

Alt i `out/` er statiske filer, så du kan:

- uploade `out/` til et hvilket som helst webhotel, eller lægge det på fx GitHub
  Pages eller Netlify — eller
- lade have.py gøre det: udfyld `deploy` i `haven.yaml` og adgangskoden i `.env`,
  og kør `have deploy`.

---

## Hvad nu?

- **Rediger indhold** i `data/` — den fulde feltdokumentation er i [`skema.md`](skema.md).
- **De daglige kommandoer** (`have check`, `have nyt-år`, `have ny-entry`,
  `have hent-fotos` …) står i [README](../README.md).
- **Avanceret, helt valgfrit:** kør have.py på flere maskiner og tilføj en
  mobil-webapp til at registrere direkte i haven — se [`sync.md`](sync.md).

Held og lykke i haven. 🌿
