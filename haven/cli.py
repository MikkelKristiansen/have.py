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
import os
import argparse
import argcomplete
from pathlib import Path
import subprocess
import datetime
import yaml
from jinja2 import Environment, FileSystemLoader, pass_eval_context
from pydantic import ValidationError

# ── Konfiguration ──────────────────────────────────────────────────────────────

from . import __version__
from .config import (
    load_config, data_mappe, out_mappe, sti,
    sftp_adgangskode, ftp_adgangskode, PROJECT_ROOT,
)
from .models import Plante, FotoModel, Høne
from .wikidata import (wikidata_søg, wikidata_hent_plantedata,
                       wikidata_hent_foto_url, wikidata_hent_foto_metadata)

# Konstanter + mutérbare databaser (PLANTE_DB/DYR_DB) + HONS_TYPER er flyttet til
# haven/kontekst.py (se briefs/cli-opdeling.md, fase 1). `import *` holder denne
# fase inkrementel — funktionskroppe nedenfor er urørt. `_config` er underscore og
# kommer derfor ikke med `*`; den re-importeres eksplicit (bruges mange steder her).
from .kontekst import *  # noqa: F401,F403
from .kontekst import _config  # noqa: F401

# Indlæsning (YAML-load, db-byggere, slug, skriv_hvis_ændret, _les_entries_mappe …)
# og validering (valider_*, check, opdater_schema_*) er flyttet til haven/indlaes.py
# og haven/validering.py (se briefs/cli-opdeling.md, fase 2). `import *` (de eksporterer
# eksplicitte __all__, inkl. de _underscore-helpers cli stadig kalder) holder fasen
# inkrementel — funktionskroppene nedenfor er urørte.
from .indlaes import *      # noqa: F401,F403
from .validering import *   # noqa: F401,F403

# Jinja-miljøet (lav_jinja_env + alle filtre) og kontrast_farve er flyttet til
# haven/skabeloner.py (se briefs/cli-opdeling.md, fase 3). Template-stien resolver
# fortsat til haven/templates/ via Path(__file__).parent i det nye modul.
from .skabeloner import *   # noqa: F401,F403

# Render-laget (fase 4): feeds (iCal/RSS), soeg, hoens, almanak, generering.
# Udskilles ét modul ad gangen; orkestratoren generer_alle bliver i cli.py til fase 6.
from .feeds import *        # noqa: F401,F403
from .soeg import *         # noqa: F401,F403
from .hoens import *        # noqa: F401,F403
from .almanak import *      # noqa: F401,F403
from .generering import *   # noqa: F401,F403

# Sideløbende handlere (fase 5): scaffold (init-skabeloner), deploy (upload/gem-data),
# vejr (Open-Meteo). Wizards i cli.py bruger scaffold + deploy via disse import *.
from .scaffold import *     # noqa: F401,F403
from .deploy import *       # noqa: F401,F403
from .vejr import *         # noqa: F401,F403

# Interaktive wizards + opret-kerner (fase 5). main()-dispatch nedenfor kalder dem.
from .wizards import *      # noqa: F401,F403


# ── Global årsindeks ───────────────────────────────────────────────────────────

def _regenerer_gl_år_sider(gl_år: int, år_liste: list, aktivt_år: int,
                            nav_bede_aktiv: list, have_navn: str, features: dict,
                            env, alle_planter: list, out_rod: Path):
    """Regenerer HTML-sider for et ikke-aktivt år med opdateret år_liste i nav."""
    gl_data = PROJECT_ROOT / "data" / str(gl_år)
    gl_out  = out_rod / str(gl_år)
    if not gl_data.is_dir() or not gl_out.is_dir():
        return

    gl_almanak  = str(gl_data / "almanak.yaml")
    gl_entries  = str(gl_data / "entries.yaml")
    gl_data_sti = str(gl_data)

    gl_yaml_filer = sorted([
        str(gl_data / f) for f in os.listdir(gl_data_sti)
        if f.endswith(".yaml") and not f.startswith(".")
        and f not in ("almanak.yaml", "entries.yaml")
        and os.path.isfile(str(gl_data / f))
    ])

    gl_bede_nav = []
    gl_dyr_nav  = []
    for gl_yaml in gl_yaml_filer:
        _meta = load_yaml(gl_yaml).get("meta", {})
        _hn = _meta.get("html_navn")
        if not _hn:
            continue
        _post = {
            "ikon":      _meta.get("ikon", "🌿"),
            "titel":     _meta.get("titel", _hn),
            "html_navn": _hn,
        }
        (gl_dyr_nav if _meta.get("type") == "husdyr" else gl_bede_nav).append(_post)

    def gl_nav(aktiv_side=""):
        return {"nav_bede": gl_bede_nav, "nav_dyr": gl_dyr_nav, "have_navn": have_navn,
                "aktiv_side": aktiv_side, "features": features,
                "år_liste": år_liste, "aktivt_år": aktivt_år,
                "har_høns": bool(DYR_DB)}

    for gl_yaml in gl_yaml_filer:
        gl_meta = load_yaml(gl_yaml).get("meta", {})
        gl_hn = gl_meta.get("html_navn")
        if not gl_hn:
            continue
        gl_html = str(gl_out / f"{gl_hn}.html")
        generer_html(gl_yaml, gl_html, env, alle_planter,
                     nav_context=gl_nav(gl_hn),
                     almanak_fil=gl_almanak,
                     entries_fil=gl_entries,
                     data_mappe_sti=gl_data_sti)

    generer_samlet_almanak(gl_yaml_filer, str(gl_out / "almanak.html"), env, alle_planter,
                           nav_context=gl_nav("almanak"),
                           almanak_fil=gl_almanak,
                           entries_fil=gl_entries,
                           år=gl_år)

    gl_projekter = [projekt_info(y) for y in gl_yaml_filer
                    if load_yaml(y).get("meta", {}).get("html_navn")]
    if os.path.isfile(gl_almanak):
        gl_projekter.append(projekt_info(gl_almanak))
    gl_planter_info = projekt_info(str(PLANTER_FIL))
    gl_planter_info["html_navn"] = "../planter"
    gl_projekter.append(gl_planter_info)
    generer_index(gl_projekter, str(gl_out / "index.html"), env,
                  nav_context=gl_nav("hjem"), år=gl_år)

    # Synkronisér fotos for det historiske år
    fotos_basis = PROJECT_ROOT / "fotos"
    if fotos_basis.exists():
        gl_fotos_dest = gl_out / "fotos"
        entries_kilde = fotos_basis / "entries" / str(gl_år)
        if entries_kilde.exists():
            _sync_mappe(entries_kilde, gl_fotos_dest / "entries")
        for fil in fotos_basis.iterdir():
            if fil.is_file():
                dst = gl_fotos_dest / fil.name
                if not dst.exists() or fil.stat().st_mtime > dst.stat().st_mtime:
                    import shutil
                    gl_fotos_dest.mkdir(exist_ok=True)
                    shutil.copy2(fil, dst)
                    os.chmod(dst, 0o644)



# ── Entry-oprettelse ───────────────────────────────────────────────────────────

def generer_alle(yaml_filer=None) -> list:
    """Generer alle HTML-sider. Returnerer liste af (sti, navn)-tupler til upload."""
    import shutil
    if yaml_filer is None:
        yaml_filer = _find_yaml_filer()

    data_rod = PROJECT_ROOT / "data"
    if not any(data_rod.glob("**/*.yaml")):
        print("❌ Ingen have fundet — kør: have init")
        sys.exit(1)
    if not os.path.isdir(DATA_MAPPE):
        print(f"❌ data/{AKTIVT_ÅR}/ eksisterer ikke — kør: have nyt-år {AKTIVT_ÅR}")
        sys.exit(1)
    if not os.path.isfile(PLANTER_FIL):
        print(f"❌ {PLANTER_FIL} mangler — kør: have init")
        sys.exit(1)

    os.makedirs(OUT_MAPPE, exist_ok=True)
    env          = lav_jinja_env()
    upload_filer = []
    projekter    = []
    advarsler    = []

    planter_data = load_yaml(PLANTER_FIL)
    if isinstance(planter_data, list):
        alle_planter = planter_data
    else:
        alle_planter = planter_data.get("planter", [])
    PLANTE_DB.update(byg_plante_db(PLANTER_FIL))
    print(f"✅ Plantedatabase indlæst: {len(alle_planter)} planter")
    DYR_DB.clear()
    DYR_DB.update(byg_dyr_db())
    if DYR_DB:
        print(f"✅ Dyreregister indlæst: {len(DYR_DB)} dyr")
    valider_planter(PLANTE_DB)
    valider_referencer(PLANTE_DB, yaml_filer)

    # ── Navigation-kontekst ────────────────────────────────────────────────────
    have_navn = _config.get("navn", "")
    if not have_navn and os.path.isfile(ALMANAK_FIL):
        alm_meta = load_yaml(ALMANAK_FIL).get("meta", {})
        have_navn = alm_meta.get("undertitel", "")
    have_navn = have_navn or "Haven"

    nav_bede = []   # plantezoner → "Sektioner"
    nav_dyr  = []   # husdyr-zoner → "Dyr"
    for _ys in yaml_filer:
        if not os.path.isfile(_ys):
            continue
        _meta = load_yaml(_ys).get("meta", {})
        _hn   = _meta.get("html_navn")
        if not _hn:
            continue
        _post = {
            "ikon":     _meta.get("ikon", "🌿"),
            "titel":    _meta.get("titel", _hn),
            "html_navn": _hn,
        }
        (nav_dyr if _meta.get("type") == "husdyr" else nav_bede).append(_post)

    _data_basis = str(PROJECT_ROOT / "data")
    år_liste = sorted([
        int(d) for d in os.listdir(_data_basis)
        if d.isdigit() and os.path.isdir(os.path.join(_data_basis, d))
    ]) if os.path.isdir(_data_basis) else [AKTIVT_ÅR]

    def nav_ctx(aktiv_side="", op_sti="../", jaar_sti=""):
        return {"nav_bede": nav_bede, "nav_dyr": nav_dyr, "have_navn": have_navn,
                "aktiv_side": aktiv_side,
                "features": _config.get("features", {}), "år_liste": år_liste,
                "aktivt_år": AKTIVT_ÅR, "op_sti": op_sti, "jaar_sti": jaar_sti,
                "har_høns": bool(DYR_DB)}
    # ─────────────────────────────────────────────────────────────────────────

    for yaml_sti in yaml_filer:
        if not os.path.isfile(yaml_sti):
            print(f"❌ {yaml_sti} mangler — springer over "
                  f"(ret bede-listen i haven.yaml eller kør: have ny-bed)",
                  file=sys.stderr)
            continue
        data      = load_yaml(yaml_sti)
        meta      = data.get("meta", {})
        html_navn = meta.get("html_navn")
        if not html_navn:
            print(f"❌ {yaml_sti}: meta.html_navn mangler — "
                  f"siden springes over; tilføj fx 'html_navn: hoejbede'",
                  file=sys.stderr)
            continue
        meta_år = meta.get("år")
        if meta_år and meta_år != AKTIVT_ÅR:
            advarsler.append(
                f"⚠️  {yaml_sti}: meta.år={meta_år} men AKTIVT_ÅR={AKTIVT_ÅR} — "
                f"opdatér meta.år eller kør: have check"
            )
        html_sti = os.path.join(OUT_MAPPE, html_navn + ".html")
        # zone-typer: 'husdyr' aktiverer alternativ template og wizard-sæt.
        # Zoner uden 'type' behandles som plantezoner (eksisterende opførsel).
        if meta.get("type") == "husdyr":
            hons_entries = generer_hons_html(yaml_sti, html_sti, env, nav_context=nav_ctx(html_navn))
            upload_filer.append((html_sti, html_navn + ".html"))
            projekter.append(projekt_info(yaml_sti))
            ics_sti = os.path.join(OUT_MAPPE, f"{html_navn}-{AKTIVT_ÅR}.ics")
            if generer_hons_ics(hons_entries, ics_sti, AKTIVT_ÅR):
                upload_filer.append((ics_sti, f"{html_navn}-{AKTIVT_ÅR}.ics"))
            continue
        generer_html(yaml_sti, html_sti, env, alle_planter, nav_context=nav_ctx(html_navn))
        upload_filer.append((html_sti, html_navn + ".html"))
        projekter.append(projekt_info(yaml_sti))

    index_sti  = os.path.join(OUT_MAPPE, "index.html")
    samlet_sti = os.path.join(OUT_MAPPE, "almanak.html")
    generer_samlet_almanak(yaml_filer, samlet_sti, env, alle_planter, nav_context=nav_ctx("almanak"))
    upload_filer.append((samlet_sti, "almanak.html"))
    projekter.append(projekt_info(ALMANAK_FIL))

    planter_sti = os.path.join(str(OUT_MAPPE.parent), "planter.html")
    generer_planter_oversigt(alle_planter, yaml_filer, planter_sti, env, nav_context=nav_ctx("planter", op_sti="", jaar_sti=f"{AKTIVT_ÅR}/"))
    upload_filer.append((planter_sti, "planter.html"))

    # Hønseregister — delt på tværs af år (samme rod-niveau som planter.html)
    if DYR_DB:
        valider_hoenser(DYR_DB)
        hoense_sti = os.path.join(str(OUT_MAPPE.parent), "hoenseregisteret.html")
        generer_hoenseregisteret_oversigt(list(DYR_DB.values()), hoense_sti, env,
                                          nav_context=nav_ctx("hoenseregisteret", op_sti="", jaar_sti=f"{AKTIVT_ÅR}/"))
        upload_filer.append((hoense_sti, "hoenseregisteret.html"))
        # Ryd forældede årskopier (registret bor i roden, ikke pr. år)
        for _gl_år in år_liste:
            _stale = OUT_MAPPE.parent / str(_gl_år) / "hoenseregisteret.html"
            if _stale.exists():
                _stale.unlink()
                print(f"🗑  Fjernet forældet: {_stale}")

    arkiv_samlet_sti = OUT_MAPPE.parent / "arkiv-samlet.html"
    generer_samlet_arkiv(år_liste, arkiv_samlet_sti, env, plante_db=PLANTE_DB,
                         nav_context=nav_ctx("arkiv-samlet", op_sti="", jaar_sti=f"{AKTIVT_ÅR}/"))
    upload_filer.append((str(arkiv_samlet_sti), "arkiv-samlet.html"))

    for _gl_år in år_liste:
        _stale = OUT_MAPPE.parent / str(_gl_år) / "planter.html"
        if _stale.exists():
            _stale.unlink()
            print(f"🗑  Fjernet forældet: {_stale}")
    planter_info = projekt_info(PLANTER_FIL)
    planter_info["undertitel"] = f"{len(alle_planter)} sorter med kalender og noter"
    planter_info["html_navn"] = "../planter"
    projekter.append(planter_info)

    generer_index(projekter, index_sti, env, nav_context=nav_ctx("hjem"),
                  hero_billede=_config.get("hero_billede", ""))
    upload_filer.append((index_sti, "index.html"))

    for info_yaml, info_html in [("data/om.yaml", "om.html"), ("data/kontakt.yaml", "kontakt.html")]:
        if os.path.exists(info_yaml):
            info_sti = os.path.join(str(OUT_MAPPE.parent), info_html)
            generer_info_side(info_yaml, info_sti, env, nav_context=nav_ctx("", op_sti="", jaar_sti=f"{AKTIVT_ÅR}/"))
            upload_filer.append((info_sti, info_html))
        for _gl_år in år_liste:
            _stale = OUT_MAPPE.parent / str(_gl_år) / info_html
            if _stale.exists():
                _stale.unlink()
                print(f"🗑  Fjernet forældet: {_stale}")

    søg_json_sti, søg_data = generer_søg_json(OUT_MAPPE.parent, PROJECT_ROOT / "data", PLANTE_DB)
    upload_filer.append((str(søg_json_sti), "søg.json"))
    opdater_schema_plante_ids(PLANTE_DB)

    import json as _json
    søg_html_sti = OUT_MAPPE.parent / "søg.html"
    skabelon_søg = env.get_template("søg.html")
    søg_html = skabelon_søg.render(
        år=AKTIVT_ÅR,
        søg_data_json=_json.dumps(søg_data, ensure_ascii=False, separators=(",", ":")),
        **nav_ctx("søg", op_sti="", jaar_sti=f"{AKTIVT_ÅR}/"),
    )
    if skriv_hvis_ændret(søg_html_sti, søg_html):
        print(f"✅ Søgeside genereret: {søg_html_sti}")
    else:
        print(f"ℹ️  Søgeside uændret: {søg_html_sti}")
    upload_filer.append((str(søg_html_sti), "søg.html"))

    _lokal_css = Path.cwd() / "static" / "style.css"
    css_kilde = str(_lokal_css if _lokal_css.exists() else Path(__file__).parent / "static" / "style.css")
    if os.path.exists(css_kilde):
        css_tekst = Path(css_kilde).read_text(encoding="utf-8")
        # Kopiér til årsmappe
        css_dest = os.path.join(OUT_MAPPE, "style.css")
        if skriv_hvis_ændret(css_dest, css_tekst):
            os.chmod(css_dest, 0o644)
            print(f"✅ CSS kopieret: {css_dest}")
        else:
            print(f"ℹ️  CSS uændret: {css_dest}")
        upload_filer.append((css_dest, "style.css"))
        # Kopiér til rodmappe (bruges af søg.html, planter.html, om.html m.fl.)
        css_rod = str(OUT_MAPPE.parent / "style.css")
        skriv_hvis_ændret(css_rod, css_tekst)
        os.chmod(css_rod, 0o644)

    _lokal_js = Path.cwd() / "static" / "almanak-filter.js"
    js_kilde = str(_lokal_js if _lokal_js.exists() else Path(__file__).parent / "static" / "almanak-filter.js")
    if os.path.exists(js_kilde):
        js_tekst = Path(js_kilde).read_text(encoding="utf-8")
        # Kopiér kun til årsmappe — almanak-filter.js bruges kun af almanak.html
        js_dest = os.path.join(OUT_MAPPE, "almanak-filter.js")
        if skriv_hvis_ændret(js_dest, js_tekst):
            os.chmod(js_dest, 0o644)
            print(f"✅ JS kopieret: {js_dest}")
        else:
            print(f"ℹ️  JS uændret: {js_dest}")
        upload_filer.append((js_dest, "almanak-filter.js"))

    fotos_basis = PROJECT_ROOT / "fotos"
    if fotos_basis.exists():
        # Plantefotos er tidløse — kopieres til out/fotos/planter/ (rod-niveau)
        planter_kilde = fotos_basis / "planter"
        if planter_kilde.exists():
            planter_dest = OUT_MAPPE.parent / "fotos" / "planter"
            _generer_manglende_thumbnails(planter_kilde)
            n = _sync_mappe(planter_kilde, planter_dest)
            _generer_manglende_thumbnails(planter_dest)
            if n > 0:
                print(f"✅ Plantefotos synkroniseret: {n} filer → {planter_dest}")
            else:
                print(f"ℹ️  Plantefotos uændrede: {planter_dest}")
            # Ryd stale planter-mapper i årsundermapper
            for _gl_år in år_liste:
                _stale_planter = OUT_MAPPE.parent / str(_gl_år) / "fotos" / "planter"
                if _stale_planter.exists():
                    shutil.rmtree(_stale_planter)
                    print(f"🗑  Fjernet forældet: {_stale_planter}")

        # Hønsefotos er tidløse — kopieres til out/fotos/dyr/ (rod-niveau)
        dyr_kilde = fotos_basis / "dyr"
        if dyr_kilde.exists():
            dyr_dest = OUT_MAPPE.parent / "fotos" / "dyr"
            _generer_manglende_thumbnails(dyr_kilde)
            n = _sync_mappe(dyr_kilde, dyr_dest)
            _generer_manglende_thumbnails(dyr_dest)
            if n > 0:
                print(f"✅ Hønsefotos synkroniseret: {n} filer → {dyr_dest}")
            else:
                print(f"ℹ️  Hønsefotos uændrede: {dyr_dest}")
            for _gl_år in år_liste:
                _stale_dyr = OUT_MAPPE.parent / str(_gl_år) / "fotos" / "dyr"
                if _stale_dyr.exists():
                    shutil.rmtree(_stale_dyr)
                    print(f"🗑  Fjernet forældet: {_stale_dyr}")

        # Entryfotos er årstalsbestemte — kopieres til out/{år}/fotos/entries/
        fotos_dest = OUT_MAPPE / "fotos"
        fotos_dest.mkdir(exist_ok=True)
        entries_kilde = fotos_basis / "entries" / str(AKTIVT_ÅR)
        entries_dest  = fotos_dest / "entries"
        if entries_kilde.exists():
            if entries_dest.exists():
                shutil.rmtree(entries_dest)
            shutil.copytree(entries_kilde, entries_dest)
        else:
            entries_dest.mkdir(exist_ok=True)
        for fil in fotos_basis.iterdir():
            if fil.is_file():
                dst = fotos_dest / fil.name
                shutil.copy2(fil, dst)
                os.chmod(dst, 0o644)
        for rod, _, filer_i_rod in os.walk(fotos_dest):
            for fil in filer_i_rod:
                os.chmod(os.path.join(rod, fil), 0o644)
        print(f"✅ Årsfotos kopieret: {fotos_dest}")

    generer_redirect_index(str(OUT_MAPPE.parent), AKTIVT_ÅR)

    for _gl_år in år_liste:
        if _gl_år != AKTIVT_ÅR:
            _regenerer_gl_år_sider(
                _gl_år, år_liste, AKTIVT_ÅR,
                nav_bede, have_navn, _config.get("features", {}),
                env, alle_planter, OUT_MAPPE.parent,
            )

    if os.path.exists(ALMANAK_FIL):
        ics_sti = os.path.join(OUT_MAPPE, f"have-{AKTIVT_ÅR}.ics")
        if (not os.path.exists(ics_sti) or
                os.path.getmtime(ALMANAK_FIL) > os.path.getmtime(ics_sti)):
            generer_ics(ALMANAK_FIL, ics_sti, AKTIVT_ÅR, yaml_filer)
        else:
            print(f"ℹ️  ICS uændret (almanak.yaml ikke nyere): {ics_sti}")
        upload_filer.append((ics_sti, f"have-{AKTIVT_ÅR}.ics"))

    dagbog_rss_sti  = os.path.join(OUT_MAPPE, "have-dagbog.rss")
    almanak_rss_sti = os.path.join(OUT_MAPPE, "have-almanak.rss")
    if os.path.exists(ENTRIES_FIL):
        if (not os.path.exists(dagbog_rss_sti) or
                os.path.getmtime(ENTRIES_FIL) > os.path.getmtime(dagbog_rss_sti)):
            generer_rss_dagbog(ENTRIES_FIL, dagbog_rss_sti, AKTIVT_ÅR, BASE_URL)
        else:
            print(f"ℹ️  RSS dagbog uændret: {dagbog_rss_sti}")
        upload_filer.append((dagbog_rss_sti, "have-dagbog.rss"))
    if os.path.exists(ALMANAK_FIL):
        if (not os.path.exists(almanak_rss_sti) or
                os.path.getmtime(ALMANAK_FIL) > os.path.getmtime(almanak_rss_sti)):
            generer_rss_almanak(ALMANAK_FIL, almanak_rss_sti, AKTIVT_ÅR, BASE_URL, yaml_filer)
        else:
            print(f"ℹ️  RSS almanak uændret: {almanak_rss_sti}")
        upload_filer.append((almanak_rss_sti, "have-almanak.rss"))

    if advarsler:
        print(f"\n{'─'*40}")
        for a in advarsler:
            print(a)
        print(f"{'─'*40}")
        print(f"Kør 'have check' for fuld diagnose.\n")

    return upload_filer


def kør_alt() -> None:
    """Kør hele den daglige arbejdsgang i rækkefølge: hent nye indlæg fra inboxen,
    gem havedata-repoet, og byg + deploy sitet. Et fejlende trin stopper ikke de
    øvrige (afslutter dog med fejlkode hvis noget gik galt)."""
    trin = [
        ("📥  Henter dagbogsindlæg fra inboxen", ["have", "hent-inbox", "--skriv"]),
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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Eksempler:\n  have build\n  have deploy\n  have init\n  have check"
    )
    parser.add_argument("--version", action="version",
                        version=f"have {__version__}")
    subparsers = parser.add_subparsers(dest="kommando")

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

    # Subkommando: hent-fotos
    subparsers.add_parser("hent-fotos", help="Hent plantefotos fra Wikimedia")

    # Subkommando: hent-havefotos
    subparsers.add_parser("hent-havefotos", help="Tjek og synkronisér almanakfotos i entries")

    # Subkommando: hent-inbox (delegeres til haven.inbox; her kun for --help-synlighed)
    _p_inbox = subparsers.add_parser("hent-inbox", help="Hent dagbogsindlæg fra have-inbox-webappen (SFTP) og behandl dem")
    _p_inbox.add_argument("--skriv", action="store_true",
                          help="Importér til data/, byg site og ryd serverens inbox (uden flaget: dry-run)")

    # Subkommando: nyt-bed
    subparsers.add_parser("nyt-bed", help="Tilføj nyt bed til en zone-YAML-fil (interaktiv wizard)")

    # Subkommando: ny-entry
    subparsers.add_parser("ny-entry", help="Opret ny dagbogsentry (interaktiv wizard)")

    # Subkommando: plant-en-plante
    subparsers.add_parser("plant-en-plante", help="Plant en plante i et eksisterende bed (interaktiv wizard)")

    subparsers.add_parser("riv-en-plante-op", help="Fjern en zone/plante fra et eksisterende bed (interaktiv wizard)")

    subparsers.add_parser("ret-en-plante", help="Ret en eksisterende zone/plante i et bed (interaktiv wizard)")

    subparsers.add_parser("ret-bed", help="Omfordel zone-bredder og tilføj nye zoner med ratio (interaktiv wizard)")

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
    subparsers.add_parser("alt", help="Kør hele arbejdsgangen: hent-inbox → gem-data → deploy")

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

    # Standard: generer
    parser.add_argument("yaml", nargs="*", default=None)
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

    if args.kommando == "nyt-bed":
        nyt_bed()
        sys.exit(0)

    if args.kommando == "ny-entry":
        ny_entry()
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
        kør_alt()
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
