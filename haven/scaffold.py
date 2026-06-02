"""haven.scaffold — skabelon-strenge og YAML-bygning til init/nyt-år/nyt-område.

Selvstændigt modul (ingen haven-afhængigheder) i cli-opdelingen (se
briefs/cli-opdeling.md, fase 5). De lange init-skabeloner og _lav_*-hjælpere
bruges af wizards.py (init_projekt, nyt_område, nyt_år).
"""

__all__ = [
    "INIT_YAML", "INIT_ALMANAK", "_OM_YAML", "_KONTAKT_YAML", "_PLANTER_YAML",
    "_META_FELTER_DEFAULT", "_STARTER_BEDE", "_ALMANAK_MÅNEDSTEKST",
    "_STARTER_BEGIVENHEDER", "_yaml_dq", "_lav_område_yaml",
    "_lav_almanak_yaml", "_lav_entries_yaml",
]


INIT_YAML = """# Højbedshaven {år}
# Rediger denne fil for at opdatere din plan.

meta:
  år: {år}
  titel: "Højbedshaven"
  html_navn: "hoejbede"

bede:
  - id: bed-1
    navn: "Bed 1"
    bredde_cm: 240
    dybde_cm: 80
    farve: "#d4edda"
    zoner:
      - navn: "Tomater"
        bredde: 0.5
        plante: "Cherrytomater"
        sort: "Sungold"
        farve: "#ff8c69"
      - navn: "Salat"
        bredde: 0.5
        plante: "Salat"
        sort: "Lollo Rossa"
        farve: "#aed581"

planter:
  - navn: "Cherrytomater"
    sort: "Sungold"
    indendørs: 3
    udplantning: 6
    høst_fra: 7
    høst_til: 10
    noter: "Skal ikke fryse. Kræver støtte."
  - navn: "Salat"
    sort: "Lollo Rossa"
    direkte: 4
    høst_fra: 5
    høst_til: 9
    noter: "Sås løbende hver 3. uge."
"""

INIT_ALMANAK = """# Havealmanak {år}
# Kopieret fra almanak-skabelon.yaml — tilpas til din have.

måneder:
  - måned: 1
    navn: "Januar"
    indledning: "Havens hvilemåned. Planlæg sæsonen."
    begivenheder:
      - Bestil frø og løg
    entries: []

  - måned: 2
    navn: "Februar"
    indledning: "Første forspiring indendørs."
    begivenheder:
      - Forspir peberfrugter og chili
    entries: []

  - måned: 3
    navn: "Marts"
    indledning: "Forspiring skyder fart."
    begivenheder:
      - Forspir tomater og squash
      - Direkte såning af spinat og radiser
    entries: []

  - måned: 4
    navn: "April"
    indledning: "Travleste forspiremåned."
    begivenheder:
      - Læg kartofler
      - Direkte såning af gulerødder
    entries: []

  - måned: 5
    navn: "Maj"
    indledning: "Nat-frosten er næsten ovre."
    begivenheder:
      - Hærd forspirede planter af
      - Sæt bønner direkte
    entries: []

  - måned: 6
    navn: "Juni"
    indledning: "Udplantning af de varmekrævende."
    begivenheder:
      - Udplant tomater og basilikum
    entries: []

  - måned: 7
    navn: "Juli"
    indledning: "Høstsæsonen åbner."
    begivenheder:
      - Høst gulerødder og bønner løbende
    entries: []

  - måned: 8
    navn: "August"
    indledning: "Fuld høstsæson."
    begivenheder:
      - Høst tomater kontinuerligt
    entries: []

  - måned: 9
    navn: "September"
    indledning: "Efterårshøst og oprydning."
    begivenheder:
      - Høst og opbevar løg
    entries: []

  - måned: 10
    navn: "Oktober"
    indledning: "Frosten kommer. Grønkål smager bedst nu."
    begivenheder:
      - Høst grønkål efter frost
    entries: []

  - måned: 11
    navn: "November"
    indledning: "Haven lukker ned."
    begivenheder:
      - Afsluttende oprydning
    entries: []

  - måned: 12
    navn: "December"
    indledning: "Hvil og planlægning til næste sæson."
    begivenheder:
      - Gennemgå årets noter
    entries: []
"""

_OM_YAML = """\
titel: "Om siden"
html_navn: "om"

indhold:
  - tekst: >
      Velkommen til {have_titel}. Her dokumenterer jeg sæsonen {år} med bedoversigter,
      sådatokalendere og en løbende almanak.
  - tekst: >
      Siden genereres automatisk fra YAML-filer via have.py.
      Rediger filerne i data/ for at tilpasse den til din have.
"""

_KONTAKT_YAML = """\
titel: "Kontakt"
html_navn: "kontakt"

indhold:
  - tekst: >
      Har du spørgsmål eller kommentarer til haven, er du velkommen til at tage kontakt.

kontakt:
  - label: "E-mail"
    værdi: "din@email.dk"
    link: "mailto:din@email.dk"
"""

_PLANTER_YAML = """\
# Plantedatabase {år}
# Tilføj dine planter her. Hvert element refereres fra bede-filer via id-feltet.
# Kalenderfelter er månedsnumre (1-12). Udelad dem der ikke er relevante.

meta:
  titel: "Planteregister"
  html_navn: "planter"
  undertitel: "Alle sorter med kalender og noter"
  beskrivelse: ""
  ikon: "🌿"
  tags: []

planter:
- id: tomat-eksempel
  navn: Tomater
  sort: Money Maker
  farve: "#e53935"
  placering: Sol
  indendørs: 3
  udplantning: 5
  høst_fra: 7
  høst_til: 10
  noter: Udplantes efter frostrisikoens ophør.
  foto:
    fil: placeholder.jpg
- id: agurk-eksempel
  navn: Agurker
  sort: Marketmore
  farve: "#8bc34a"
  placering: Sol
  indendørs: 4
  udplantning: 5
  høst_fra: 7
  høst_til: 9
  noter: Kræver varme og jævn vanding.
  foto:
    fil: placeholder.jpg
- id: salat-eksempel
  navn: Salat
  sort: Lollo Rossa
  farve: "#4a7c59"
  placering: Sol/halvskygge
  direkte: 4
  høst_fra: 5
  høst_til: 9
  noter: Sås løbende hver 3. uge.
  foto:
    fil: placeholder.jpg
- id: gulerod-eksempel
  navn: Gulerødder
  sort: Nantes
  farve: "#ff6f00"
  placering: Sol
  direkte: 4
  høst_fra: 7
  høst_til: 10
  noter: Tyndes til 5 cm afstand.
  foto:
    fil: placeholder.jpg
- id: basilikum-eksempel
  navn: Basilikum
  sort: Genovese
  farve: "#2d5a27"
  placering: Sol
  indendørs: 4
  udplantning: 5
  høst_fra: 6
  høst_til: 9
  noter: Knibes for at undgå blomstring.
  foto:
    fil: placeholder.jpg
- id: persille-eksempel
  navn: Persille
  sort: Gigante d'Italia
  farve: "#374720"
  placering: Sol/halvskygge
  direkte: 4
  høst_fra: 6
  høst_til: 10
  noter: Langsom spiring — hold fugtig.
  foto:
    fil: placeholder.jpg
- id: jordbær-eksempel
  navn: Jordbær
  sort: Elsanta
  farve: "#e53935"
  placering: Sol
  høst_fra: 6
  høst_til: 8
  noter: Fjern udløbere løbende.
  foto:
    fil: placeholder.jpg
- id: hindbær-eksempel
  navn: Hindbær
  sort: Autumn Bliss
  farve: "#c2185b"
  placering: Sol/halvskygge
  høst_fra: 8
  høst_til: 10
  noter: Skæres ned efter høst.
  foto:
    fil: placeholder.jpg
"""


_META_FELTER_DEFAULT = {
    "titel": "",
    "html_navn": "",
    "ikon": "",
    "ikon_billede": "",
    "undertitel": "",
    "beskrivelse": "",
    "tags": [],
}


_STARTER_BEDE = {
    "hoejbede": """\
bede:
- id: bed-1
  navn: Bed 1
  bredde_cm: 120
  dybde_cm: 80
  farve: '#e8f5e9'
  zoner:
  - navn: Salat
    bredde: 0.5
    plante_id: salat-eksempel
  - navn: Gulerødder
    bredde: 0.5
    plante_id: gulerod-eksempel

kalender_planter: [salat-eksempel, gulerod-eksempel]
""",
    "krydderurter": """\
bede:
- id: palleramme-1
  navn: Palleramme 1
  bredde_cm: 120
  dybde_cm: 80
  farve: '#fef9e7'
  zoner:
  - navn: Basilikum
    bredde: 0.5
    plante_id: basilikum-eksempel
  - navn: Persille
    bredde: 0.5
    plante_id: persille-eksempel

kalender_planter: [basilikum-eksempel, persille-eksempel]
""",
    "frugthaven": """\
bede:
- id: frugtbed-1
  navn: Bærbed
  bredde_cm: 200
  dybde_cm: 60
  farve: '#fce4ec'
  zoner:
  - navn: Jordbær
    bredde: 0.6
    plante_id: jordbær-eksempel
  - navn: Hindbær
    bredde: 0.4
    plante_id: hindbær-eksempel

kalender_planter: [jordbær-eksempel, hindbær-eksempel]
""",
    "drivhus": """\
bede:
- id: drivhus-1
  navn: Drivhus — sektion 1
  bredde_cm: 200
  dybde_cm: 80
  farve: '#e3f2fd'
  zoner:
  - navn: Tomater
    bredde: 0.5
    plante_id: tomat-eksempel
  - navn: Agurker
    bredde: 0.5
    plante_id: agurk-eksempel

kalender_planter: [tomat-eksempel, agurk-eksempel]
""",
}


def _yaml_dq(værdi) -> str:
    """Returnér en sikkert dobbelt-citeret YAML-skalar af en (bruger-)streng.

    Escaper backslash og citationstegn og fjerner linjeskift, så fri brugerinput
    (fx titler med "anførselstegn") ikke ødelægger den genererede YAML.
    """
    s = str(værdi).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\r", "").replace("\n", " ")
    return f'"{s}"'


def _lav_område_yaml(om, år):
    meta = (
        f"# {om['titel']} {år}\n\n"
        f"meta:\n"
        f"  år: {år}\n"
        f"  titel: {_yaml_dq(om['titel'])}\n"
        f"  html_navn: {_yaml_dq(om['html_navn'])}\n"
        f"  ikon: {_yaml_dq(om['ikon'])}\n"
        f"  ikon_billede: \"\"\n"
        f"  undertitel: {_yaml_dq(om['undertitel'])}\n"
        f"  beskrivelse: \"\"\n"
        f"  tags: []\n\n"
    )
    bede = _STARTER_BEDE.get(om["html_navn"], "bede: []\n\nkalender_planter: []\n")
    return meta + bede


_ALMANAK_MÅNEDSTEKST = [
    "Havens hvilemåned. Planlæg sæsonen og bestil frø.",
    "Første forspiring indendørs — tomater og peberfrugter.",
    "Forspiring skyder fart. Tjek udstyret.",
    "Travleste forspiremåned. Direkte såning begynder.",
    "Nat-frosten er næsten ovre. Udplantning nærmer sig.",
    "Udplantning af de varmekrævende afgrøder.",
    "Høstsæsonen åbner. Hold øje med vand.",
    "Fuld høstsæson. Løbende høst og såning af efterårskulturer.",
    "Efterårshøst og oprydning. Sæt løg og hvidløg.",
    "Frosten kommer. Grønkål smager bedst nu.",
    "Afslut sæsonen. Kompostér og dæk bedene.",
    "Ro i haven. Planlæg næste år.",
]


_STARTER_BEGIVENHEDER = {
    "hoejbede":    {4: "Så gulerødder direkte og plant salat ud."},
    "krydderurter":{5: "Sæt basilikum ud — venter til efter frost."},
    "frugthaven":  {6: "Jordbær begynder at modne — høst løbende."},
    "drivhus":     {5: "Udplant tomater og agurker i drivhuset."},
}


def _lav_almanak_yaml(have_titel, områder, år):
    måneder_navne = [
        "Januar", "Februar", "Marts", "April", "Maj", "Juni",
        "Juli", "August", "September", "Oktober", "November", "December",
    ]
    tags_str = ", ".join(_yaml_dq(om["titel"]) for om in områder)

    linjer = [
        f"# Havealmanak {år}",
        "# område_id knytter indledninger og begivenheder til de enkelte haver.",
        "",
        "meta:",
        f"  år: {år}",
        '  titel: "Havealmanak"',
        '  html_navn: "almanak"',
        f'  undertitel: {_yaml_dq(have_titel)}',
        '  beskrivelse: ""',
        '  ikon: "📖"',
        f"  tags: [{tags_str}]",
        "",
        "måneder:",
    ]
    for i, navn in enumerate(måneder_navne, 1):
        tekst = _ALMANAK_MÅNEDSTEKST[i - 1]
        linjer += [
            "",
            f"  - måned: {i}",
            f'    navn: "{navn}"',
            "    indledninger:",
        ]
        for om in områder:
            linjer += [
                f"      - område_id: {om['html_navn']}",
                f'        tekst: "{tekst}"',
            ]
        linjer.append("    begivenheder:")
        for om in områder:
            begivenhed = _STARTER_BEGIVENHEDER.get(om["html_navn"], {}).get(i, "")
            linjer += [
                f"      - område_id: {om['html_navn']}",
                f'        tekst: "{begivenhed}"',
            ]
        linjer.append("    entries: []")

    return "\n".join(linjer) + "\n"


def _lav_entries_yaml(år: int, zone: str) -> str:
    import datetime
    april = datetime.date(år, 4, 20).isoformat()
    maj   = datetime.date(år, 5, 12).isoformat()
    return (
        f"# Haveentries {år}\n"
        "# Brug 'have ny-entry' til at oprette entries interaktivt,\n"
        "# eller skriv dem direkte her. Eksempel:\n"
        "#\n"
        "# entries:\n"
        f"#   - dato: {april}\n"
        f"#     zone: {zone}       # HTML-navn på det bed du skriver om\n"
        "#     plante_id: nantes   # ID på planten (valgfri)\n"
        "#     tekst: |\n"
        "#       De første gulerødder er spiret frem — fine, hårfine blade.\n"
        "#\n"
        "#       Markdown virker: **fed**, *kursiv*, lister osv.\n"
        f"#   - dato: {maj}\n"
        f"#     zone: {zone}\n"
        "#     tekst: Lugede ukrudt og vandede.\n"
        "#     foto:\n"
        f"#       fil: mit-foto.jpg   # Placér billedet i fotos/entries/{år}/\n"
        "#       tekst: Billedtekst\n"
        "\n"
        "entries: []\n"
    )
