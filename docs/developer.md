# haven

> Statisk havesite-generator i Python — for haven du planlægger, dyrker og dokumenterer.

## Hvad er det?

haven er et personligt haveværktøj der omdanner YAML-filer til et statisk website. Jeg bruger det til at planlægge sæsonen, holde styr på hvad der er sået hvornår og dokumentere haven løbende med billeder og noter.

Ingen database, ingen framework, ingen cloud. Data bor i tekstfiler, output er HTML du kan åbne i en browser eller lægge på en server.

## Funktioner

- Separate sider pr. haveafsnit (højbede, krydderurter, frugthave, drivhus)
- Plante-oversigt med sæsonkalender på tværs af hele året
- Plantefotos hentes automatisk fra Wikimedia Commons med licens-kreditering
- iCal-kalender og RSS-feeds genereres automatisk
- Dagbogsindlæg pr. bed med billeder
- Responsivt design — virker på mobil og desktop
- Årsbaseret struktur så historikken bevares år for år

## Quickstart

Kræver Python 3.11 eller nyere.

```bash
git clone <REPO-URL>
cd have.py
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
have
```

Det færdige site ligger i `out/`. Åbn `out/index.html` i en browser (redirecter til det aktive år).

Byg automatisk når du redigerer YAML-filer:

```bash
have watch
```

Hent plantefotos fra Wikimedia Commons:

```bash
have hent-fotos              # tør kørsel — viser hvad der ville ske
have hent-fotos --skriv      # gem billeder og opdatér planter.yaml
```

## Konfiguration

Al runtime-konfiguration ligger i `haven.yaml` i projektroden:

```yaml
aktivt_år: 2026          # hvilket år der bygges

bede:                    # YAML-filer i data/{aktivt_år}/ der rendres som haveafsnit
  - højbedshaven
  - krydderurter
  - frugthaven
  - drivhus

site:
  basis_url: "https://example.com"   # bruges i RSS-feeds og iCal

deploy:
  protokol: [ftp, sftp]  # "sftp", "ftp", "ingen" — eller en liste for flere mål
  sftp:
    host: example.com
    bruger: mit_brugernavn
    mappe: www
    # Adgangskode: export HAVE_SFTP_KODE=ditpassword
```

Adgangskoder gemmes aldrig i `haven.yaml`. Sæt dem via `.env`:

```bash
cp .env.eksempel .env
# Rediger .env og indsæt dine adgangskoder
```

## Tilpas til din egen have

Redigér YAML-filerne i `data/2026/` — én fil pr. haveafsnit. Hvert bed beskrives med zoner, og hver zone refererer til en plante i `data/planter.yaml` via `plante_id`:

```yaml
# data/2026/højbedshaven.yaml
bede:
  - id: bed-1
    navn: Bed 1
    bredde_cm: 120
    dybde_cm: 80
    zoner:
      - navn: Gulerødder
        bredde: 0.5
        plante_id: nantes     # matcher id i data/planter.yaml
```

Se [`docs/skema.md`](docs/skema.md) for fuld dokumentation af alle felter i alle YAML-filer.

Når en ny sæson starter:

```bash
have nyt-år 2027
```

## Projektstruktur

```
haven/               # Python-pakke (CLI, generator, config)
haven/templates/     # Jinja2-skabeloner (pakkedata — kopieres ud ved have init)
haven/static/        # CSS (pakkedata — kopieres ud ved have init)
haven.yaml           # Runtime-konfiguration (aktivt år, bede, deploy)
data/planter.yaml    # Fælles plantedatabase (deles på tværs af år)
data/{år}/           # YAML-data pr. sæson
fotos/planter/       # Kilde-plantefotos (downloades med have hent-fotos)
fotos/entries/{år}/  # Egne havebilleder pr. sæson
out/                 # Genereret site (ikke i git)
docs/skema.md        # YAML-feltdokumentation
```

## Kommandooversigt

```bash
have                 # byg alle sider
have build           # samme som ovenfor
have deploy          # byg + upload til server
have watch           # byg automatisk ved filændringer
have check           # validér YAML og krydsreferencér planter mod bede
have nyt-år 2027     # klargør ny sæson
have ny-plante       # tilføj plante til planter.yaml (interaktiv wizard)
have ny-entry        # opret dagbogspost (interaktiv wizard)
have hent-fotos      # hent plantefotos fra Wikimedia Commons
have hent-havefotos  # tjek og synkronisér almanakfotos
have nyt-bed         # opret nyt bed i en havezone, fx. et nyt bed i et højbed
```

## Licens

Kildekoden er udgivet under [MIT](LICENSE).

YAML-filer, eksempelfiler og dokumentation er udgivet under [CC BY 4.0](LICENSE-INDHOLD.md).

Plantefotos hentet via `have hent-fotos` er fra Wikimedia Commons og underlagt deres egne licenser — kreditering rendres på det publicerede site.
