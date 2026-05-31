# YAML-skema

Dokumentation af alle YAML-filer i haven. Felter markeret `(påkrævet)` skal altid
være til stede — øvrige er valgfri og kan udelades.

Pydantic-modellerne i `haven/models.py` dækker i dag `planter.yaml`. Når de
øvrige formater modelleres, kan denne fil auto-genereres fra skemaerne.

---

## haven.yaml

Runtime-konfiguration. Ligger altid i projektroden.

```yaml
aktivt_år: 2026           # (påkrævet) det år der bygges og vises som standard

stier:                    # stier relativt til projektroden — sjældent nødvendigt at ændre
  data: data
  out: out
  fotos: fotos

bede:                     # (påkrævet) navne på YAML-filer i data/{aktivt_år}/
  - højbedshaven          # svarer til data/2026/højbedshaven.yaml
  - krydderurter

site:
  basis_url: "https://eksempel.dk"   # (påkrævet for RSS og iCal) rodadresse

features:
  ics_kalender: true      # generer have-{år}.ics
  rss_feeds: true         # generer have-dagbog.rss og have-almanak.rss

kontakt_email: ""         # valgfri — sendes med i User-Agent ved Wikimedia-downloads

hero_billede: fotos/min-have.jpg   # valgfri — baggrundsbillede på forsiden

deploy:
  protokol: [ftp, sftp]   # "sftp", "ftp", "ingen" — eller en liste for flere mål
                          # (uploader i nævnt rækkefølge; overstyr med: have deploy --protokol sftp)
  sftp:
    host: eksempel.dk
    bruger: mit_brugernavn
    mappe: www
    # Adgangskode: HAVE_SFTP_KODE miljøvariabel eller .env
  ftp:
    host: eksempel.dk
    bruger: mit_brugernavn
    mappe: /haven
    # Adgangskode: HAVE_FTP_KODE miljøvariabel eller .env
```

---

## data/planter.yaml

Central plantedatabase. Deles på tværs af alle år — ændres aldrig af `have nyt-år`.

```yaml
meta:                     # valgfri — bruges til forsidekortet for planteregistret
  titel: Planteregister
  html_navn: planter
  undertitel: "Alle sorter med kalender og noter"
  beskrivelse: "..."
  ikon: 🌿
  tags: [Drivhuset, Frugthaven]

planter:                  # liste af planter (eller direkte liste uden nøgle)
  - id: tomater-money-maker  # (påkrævet) slugificeret "{navn} {sort}" — kun a-z, 0-9, bindestreg
                             # æ→ae, ø→oe, å→aa. Genereres automatisk af `have ny-plante`.
    navn: Tomater         # (påkrævet) artsnavn vist på siden
    sort: Money Maker     # sortsnavne (vises som undertitel)
    latin: "Solanum lycopersicum"
    familie: Natskyggefamilien  # plantefamilie — udfyldes automatisk af `have hent-fotos`
    wikipedia: Tomato     # Wikipedia-sidtitel — bruges til billedsøgning
    wikidata: Q23240      # Wikidata QID — bruges til P18-billede (foretrækkes frem for wikipedia)
    farve: "#e53935"      # (påkrævet) hex-farve til bedtegningen
    placering: Sol        # fritekst — Sol / Halvskygge / Skygge
    afstand: 50           # cm mellem planter i rækken
    rækkeafstand: 70      # cm mellem rækker
    sådybde: 0.5          # cm
    indendørs: 3          # måned (1–12) for forspiring indendørs
    direkte: null         # måned for direkte såning udendørs
    udplantning: 5        # måned for udplantning
    høst_fra: 7           # måned høst begynder
    høst_til: 10          # måned høst slutter
    noter: "Udplantes i drivhuset — ikke friland."
    pasning: "Toppes ved 1,5 m. Fjern sideskud ugentligt."  # pasningsvejledning vist på plante-kortet
    foto:
      fil: money-maker.jpg    # filnavn i fotos/planter/
      licens: CC BY-SA 4.0
      forfatter: Hans Jensen
      kilde: https://commons.wikimedia.org/wiki/File:...
```

Kalenderfelterne `indendørs`, `direkte`, `udplantning`, `høst_fra`, `høst_til` angives
alle som heltal 1–12. En plante med `høst_fra: 10` og `høst_til: 3` tolkes som
wrap-around (efterår til forår).

**Id-konvention:** `have ny-plante` foreslår automatisk et id baseret på navn og sort via
`slugify()`: æ→ae, ø→oe, å→aa, kun a-z/0-9/bindestreg. Eksempler:
`Gulerødder Nantes` → `guleroedder-nantes`, `Dild` (ingen sort) → `dild`.

---

## data/{år}/{bed}.yaml

Én fil pr. haveafsnit pr. sæson, fx `data/2026/drivhus.yaml`.

```yaml
meta:
  år: 2026                # (påkrævet) skal matche aktivt_år i haven.yaml
  titel: "Drivhuset"      # (påkrævet) vises i navigation og som sidetitel
  html_navn: "drivhus"    # (påkrævet) output-filnavn uden .html — url-venlig streng
  ikon: "🏡"              # emoji vist i navigation
  ikon_billede: "fotos/drivhus.jpg"   # rund thumbnail til forsidekortet (overstyrer ikon)
  undertitel: "Tomater, agurker & peberfrugter"
  beskrivelse: "..."      # vist i forsidekortet
  tags: [Tomater, Agurker]

bede:
  - id: drivhus-nord      # (påkrævet) unik streng inden for filen
    navn: "Det store drivhus — nord"   # vises over bedtegningen
    bredde_cm: 200        # bruges til proportional tegning
    dybde_cm: 100
    farve: "#e3f2fd"      # baggrundsfarve i tegningen
    beskrivelse: "..."
    zoner:
      # Simpelt format — én plante pr. zone
      - navn: "Tomater"
        bredde: 0.5       # relativ bredde (summer ikke nødvendigvis til 1)
        plante_id: money-maker   # matcher id i planter.yaml
        antal: 6          # antal planter vist i tegningen
        note: "Toppes ved 1,5 m"   # kort note vist i tegningen

      # Sædskifte — flere afgrøder i samme zone hen over sæsonen
      - navn: "Kartofler → Majroer"
        bredde: 0.33
        afgrøder:
          - plante_id: solist
            fra: 4        # måned afgrøden starter (1–12)
            til: 7        # måned afgrøden slutter
          - plante_id: goldball
            fra: 7
            til: 10

kalender_planter:         # planter der vises i sæsonkalenderen for dette afsnit
  - filippa               # plante_id fra planter.yaml
  - ingrid-marie
```

---

## Husdyr-zone (høns)

En zone-fil med `meta.type: husdyr` behandles som en husdyr-zone i stedet for
en plantezone. Den får en alternativ HTML-side (høne-register + observationslog)
og et eget wizard-sæt (`have hons …`). Zoner **uden** `type`-felt behandles som
hidtil (plantezoner).

### data/{år}/hons.yaml

```yaml
meta:
  år: 2026
  titel: "Hønsehuset"
  html_navn: "hons"       # output-filnavn + mappe-navn for entries
  ikon: "🐔"
  type: husdyr            # (påkrævet for husdyr-zone) aktiverer hønse-template
  undertitel: "Æg, rugning & flokkens trivsel"
  beskrivelse: "..."
  tags: [Høns, Æg]
```

### data/dyr.yaml

Globalt dyreregister, delt på tværs af år (samme niveau som `planter.yaml`).
Indlæses til `DYR_DB`. Tilføj høner med `have hons ny-høne`. Registret vises
som sin egen side `hoenseregisteret.html` (link i topnavigationen ved siden af
Planter) — samme mønster som planteregistret.

```yaml
- id: australorp-sort-1   # (påkrævet) slug, bruges som reference i entries
  navn: Berta             # valgfri — vises som overskrift på hønsekortet
  race: Australorp        # (påkrævet) fritekst
  farve: sort             # fritekst — skelner individer af samme race
  fødselsdato: 2023-04-12  # valgfri, ISO-dato (vises som "kom til verden" + alder)
  aktiv: true             # default true; sættes false ved dødsfald
  noter: "Flokkens leder"  # valgfri fritekst
  foto:                   # valgfri — billedfil i fotos/dyr/ (thumbs autogenereres)
    fil: berta.jpg        #   ekstern URL (http…) bruges direkte
    forfatter: Mikkel
```

### data/{år}/entries/hons/

Én YAML-fil pr. observation (`{dato}-{type}.yaml`). Felter pr. `type`:

```yaml
# æglægning
dato: 2026-05-30
type: æglægning
æg: 4
noter: "Rosa lagde ikke i dag"

# ruge-start — forventet_klæk = dato + 21 dage (beregnes af wizarden),
#              giver en VEVENT i hons-{år}.ics
dato: 2026-05-30
type: ruge-start
høne: australorp-sort-1   # id fra dyr.yaml
æg_antal: 9
forventet_klæk: 2026-06-20

# foderkøb
dato: 2026-05-30
type: foderkøb
foder_type: pellets
mængde_kg: 25
pris: 189
butik: Agrovi

# sundhedsobs — høne valgfri (tom = hele flokken)
dato: 2026-05-30
type: sundhedsobs
høne: australorp-sort-1
observation: "halter på venstre ben"
handling: "isoleret, holdes under observation"

# dødsfald — wizarden sætter aktiv: false på hønen i dyr.yaml
dato: 2026-05-30
type: dødsfald
høne: australorp-sort-1
årsag: ukendt

# fjerfældning — fase: start eller slut
dato: 2026-05-30
type: fjerfældning
fase: start
```

---

## data/{år}/almanak.yaml

Havealmanak med månedsvise indledninger og begivenheder pr. haveafsnit.

```yaml
meta:
  titel: "Havealmanak"
  html_navn: "almanak"    # output-filnavn — bør altid være "almanak"
  undertitel: "Alle havens dele samlet"
  beskrivelse: "..."
  ikon: "📖"
  tags: [Højbedshaven, Drivhuset]

måneder:
  - måned: 1              # (påkrævet) heltal 1–12
    navn: "Januar"        # vises som overskrift
    indledninger:         # én pr. haveafsnit — tekst øverst i almanakken for måneden
      - område_id: hoejbede   # matcher html_navn fra bed-YAML
        tekst: "Havens hvilemåned."
    begivenheder:         # konkrete opgaver for måneden
      - område_id: hoejbede
        tekst: |
          Bestil frø og løg til sæsonen.
```

---

## data/{år}/entries/sektioner/{dato}-{zone}.md

Dagbogspost som Markdown-fil med YAML-frontmatter.
Filnavnet er blot en konvention — indholdet styres af frontmatter.
Oprettes automatisk af `have ny-entry`.

```markdown
---
dato: 2026-04-26          # (påkrævet) ISO-dato
zone: drivhus             # (påkrævet) matcher html_navn fra bed-YAML
plante_id: tomater-money-maker  # valgfri — én eller liste af plante-id'er
foto: 2026-04-26-drivhus.jpg    # valgfri — filnavn i fotos/entries/{år}/
---

Tomaterne begynder at sætte blomster. Vandes dagligt.
```

Fotos gemmes i `fotos/entries/{år}/` og kopieres til `out/{år}/fotos/entries/` ved
build. Thumbnails genereres automatisk.

> **Mappestruktur for entries:**
> `entries/sektioner/` — markdown-entries for bede og havezoner
> `entries/hons/`      — YAML-entries for hønsemodulet (se Husdyr-zone)

---

## data/{år}/entries.yaml

Ældre format — erstattes løbende af markdown-filer ovenfor. Begge formater
læses og blandes i outputtet.

```yaml
entries:
  - dato: 2026-04-26
    område_id: drivhus    # matcher html_navn fra bed-YAML
    tekst: "Tomaterne spirer."
    foto:
      fil: 2026-04-26-drivhus.jpg
      tekst: "Tomater i drivhuset"
```

---

## data/om.yaml

Indhold til Om-siden (`out/om.html`).

```yaml
titel: "Om siden"
html_navn: "om"           # bør altid være "om"

indhold:
  - tekst: >
      Velkommen til min have. Her dokumenterer jeg sæsonen.
  - tekst: >
      Siden genereres automatisk fra YAML-filer via have.py.
```

---

## data/kontakt.yaml

Indhold til Kontakt-siden (`out/kontakt.html`).

```yaml
titel: "Kontakt"
html_navn: "kontakt"      # bør altid være "kontakt"

indhold:
  - tekst: >
      Har du spørgsmål, er du velkommen til at tage kontakt.

kontakt:
  - label: "E-mail"
    værdi: "din@email.dk"
    link: "mailto:din@email.dk"   # valgfri — gør værdien klikbar
  - label: "Hjemmeside"
    værdi: "eksempel.dk"
    link: "https://eksempel.dk"
```
