#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
haven — Generer HTML-plan for køkkenhaven via Jinja2-skabeloner.
Læser YAML-filer og producerer HTML til webbrug og print via browser.

Brug:
  have build                         # generer HTML lokalt
  have deploy                        # byg og upload til server
"""

import sys
import argparse
import argcomplete
import subprocess
import datetime

# ── Imports ──────────────────────────────────────────────────────────────────────
#
# cli.py er kun entry point: argparse-opsætning + main()-dispatch (+ kør_alt). Al
# logik bor i de udskilte moduler (se briefs/cli-opdeling.md). Importerne herunder
# er bevidst eksplicitte og afspejler præcis hvad dispatchen kalder.

from . import __version__
from .kontekst import (
    PLANTE_DB, PLANTER_FIL, DEPLOY_PROTOKOLLER, normaliser_protokoller,
)
from .indlaes import byg_plante_db, _find_yaml_filer
from .validering import check, opdater_schema_plante_ids, opdater_schema_planter
from .byg import generer_alle
from .deploy import upload, upload_ftp, gem_data
from .vejr import hent_vejr
from .wizards import (
    init_projekt, nyt_område, nyt_år, ny_entry, ret_entry, ny_plante, ret_i_plante_yaml,
    ret_foto, nyt_bed, plant_en_plante, riv_en_plante_op, ret_en_plante, ret_bed,
    hons_ny_høne, hons_ny_obs, wizard_ny_frø,
)


def kør_alt(lokal: bool = False) -> None:
    """Kør hele den daglige arbejdsgang i rækkefølge: hent nye indlæg fra inboxen,
    gem havedata-repoet, og byg + deploy sitet. Et fejlende trin stopper ikke de
    øvrige (afslutter dog med fejlkode hvis noget gik galt).

    lokal=True læser inboxen direkte fra disk (--lokal) — bruges når have kører på
    samme maskine som have-inbox (fx headless auto-import på RPi5)."""
    hent_inbox = ["have", "hent-inbox", "--skriv"] + (["--lokal"] if lokal else [])
    trin = [
        ("📥  Henter dagbogsindlæg fra inboxen", hent_inbox),
        ("💾  Gemmer havedata (commit + push)",   ["have", "gem-data"]),
        ("🚀  Bygger og deployer",                ["have", "deploy"]),
    ]
    fejlede = []
    for navn, kmd in trin:
        print(f"\n{'═' * 52}\n  {navn}\n{'═' * 52}")
        if subprocess.run(kmd).returncode != 0:
            fejlede.append(navn.strip())
            print("⚠️  Trinnet meldte en fejl — fortsætter med resten.")
    print()
    if fejlede:
        print(f"⚠️  'have alt' færdig, men disse trin havde problemer: {', '.join(fejlede)}")
        sys.exit(1)
    print("✅  'have alt' færdig — hentet, gemt og deployet. 🌿")


class GrupperetHelp(argparse.RawDescriptionHelpFormatter):
    """Skjuler argparses auto-genererede subkommando-dump i top-niveau-hjælpen.

    Den flade liste erstattes af den grupperede oversigt i `epilog` (KOMMANDO_OVERSIGT),
    så `have --help` bliver til at overskue. Per-kommando-hjælp (`have <kmd> --help`)
    bruger argparses standard og er upåvirket.
    """
    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction):
            return ""
        return super()._format_action(action)


# Håndkurateret, grupperet kommandooversigt vist i `have --help`. Rækkefølge og
# gruppering afspejler arbejdsgangen, ikke tilføjelsesrækkefølgen i koden. Interne
# vedligeholdskommandoer (fx opdater-schema) udelades bevidst — de virker stadig.
KOMMANDO_OVERSIGT = """\
Kommandoer:

  Projekt & sæson
    init                Sæt aktuelle mappe op som haveprojekt
    område              Opret nyt havområde i aktuelle projekt
    nyt-år              Klargør ny sæson (fx: have nyt-år 2027)

  Plantekatalog
    ny-plante           Opret ny plante i planter.yaml
    ret-i-plante-yaml   Ret en eksisterende plante i planter.yaml
    ret-foto            Ret foto for en plante (planter.yaml) eller høne (dyr.yaml)
    ny-frø              Tilføj ny frøpost til frø.yaml

  Bede & placering
    nyt-bed             Tilføj nyt bed til en zone-YAML-fil
    plant-en-plante     Plant en plante i et eksisterende bed
    ret-en-plante       Ret en zone/plante i et bed
    riv-en-plante-op    Fjern en zone/plante fra et bed
    ret-bed             Omfordel zone-bredder og tilføj nye zoner

  Dagbog & data
    ny-entry            Opret ny dagbogsentry
    ret-entry           Ret en eksisterende dagbogs- eller hønse-entry
    hent-inbox          Hent dagbogsindlæg fra have-inbox-webappen
    hent-havefotos      Tjek og synkronisér almanakfotos i entries
    hent-fotos          Hent plantefotos fra Wikimedia
    hent-vejr           Hent historisk vejrdata fra Open-Meteo

  Høns
    hons                Hønsemodul — observationer og dyreregister (se: have hons --help)

  Byg & udgiv
    build               Generer alle HTML-sider (alias for: have uden argumenter)
    watch               Filwatcher der genbygger ved ændringer (livereload)
    check               Validér planter.yaml og krydsreferencér mod bede
    deploy              Generer alle sider og upload til server
    gem-data            Commit + push af havedata-repoet (data/)
    alt                 Kør hele arbejdsgangen: hent-inbox → gem-data → deploy

Kør 'have <kommando> --help' for detaljer om en enkelt kommando.

Eksempler:
  have build
  have deploy
  have check
  have nyt-år 2027
"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # hent-fotos delegerer til haven.fotos inkl. alle dens flags
    if len(sys.argv) >= 2 and sys.argv[1] == "hent-fotos":
        subprocess.run([sys.executable, "-m", "haven.fotos"] + sys.argv[2:])
        sys.exit(0)

    # hent-havefotos delegerer til haven.havefotos inkl. alle dens flags
    if len(sys.argv) >= 2 and sys.argv[1] == "hent-havefotos":
        subprocess.run([sys.executable, "-m", "haven.havefotos"] + sys.argv[2:])
        sys.exit(0)

    # hent-inbox delegerer til haven.inbox inkl. alle dens flags
    if len(sys.argv) >= 2 and sys.argv[1] == "hent-inbox":
        subprocess.run([sys.executable, "-m", "haven.inbox"] + sys.argv[2:])
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="have — generer HTML + indeks for hele haven.",
        formatter_class=GrupperetHelp,
        epilog=KOMMANDO_OVERSIGT,
    )
    parser.add_argument("--version", action="version",
                        version=f"have {__version__}")
    subparsers = parser.add_subparsers(dest="kommando", metavar="<kommando>")

    # Subkommando: init
    init_parser = subparsers.add_parser("init", help="Sæt aktuelle mappe op som haveprojekt")
    init_parser.add_argument("--ja", "-j", action="store_true",
                             help="Acceptér alle defaults uden at spørge (til CI og test)")

    # Subkommando: område
    subparsers.add_parser("område", help="Opret nyt havområde i aktuelle projekt")

    # Subkommando: check
    subparsers.add_parser("opdater-schema", help="Opdater plante_id-enum i bed.schema.json fra planter.yaml")
    check_parser = subparsers.add_parser("check", help="Validér planter.yaml og krydsreferencér mod bede")
    check_parser.add_argument("--strict", action="store_true",
                              help="Behandl advarsler som fejl (nyttigt inden upload)")
    check_parser.add_argument("--farver", action="store_true",
                              help="Vis farvetabel for alle planter")

    # Subkommando: nyt-år
    nyt_år_parser = subparsers.add_parser("nyt-år", help="Klargør ny sæson (fx: have nyt-år 2027)")
    nyt_år_parser.add_argument("år", type=int, help="Det nye år (fx 2027)")

    # Subkommando: ny-plante
    subparsers.add_parser("ny-plante", help="Opret ny plante i planter.yaml (interaktiv wizard)")

    subparsers.add_parser("ret-i-plante-yaml", help="Ret en eksisterende plante i planter.yaml (interaktiv wizard)")

    subparsers.add_parser("ret-foto", help="Ret foto for en plante (planter.yaml) eller høne (dyr.yaml) (interaktiv wizard)")

    # Subkommando: hent-fotos
    subparsers.add_parser("hent-fotos", help="Hent plantefotos fra Wikimedia")

    # Subkommando: hent-havefotos
    subparsers.add_parser("hent-havefotos", help="Tjek og synkronisér almanakfotos i entries")

    # Subkommando: hent-inbox (delegeres til haven.inbox; her kun for --help-synlighed)
    _p_inbox = subparsers.add_parser("hent-inbox", help="Hent dagbogsindlæg fra have-inbox-webappen (SFTP) og behandl dem")
    _p_inbox.add_argument("--skriv", action="store_true",
                          help="Importér til data/, byg site og ryd serverens inbox (uden flaget: dry-run)")
    _p_inbox.add_argument("--lokal", action="store_true",
                          help="Læs inboxen lokalt fra disk i stedet for via SFTP (samme maskine som have-inbox)")

    # Subkommando: nyt-bed
    subparsers.add_parser("nyt-bed", help="Tilføj nyt bed til en zone-YAML-fil (interaktiv wizard)")

    # Subkommando: ny-entry
    subparsers.add_parser("ny-entry", help="Opret ny dagbogsentry (interaktiv wizard)")

    # Subkommando: ret-entry
    subparsers.add_parser("ret-entry", help="Ret en eksisterende dagbogs- eller hønse-entry (interaktiv wizard)")

    # Subkommando: plant-en-plante
    subparsers.add_parser("plant-en-plante", help="Plant en plante i et eksisterende bed (interaktiv wizard)")

    subparsers.add_parser("riv-en-plante-op", help="Fjern en zone/plante fra et eksisterende bed (interaktiv wizard)")

    subparsers.add_parser("ret-en-plante", help="Ret en eksisterende zone/plante i et bed (interaktiv wizard)")

    subparsers.add_parser("ret-bed", help="Omfordel zone-bredder og tilføj nye zoner med ratio (interaktiv wizard)")

    # Subkommando: ny-frø
    subparsers.add_parser("ny-frø", help="Tilføj ny frøpost til data/frø.yaml (interaktiv wizard)")

    # Subkommando: hons — hønsemodul med underkommandoer
    hons_parser = subparsers.add_parser("hons", help="Hønsemodul — observationer og dyreregister")
    hons_sub = hons_parser.add_subparsers(dest="hons_kommando")
    hons_sub.add_parser("ny-obs", help="Registrér en hønse-observation (interaktiv wizard)")
    hons_sub.add_parser("ny-høne", help="Tilføj ny høne til dyr.yaml (interaktiv wizard)")

    # Subkommando: build (alias for default)
    subparsers.add_parser("build", help="Generer alle HTML-sider (alias for: have uden argumenter)")

    # Subkommando: deploy
    _p_deploy = subparsers.add_parser("deploy", help="Generer alle sider og upload til server (protokol sat i haven.yaml)")
    _p_deploy.add_argument(
        "--protokol", nargs="+", choices=["ftp", "sftp", "ingen"], metavar="PROTOKOL",
        help="Overstyr deploy.protokol for denne kørsel — ét eller flere mål, fx: "
             "--protokol ftp sftp (uploader i nævnt rækkefølge)",
    )

    # Subkommando: alt — kør hele arbejdsgangen
    _p_alt = subparsers.add_parser("alt", help="Kør hele arbejdsgangen: hent-inbox → gem-data → deploy")
    _p_alt.add_argument("--lokal", action="store_true",
                        help="Læs inboxen lokalt fra disk i stedet for via SFTP "
                             "(når have kører på samme maskine som have-inbox, fx RPi5)")

    # Subkommando: gem-data
    _p_gem = subparsers.add_parser("gem-data", help="Commit + push af havedata-repoet (data/)")
    _p_gem.add_argument("besked", nargs="?", metavar="BESKED",
                        help="Valgfri commit-besked (standard: 'opdater havedata <dato>')")

    # Subkommando: hent-vejr
    hent_vejr_parser = subparsers.add_parser("hent-vejr", help="Hent historisk vejrdata fra Open-Meteo og skriv til almanak.yaml")
    hent_vejr_parser.add_argument("--år", type=int, default=datetime.date.today().year,
                                  help="Årstal der hentes for (standard: indeværende år)")
    hent_vejr_parser.add_argument("--force", action="store_true",
                                  help="Overskriv eksisterende måneder og inkludér indeværende måned")

    # Subkommando: watch
    watch_parser = subparsers.add_parser("watch", help="Filwatcher der genbygger ved ændringer (livereload)")
    watch_parser.add_argument("--port", type=int, default=5500, help="Port til livereload-server (standard: 5500)")

    # Standard: generer (skjult fra --help; oversigten ligger i KOMMANDO_OVERSIGT)
    parser.add_argument("yaml", nargs="*", default=None, help=argparse.SUPPRESS)
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    yaml_filer = args.yaml if args.yaml else _find_yaml_filer()

    if args.kommando == "init":
        init_projekt(ja=args.ja)
        sys.exit(0)

    if args.kommando == "område":
        nyt_område()
        sys.exit(0)

    if args.kommando == "opdater-schema":
        PLANTE_DB.update(byg_plante_db(PLANTER_FIL))
        opdater_schema_plante_ids(PLANTE_DB)
        opdater_schema_planter()
        sys.exit(0)

    if args.kommando == "check":
        check(yaml_filer, strict=getattr(args, "strict", False),
              farver=getattr(args, "farver", False))
        sys.exit(0)

    if args.kommando == "nyt-år":
        nyt_år(args.år)
        sys.exit(0)

    if args.kommando == "ny-plante":
        ny_plante()
        sys.exit(0)

    if args.kommando == "ret-i-plante-yaml":
        ret_i_plante_yaml()
        sys.exit(0)

    if args.kommando == "ret-foto":
        ret_foto()
        sys.exit(0)

    if args.kommando == "ny-frø":
        wizard_ny_frø()
        sys.exit(0)

    if args.kommando == "nyt-bed":
        nyt_bed()
        sys.exit(0)

    if args.kommando == "ny-entry":
        ny_entry()
        sys.exit(0)

    if args.kommando == "ret-entry":
        ret_entry()
        sys.exit(0)

    if args.kommando == "plant-en-plante":
        plant_en_plante()
        sys.exit(0)

    if args.kommando == "riv-en-plante-op":
        riv_en_plante_op()
        sys.exit(0)

    if args.kommando == "ret-en-plante":
        ret_en_plante()
        sys.exit(0)

    if args.kommando == "ret-bed":
        ret_bed()
        sys.exit(0)

    if args.kommando == "hons":
        hk = getattr(args, "hons_kommando", None)
        if hk == "ny-obs":
            hons_ny_obs()
        elif hk == "ny-høne":
            hons_ny_høne()
        else:
            hons_parser.print_help()
        sys.exit(0)

    if args.kommando == "alt":
        kør_alt(lokal=args.lokal)
        sys.exit(0)

    if args.kommando == "gem-data":
        gem_data(args.besked)
        sys.exit(0)

    if args.kommando == "hent-vejr":
        hent_vejr(args.år, force=args.force)
        sys.exit(0)

    if args.kommando == "deploy":
        # --protokol overstyrer haven.yaml for denne kørsel; ellers bruges konfig.
        protokoller = (normaliser_protokoller(args.protokol)
                       if args.protokol else DEPLOY_PROTOKOLLER)
        if not protokoller:
            print("ℹ️  Upload sprunget over — sæt deploy.protokol til fx 'sftp', 'ftp' "
                  "eller [ftp, sftp] i haven.yaml (eller brug --protokol)")
            sys.exit(0)

        upload_filer = generer_alle(_find_yaml_filer())  # byg én gang, upload til alle mål
        upload_funktioner = {"ftp": upload_ftp, "sftp": upload}
        fejlede = []
        for i, p in enumerate(protokoller):
            if len(protokoller) > 1:
                print(f"\n── Deploy {i+1}/{len(protokoller)}: {p} ──────────────────────────")
            try:
                upload_funktioner[p](upload_filer)
            except SystemExit as e:
                # Upload-funktionerne afslutter med sys.exit(1) ved fejl; fang det så
                # et nedbrud på ét mål ikke afbryder de øvrige.
                if e.code not in (0, None):
                    fejlede.append(p)
                    rest = " — fortsætter med resten" if i < len(protokoller) - 1 else ""
                    print(f"⚠️  Deploy til {p} fejlede{rest}.", file=sys.stderr)
        if fejlede:
            print(f"\n❌ Deploy fejlede for: {', '.join(fejlede)}")
            sys.exit(1)
        if len(protokoller) > 1:
            print(f"\n✅ Deploy færdig til alle mål: {', '.join(protokoller)}")
        sys.exit(0)

    if args.kommando == "watch":
        from livereload import Server
        import subprocess as _sp

        def _byg():
            _sp.run(["have", "build"])

        _server = Server()
        _server.watch("data/**/*.yaml", _byg)
        _server.watch("data/*.yaml", _byg)
        _server.watch("out/**/*.html")
        _server.serve(root="out/", port=args.port, open_url_delay=1)
        sys.exit(0)

    upload_filer = generer_alle(yaml_filer)



if __name__ == "__main__":
    main()
