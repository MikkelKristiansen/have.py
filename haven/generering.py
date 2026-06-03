"""haven.generering — HTML-sidegenerering (bede, info, index, oversigter, arkiv).

Render-lagets hovedmodul i cli-opdelingen (se briefs/cli-opdeling.md, fase 4).
Alle generer_*-funktionerne kaldes af orkestratoren (generer_alle, fase 6).
Afhænger af config (PROJECT_ROOT) + kontekst + indlaes + skabelon-env (env sendes
som parameter). skriv_hvis_ændret bor i indlaes (jf. fase 2-afvigelsen).
"""

import datetime
import os
from pathlib import Path

from .config import PROJECT_ROOT
from .kontekst import (
    ALMANAK_FIL, ENTRIES_FIL, DATA_MAPPE, PLANTE_DB, MÅNEDER, MÅNEDER_LANG, AKTIVT_ÅR,
)
from .indlaes import load_yaml, load_bed_yaml, load_frø, _les_entries_mappe, skriv_hvis_ændret

__all__ = [
    "generer_html", "generer_info_side", "generer_index",
    "generer_planter_oversigt", "generer_hoenseregisteret_oversigt",
    "generer_frø_oversigt", "generer_samlet_arkiv",
    "generer_redirect_index", "projekt_info",
    "_sync_mappe", "_generer_manglende_thumbnails",
]


def generer_html(yaml_sti, html_sti, env, alle_planter, nav_context=None,
                 almanak_fil=None, entries_fil=None, data_mappe_sti=None):
    _almanak_fil  = Path(almanak_fil)  if almanak_fil  else ALMANAK_FIL
    _entries_fil  = Path(entries_fil)  if entries_fil  else ENTRIES_FIL
    _data_mappe   = Path(data_mappe_sti) if data_mappe_sti else DATA_MAPPE
    data      = load_bed_yaml(yaml_sti)
    html_navn = data["meta"].get("html_navn", yaml_sti.replace(".yaml", ""))

    # Filtrér planter til kun dem der er relevante for denne side
    relevante_ids = set()
    for bed in data.get("bede", []):
        for zone in bed.get("zoner", []):
            for kilde in zone.get("afgrøder", []):
                if kilde.get("plante_id"):
                    relevante_ids.add(kilde["plante_id"])
    for pid in data.get("kalender_planter", []):
        relevante_ids.add(pid)
    relevante_planter = sorted(
        [p for p in alle_planter if p.get("id") in relevante_ids],
        key=lambda p: p["navn"]
    )

    # Almanak — filtrér samlet almanak.yaml på dette områdes id
    almanak_måneder = []
    if os.path.exists(_almanak_fil):
        alm = load_yaml(_almanak_fil)
        for m in alm.get("måneder", []):
            mån = {
                "måned": m["måned"],
                "navn":  m["navn"],
                "indledning":   next((i["tekst"] for i in m.get("indledninger", [])
                                      if i["område_id"] == html_navn), None),
                "begivenheder": [b["tekst"] for b in m.get("begivenheder", [])
                                 if b["område_id"] == html_navn],
                "entries":      [],
            }
            almanak_måneder.append(mån)

        # Indlæs entries fra entries.yaml og fordel på måneder
        if os.path.exists(_entries_fil):
            entries_data = load_yaml(_entries_fil)
            for e in (entries_data.get("entries") or []):
                if e.get("område_id") != html_navn:
                    continue
                e_kopi = dict(e)
                if hasattr(e_kopi.get("dato"), "isoformat"):
                    e_kopi["dato"] = e_kopi["dato"].isoformat()
                # Normaliser plante_id og berig med plantenavne
                pid = e_kopi.get("plante_id")
                if pid is None:
                    e_kopi["plante_id"] = []
                elif isinstance(pid, str):
                    e_kopi["plante_id"] = [pid] if pid else []
                elif not isinstance(pid, list):
                    e_kopi["plante_id"] = list(pid)
                e_kopi["plante_navne"] = [PLANTE_DB.get(p, {}).get("navn", p)
                                          for p in e_kopi["plante_id"] if p]
                try:
                    måned_nr = int(str(e_kopi["dato"]).split("-")[1])
                    if not 1 <= måned_nr <= len(almanak_måneder):
                        raise ValueError(f"ugyldig måned {måned_nr}")
                    almanak_måneder[måned_nr - 1]["entries"].append(e_kopi)
                except (KeyError, IndexError, ValueError):
                    pass
        # Indlæs entries fra markdown-mappe
        entries_mappe = os.path.join(_data_mappe, "entries", "sektioner")
        for e in _les_entries_mappe(entries_mappe):
            if (e.get("zone") or e.get("område_id", "")) != html_navn:
                continue
            e_kopi = dict(e)
            if hasattr(e_kopi.get("dato"), "isoformat"):
                e_kopi["dato"] = e_kopi["dato"].isoformat()
            # Berig med plantenavne (plante_id er allerede normaliseret til liste af _les_entries_mappe)
            e_kopi["plante_navne"] = [PLANTE_DB.get(p, {}).get("navn", p)
                                      for p in e_kopi.get("plante_id", []) if p]
            try:
                måned_nr = int(str(e_kopi["dato"]).split("-")[1])
                if not 1 <= måned_nr <= len(almanak_måneder):
                    raise ValueError(f"ugyldig måned {måned_nr}")
                almanak_måneder[måned_nr - 1]["entries"].append(e_kopi)
            except (KeyError, IndexError, ValueError):
                pass
        # Sortér entries ældste først (stigende dato)
        for mån in almanak_måneder:
            mån["entries"].sort(key=lambda e: str(e["dato"]))
    har_almanak = bool(almanak_måneder)

    # Beregn naboadvarsler pr. bed (muterer en kopi — original data rørtes ikke)
    bede = [dict(bed) for bed in data.get("bede", [])]
    for bed in bede:
        bed["_advarsler"] = _beregn_nabo_advarsler(bed.get("zoner", []), PLANTE_DB)

    skabelon = env.get_template("have.html")
    output = skabelon.render(
        titel           = data["meta"]["titel"],
        år              = data["meta"]["år"],
        ikon            = data["meta"].get("ikon", "🌿"),
        ikon_billede    = data["meta"].get("ikon_billede", ""),
        undertitel      = data["meta"].get("undertitel", ""),
        beskrivelse     = data["meta"].get("beskrivelse", ""),
        bede            = bede,
        planter         = relevante_planter,
        måneder         = MÅNEDER,
        har_almanak     = har_almanak,
        almanak_måneder = almanak_måneder,
        aktuel_måned    = datetime.date.today().month,
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(html_sti, output):
        print(f"✅ HTML genereret: {html_sti}")
    else:
        print(f"ℹ️  HTML uændret: {html_sti}")


def generer_info_side(yaml_sti, html_sti, env, nav_context=None):
    """Generer en simpel info-side (om.html, kontakt.html) fra YAML."""
    data = load_yaml(yaml_sti)
    år   = datetime.date.today().year
    skabelon = env.get_template("info.html")
    output = skabelon.render(
        titel   = data.get("titel", ""),
        år      = år,
        indhold = data.get("indhold", []),
        kontakt = data.get("kontakt", []),
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(html_sti, output):
        print(f"✅ Info-side genereret: {html_sti}")
    else:
        print(f"ℹ️  Info-side uændret: {html_sti}")


def generer_index(projekter, index_sti, env, nav_context=None, hero_billede="", år=None):
    skabelon = env.get_template("index.html")
    output = skabelon.render(projekter=projekter, år=år if år is not None else AKTIVT_ÅR, hero_billede=hero_billede, **(nav_context or {}))
    if skriv_hvis_ændret(index_sti, output):
        print(f"✅ Index genereret: {index_sti}")
    else:
        print(f"ℹ️  Index uændret: {index_sti}")


def _aktiv_plante_id(zone: dict) -> str | None:
    """Returner plante_id for den aktive afgrøde i zonen — spejler aktiv_afgrøde-filteret."""
    afgrøder = zone.get("afgrøder", [])
    if not afgrøder:
        return zone.get("plante_id") or None
    måned = datetime.date.today().month

    def er_aktiv(a):
        fra, til = a.get("fra", 1), a.get("til", 12)
        return (fra <= måned <= til) if fra <= til else (måned >= fra or måned <= til)

    aktive = [(i, a) for i, a in enumerate(afgrøder) if er_aktiv(a)]
    if aktive:
        _, best_a = max(aktive, key=lambda x: x[1].get("fra", 1))
        return best_a.get("plante_id") or None
    return afgrøder[0].get("plante_id") or None


def _beregn_nabo_advarsler(zoner: list, plante_db: dict) -> list:
    """Gennemgår tilstødende zone-par i et bed og returnerer naboadvarsler.

    Hvert par (zoner[i], zoner[i+1]) kontrolleres i begge retninger.
    Samme par+type vises kun én gang (dedupliceret via frozenset-nøgle).
    Returnerer liste af dicts med: zone_a, zone_b, type ('god'|'dårlig'),
    note, plante_a, plante_b.
    """
    advarsler = []
    set_nøgler: set = set()

    for i in range(len(zoner) - 1):
        zone_a = zoner[i]
        zone_b = zoner[i + 1]
        pid_a  = _aktiv_plante_id(zone_a)
        pid_b  = _aktiv_plante_id(zone_b)
        if not pid_a or not pid_b:
            continue

        plante_a = plante_db.get(pid_a, {})
        plante_b = plante_db.get(pid_b, {})
        navn_a   = plante_a.get("navn") or pid_a
        navn_b   = plante_b.get("navn") or pid_b
        zone_a_navn = zone_a.get("navn") or f"Zone {i + 1}"
        zone_b_navn = zone_b.get("navn") or f"Zone {i + 2}"

        for kilde_pid, kilde_plante, a_navn, b_navn in [
            (pid_a, plante_a, navn_a, navn_b),
            (pid_b, plante_b, navn_b, navn_a),
        ]:
            modpart_pid = pid_b if kilde_pid == pid_a else pid_a
            naboer = kilde_plante.get("naboer") or {}
            for retning, type_ in [("gode", "god"), ("dårlige", "dårlig")]:
                for nabo in naboer.get(retning) or []:
                    if nabo.get("plante_id") != modpart_pid:
                        continue
                    nøgle = (frozenset({pid_a, pid_b}), type_)
                    if nøgle in set_nøgler:
                        break
                    set_nøgler.add(nøgle)
                    advarsler.append({
                        "zone_a":   zone_a_navn,
                        "zone_b":   zone_b_navn,
                        "type":     type_,
                        "note":     nabo.get("note") or "",
                        "plante_a": a_navn,
                        "plante_b": b_navn,
                    })
                    break

    advarsler.sort(key=lambda a: 0 if a["type"] == "god" else 1)
    return advarsler


def _berig_naboer(p: dict) -> dict:
    """Berig en plante-post med display_navn og _fundet på alle naboer.

    Kopierer posten og naboer-subdict — muterer ikke originalen.
    Skabelonen behøver ikke selv slå op i PLANTE_DB.
    """
    naboer = p.get("naboer")
    if not naboer:
        return p
    p = dict(p)

    def berig_liste(liste):
        resultat = []
        for nabo in (liste or []):
            nabo = dict(nabo)
            pid = nabo.get("plante_id", "")
            ref = PLANTE_DB.get(pid, {})
            if ref:
                navn = ref.get("navn", pid)
                sort = ref.get("sort")
                nabo["display_navn"] = f"{navn} {sort}" if sort else navn
                nabo["_fundet"] = True
            else:
                nabo["display_navn"] = pid
                nabo["_fundet"] = False
            resultat.append(nabo)
        return resultat

    naboer = dict(naboer)
    naboer["gode"]    = berig_liste(naboer.get("gode",    []))
    naboer["dårlige"] = berig_liste(naboer.get("dårlige", []))
    p["naboer"] = naboer
    return p


def generer_planter_oversigt(alle_planter, yaml_filer, planter_sti, env, nav_context=None):
    """Generer planter.html — grupperingen og ikoner afledes fra meta i bed-YAML'erne."""
    id_til_gruppe: dict = {}
    gruppe_rækkefølge: list = []
    gruppe_ikoner: dict = {}
    gruppe_url: dict = {}

    for yaml_sti in yaml_filer:
        if not os.path.exists(yaml_sti):
            continue
        data  = load_bed_yaml(yaml_sti)
        meta  = data.get("meta", {})
        titel = meta.get("titel", yaml_sti)
        ikon  = meta.get("ikon", "🌿")
        html_navn = meta.get("html_navn", "")
        if titel not in gruppe_rækkefølge:
            gruppe_rækkefølge.append(titel)
            gruppe_ikoner[titel] = ikon
            if html_navn:
                gruppe_url[titel] = f"{html_navn}.html"
        for bed in data.get("bede", []):
            for zone in bed.get("zoner", []):
                for kilde in zone.get("afgrøder", []):
                    pid = kilde.get("plante_id")
                    if pid and pid not in id_til_gruppe:
                        id_til_gruppe[pid] = titel
        for pid in data.get("kalender_planter", []):
            if pid not in id_til_gruppe:
                id_til_gruppe[pid] = titel

    IKKE_I_HAVEN = "Ikke i haven"
    gruppe_rækkefølge.append(IKKE_I_HAVEN)
    grupper_dict: dict = {g: [] for g in gruppe_rækkefølge}
    for p in alle_planter:
        g = id_til_gruppe.get(p.get("id"), IKKE_I_HAVEN)
        grupper_dict[g].append(p)
    for planter in grupper_dict.values():
        planter.sort(key=lambda p: (p.get("navn", ""), p.get("sort", "")))
    grupper = [
        {"navn": g, "ikon": gruppe_ikoner.get(g, "🌿"), "url": gruppe_url.get(g, ""),
         "planter": [_berig_naboer(p) for p in grupper_dict[g]]}
        for g in gruppe_rækkefølge if grupper_dict.get(g)
    ]
    skabelon = env.get_template("planter.html")
    output = skabelon.render(
        år=datetime.date.today().year, grupper=grupper,
        måneder=MÅNEDER, måneder_lang=MÅNEDER_LANG,
        antal_planter=len(alle_planter),
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(planter_sti, output):
        print(f"✅ Planterside genereret: {planter_sti}")
    else:
        print(f"ℹ️  Planterside uændret: {planter_sti}")


def generer_hoenseregisteret_oversigt(alle_hoener, hoense_sti, env, nav_context=None):
    """Generer hoenseregisteret.html — hønseflokken fra dyr.yaml, aktive først.

    Samme mønster som generer_planter_oversigt: ét register delt på tværs af år.
    """
    i_år = datetime.date.today().year

    def berig(h):
        h = dict(h)
        fd = str(h.get("fødselsdato", "") or "")
        h["alder"] = (i_år - int(fd[:4])) if len(fd) >= 4 and fd[:4].isdigit() else None
        return h

    def sorter(liste):
        liste.sort(key=lambda h: (h.get("navn") or h.get("race") or "",
                                  str(h.get("fødselsdato", ""))))
        return liste

    aktive  = sorter([berig(h) for h in alle_hoener if h.get("aktiv", True)])
    udgåede = sorter([berig(h) for h in alle_hoener if not h.get("aktiv", True)])

    skabelon = env.get_template("hoenseregisteret.html")
    output = skabelon.render(
        år=i_år, aktive=aktive, udgåede=udgåede,
        antal_aktive=len(aktive), antal=len(alle_hoener),
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(hoense_sti, output):
        print(f"✅ Hønseregister genereret: {hoense_sti}")
    else:
        print(f"ℹ️  Hønseregister uændret: {hoense_sti}")


def generer_frø_oversigt(frø_sti, env, nav_context=None):
    """Generer frø.html — frøsamlingen fra data/frø.yaml, aktive poster øverst.

    Beriger poster med plantedata fra PLANTE_DB hvis plante_id er sat.
    Sorterer aktive efter bedst_før (stigende — ældste frø øverst).
    """
    i_år = datetime.date.today().year
    aktive, arkiverede = load_frø()

    def berig(post):
        post = dict(post)
        pid = post.get("plante_id")
        if pid and pid in PLANTE_DB:
            post["_plante"] = PLANTE_DB[pid]
        bedst_før = post.get("bedst_før")
        if isinstance(bedst_før, int):
            if bedst_før < i_år:
                post["_udløbet"] = True
            elif bedst_før == i_år:
                post["_udløber_snart"] = True
        return post

    aktive     = sorted([berig(p) for p in aktive],     key=lambda p: (p.get("bedst_før") or 9999, p.get("navn", "")))
    arkiverede = [berig(p) for p in arkiverede]

    skabelon = env.get_template("frø.html")
    output = skabelon.render(
        år=i_år, aktive=aktive, arkiverede=arkiverede,
        antal_aktive=len(aktive), antal=len(aktive) + len(arkiverede),
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(frø_sti, output):
        print(f"✅ Frøsamling genereret: {frø_sti}")
    else:
        print(f"ℹ️  Frøsamling uændret: {frø_sti}")


def generer_samlet_arkiv(år_liste, arkiv_samlet_sti, env, plante_db=None, nav_context=None):
    """Generer arkiv-samlet.html — alle bede med planter på tværs af alle år."""
    data_rod = PROJECT_ROOT / "data"
    plante_db = plante_db or {}

    # Aggreger: {html_navn: {titel, ikon, bede: {bed_id: {navn, år: {år: [planter]}}}}}
    områder: dict = {}

    for år in sorted(år_liste):
        år_mappe = data_rod / str(år)
        if not år_mappe.is_dir():
            continue
        for yaml_fil in sorted(år_mappe.glob("*.yaml")):
            if yaml_fil.name.startswith("."):
                continue
            if yaml_fil.name in ("almanak.yaml", "entries.yaml", "planter.yaml"):
                continue
            data = load_bed_yaml(str(yaml_fil))
            meta = data.get("meta", {})
            html_navn = meta.get("html_navn")
            if not html_navn:
                continue
            titel = meta.get("titel", html_navn)
            ikon = meta.get("ikon", "🌿")

            if html_navn not in områder:
                områder[html_navn] = {"titel": titel, "ikon": ikon, "bede": {}}

            for bed in data.get("bede", []):
                bed_id = bed.get("id", "")
                bed_navn = bed.get("navn", bed_id)

                if bed_id not in områder[html_navn]["bede"]:
                    områder[html_navn]["bede"][bed_id] = {"navn": bed_navn, "år": {}}

                seen: set = set()
                planter_i_år: list = []
                for zone in bed.get("zoner", []):
                    for afgrøde in zone.get("afgrøder", []):
                        plante_id = afgrøde.get("plante_id", "")
                        plante = plante_db.get(plante_id, {})
                        navn = plante.get("navn", plante_id)
                        sort = afgrøde.get("sort") or plante.get("sort", "")
                        key = (navn, sort)
                        if key not in seen:
                            seen.add(key)
                            planter_i_år.append({"navn": navn, "sort": sort})

                if planter_i_år:
                    områder[html_navn]["bede"][bed_id]["år"][år] = planter_i_år

    områder = {
        navn: område
        for navn, område in områder.items()
        if any(bed["år"] for bed in område["bede"].values())
    }

    skabelon = env.get_template("arkiv_samlet.html")
    output = skabelon.render(
        titel="Samlet arkiv",
        år=datetime.date.today().year,
        områder=områder,
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(str(arkiv_samlet_sti), output):
        print(f"✅ Samlet arkiv genereret: {arkiv_samlet_sti}")
    else:
        print(f"ℹ️  Samlet arkiv uændret: {arkiv_samlet_sti}")


def generer_redirect_index(out_basis: str, aktivt_år: int) -> None:
    """Generer out/index.html som simpel redirect til aktivt år."""
    os.makedirs(out_basis, exist_ok=True)
    html = f"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url={aktivt_år}/index.html">
<link rel="canonical" href="{aktivt_år}/index.html">
</head>
<body><p><a href="{aktivt_år}/index.html">Gå til haven {aktivt_år}</a></p></body>
</html>"""
    sti = os.path.join(out_basis, "index.html")
    if skriv_hvis_ændret(sti, html):
        print(f"✅ Redirect-index genereret: {sti}")
    else:
        print(f"ℹ️  Redirect-index uændret: {sti}")


def projekt_info(yaml_sti):
    """Læs projektmetadata direkte fra YAML-filens meta-blok."""
    data      = load_yaml(yaml_sti)
    meta      = {} if isinstance(data, list) else data.get("meta", {})
    html_navn = meta.get("html_navn", Path(yaml_sti).stem)
    return {
        "titel":       meta.get("titel", html_navn),
        "html_navn":   html_navn,
        "undertitel":  meta.get("undertitel", ""),
        "beskrivelse": meta.get("beskrivelse", ""),
        "ikon":        meta.get("ikon", "🌿"),
        "ikon_billede":meta.get("ikon_billede", ""),
        "tags":        meta.get("tags", []),
    }


_BILLEDE_EKST = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _sync_mappe(kilde: Path, dest: Path) -> int:
    """Kopiér kilde → dest, kun filer der er nye eller nyere. Returnerer antal kopierede filer."""
    import shutil
    dest.mkdir(parents=True, exist_ok=True)
    kopierede = 0
    for src in kilde.iterdir():
        dst = dest / src.name
        if src.is_dir():
            kopierede += _sync_mappe(src, dst)
        elif not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(src, dst)
            os.chmod(dst, 0o644)
            kopierede += 1
    return kopierede


def _generer_manglende_thumbnails(fotos_mappe: Path):
    """Generer thumbs/<fil> (maks 400px) for billeder der mangler thumbnail."""
    from PIL import Image, ImageOps
    thumbs = fotos_mappe / "thumbs"
    thumbs.mkdir(exist_ok=True)
    for billedfil in sorted(fotos_mappe.iterdir()):
        if not billedfil.is_file() or billedfil.suffix.lower() not in _BILLEDE_EKST:
            continue
        thumb = thumbs / billedfil.name
        if thumb.exists():
            continue
        try:
            with Image.open(billedfil) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((400, 400))
                if billedfil.suffix.lower() in (".jpg", ".jpeg"):
                    img.save(thumb, "JPEG", quality=82, optimize=True)
                else:
                    img.save(thumb, optimize=True)
        except Exception:
            pass
