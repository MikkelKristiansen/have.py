"""haven.validering — L2/L3-validering + `have check` + schema-generering.

Render-uafhængigt lag i cli-opdelingen (se briefs/cli-opdeling.md, fase 2).
Afhænger kun af kontekst + config + models + indlaes. Importeres af cli.

L2 = strukturel (Pydantic), L3 = referentiel (krydsreferencer + fotofiler).
`check` er det brugervendte dry-run; den kalder ikke validatorerne, men laver sin
egen bløde fejl/advarsel-rapport.
"""

import os
import sys
from pathlib import Path

from pydantic import ValidationError

from .config import sti, PROJECT_ROOT
from .kontekst import (
    _config, PLANTER_FIL, DYR_FIL, FRØ_FIL, SKADEDYR_FIL, FOTOS_MAPPE, DATA_MAPPE,
    AKTIVT_ÅR, ALMANAK_FIL, ENTRIES_FIL, ROTATION_CYKLUS, TUNGE_FAMILIER, PLANTE_DB,
)
from .models import Plante, Høne
from .indlaes import (
    load_yaml, load_bed_yaml, skriv_hvis_ændret, load_skadedyr,
    find_dominerende_familier,
)

__all__ = [
    "valider_planter", "valider_hoenser", "valider_referencer", "valider_frø",
    "valider_skadedyr",
    "check", "opdater_schema_plante_ids", "opdater_schema_planter",
]


# ── L2: Strukturel validering af plantedatabasen ───────────────────────────────
#
# Skemaet er udledt fra templates/planter.html og have.html.
# Opdatér _FOTO_PÅKRÆVEDE_FELTER når templates ændrer sig.

_FOTO_PÅKRÆVEDE_FELTER = {"fil": str}   # underfelter der altid dereferences


def valider_planter(db: dict) -> None:
    """L2: Kontrollér at hvert plant-objekt har den form templates forventer."""
    fejl = []
    for pid, data in db.items():
        try:
            Plante(**data)
        except ValidationError as e:
            for felt in e.errors():
                loc = ".".join(str(x) for x in felt["loc"])
                fejl.append((PLANTER_FIL.name, f"{pid}.{loc}: {felt['msg']}"))
    _print_fejl_og_afslut(fejl)

    # Bløde advarsler for ukendte nabo-referencer (ikke fejl — intentionelt)
    for pid, data in db.items():
        naboer = data.get("naboer") or {}
        for retning in ("gode", "dårlige"):
            for nabo in naboer.get(retning) or []:
                nabo_id = nabo.get("plante_id", "")
                if nabo_id and nabo_id not in db:
                    print(f"[ADVARSEL] {PLANTER_FIL.name}: {pid}.naboer.{retning}: "
                          f"plante_id {nabo_id!r} ikke fundet i planter.yaml",
                          file=sys.stderr)


def valider_hoenser(db: dict) -> None:
    """L2: Kontrollér at hvert høne-objekt har den form hoenseregisteret.html forventer."""
    fejl = []
    for hid, data in db.items():
        try:
            Høne(**data)
        except ValidationError as e:
            for felt in e.errors():
                loc = ".".join(str(x) for x in felt["loc"])
                fejl.append((DYR_FIL.name, f"{hid}.{loc}: {felt['msg']}"))
    _print_fejl_og_afslut(fejl)


# ── L3: Referentiel validering ─────────────────────────────────────────────────

def valider_referencer(db: dict, bede_yaml_filer: list) -> None:
    """L3: Kontrollér plante_id-referencer og lokale fotofiler.

    L3a — plante_id i bed-filer: bede[].zoner[].plante_id og
          bede[].zoner[].afgrøder[].plante_id og kalender_planter[].
    L3b — lokale foto-filer: p.foto.fil der ikke starter med http.

    Forudsætter at valider_planter har kørt og bestået (db er strukturelt gyldig).
    Samler alle fejl og afslutter med sys.exit(1) ved fund.
    """
    fejl: list[tuple[str, str]] = []

    # L3a: plante_id-referencer i bed-filer
    for yaml_sti in bede_yaml_filer:
        yaml_sti = Path(yaml_sti)
        if not yaml_sti.exists():
            continue
        data = load_bed_yaml(yaml_sti)
        fil = yaml_sti.name

        for bed in data.get("bede", []):
            bed_navn = bed.get("navn") or bed.get("id") or "?"
            for zone in bed.get("zoner", []):
                for kilde in zone.get("afgrøder", []):
                    pid = kilde.get("plante_id")
                    if pid and pid not in db:
                        fejl.append((fil,
                            f"bed {bed_navn!r}: refererer ukendt plante_id {pid!r}"))

        for pid in data.get("kalender_planter", []):
            if pid and pid not in db:
                fejl.append((fil,
                    f"kalender_planter: refererer ukendt plante_id {pid!r}"))

    # L3b: lokale fotofiler
    fotos_mappe = sti(_config, "fotos") / "planter"
    for pid, p in db.items():
        foto = p.get("foto")
        if not isinstance(foto, dict):
            continue
        fil_val = foto.get("fil", "")
        if not isinstance(fil_val, str) or fil_val.startswith("http"):
            continue
        if not (fotos_mappe / fil_val).exists():
            fejl.append((PLANTER_FIL.name,
                f"{pid}.foto.fil: {fil_val!r} findes ikke i fotos/planter/"))

    _print_fejl_og_afslut(fejl)


# ── Frøsamling ─────────────────────────────────────────────────────────────────

def valider_frø(frø_data: list, plante_ids: set) -> list:
    """Blød validering af frøposter. Returnerer liste af (niveau, besked)-tupler.

    niveau er 'W' (advarsel). Ingen 'E'-fejl fra frø — manglende plante_id og
    foto er altid bløde advarsler, aldrig showstoppere.
    """
    issues = []
    for i, post in enumerate(frø_data):
        navn = post.get("navn") or f"[{i}]"
        pid  = post.get("plante_id")
        if pid and pid not in plante_ids:
            issues.append(("W",
                f"frø '{navn}': plante_id {pid!r} ikke fundet i planter.yaml "
                f"— tilføj planten eller fjern plante_id-feltet"))
        foto = post.get("foto")
        if foto and isinstance(foto, str) and not foto.startswith("http"):
            # foto er kun filnavnet — fotos/frø/ ligger i skabelonen, ikke i dataene
            if not (FOTOS_MAPPE / "frø" / foto).is_file():
                issues.append(("W",
                    f"frø '{navn}': foto {foto!r} findes ikke i fotos/frø/ "
                    f"— tilføj filen eller ret foto-feltet (kun filnavn, ikke sti)"))
    return issues


# ── Skadedyr ─────────────────────────────────────────────────────────────────────

def valider_skadedyr(skadedyr_data: dict, plante_db: dict) -> list:
    """Blød validering af skadedyr-referencer. Returnerer (niveau, besked)-tupler.

    niveau er altid 'W' (advarsel) — skadedyr giver aldrig hårde 'E'-fejl:
      - Advarsel hvis et skadedyr_id i en plantes skadedyr_ids ikke findes
        i skadedyr.yaml.
      - Info-advarsel hvis en plantes familie ikke dækkes af nogen post i
        skadedyr.yaml (konsolideret til én linje).
    """
    issues = []
    kendte_ids = set(skadedyr_data.keys())
    dækkede_familier = {
        f for s in skadedyr_data.values() for f in (s.get("familier") or [])
    }

    udækkede_familier: dict = {}
    for pid, p in plante_db.items():
        for sid in p.get("skadedyr_ids") or []:
            if sid not in kendte_ids:
                issues.append(("W",
                    f"plante '{pid}': skadedyr_id {sid!r} ikke fundet i skadedyr.yaml "
                    f"— tilføj det eller ret referencen"))
        fam = p.get("familie")
        if fam and fam not in dækkede_familier:
            udækkede_familier.setdefault(fam, []).append(pid)

    if udækkede_familier:
        issues.append(("W",
            f"{len(udækkede_familier)} plantefamilie(r) har ingen skadedyr i "
            f"skadedyr.yaml: {', '.join(sorted(udækkede_familier))} — "
            f"tilføj familien til et skadedyr eller ignorer (kun info)"))

    return issues


# ── Hjælpefunktioner ───────────────────────────────────────────────────────────

def _print_fejl_og_afslut(fejl: list) -> None:
    """Printer fejlliste grupperet efter filnavn og kalder sys.exit(1) ved fejl."""
    if not fejl:
        return
    fra_filer: dict = {}
    for fil, besked in fejl:
        fra_filer.setdefault(fil, []).append(besked)
    for fil, beskeder in fra_filer.items():
        print(f"❌ Fejl i {fil}:", file=sys.stderr)
        for b in beskeder:
            print(f"  • {b}", file=sys.stderr)
    sys.exit(1)


# ── have check (brugervendt dry-run) ─────────────────────────────────────────────

def check(yaml_filer, strict=False, farver=False):
    """Validér hele projektet — kritiske fejl og advarsler med præcise handlingsanvisninger."""
    fejl = 0
    advarsler = 0

    def E(tekst):
        nonlocal fejl
        print(f"  ❌ {tekst}")
        fejl += 1

    def W(tekst):
        nonlocal advarsler, fejl
        if strict:
            print(f"  ❌ {tekst}  [strict]")
            fejl += 1
        else:
            print(f"  ⚠️  {tekst}")
        advarsler += 1

    def OK(tekst):
        print(f"  ✅ {tekst}")

    # ── 0. Pre-flight ──────────────────────────────────────────────────────────
    print(f"\n🔍 0. Pre-flight\n")

    if not os.path.isdir(DATA_MAPPE):
        E(f"{DATA_MAPPE}/ eksisterer ikke — "
          f"kør: have nyt-år {AKTIVT_ÅR}")
    else:
        OK(f"{DATA_MAPPE}/ fundet")

    if not os.path.isfile(PLANTER_FIL):
        E(f"{PLANTER_FIL} mangler — opret filen eller kør: have init")
    else:
        OK(f"{PLANTER_FIL} fundet")

    PÅKRÆVEDE_SKABELONER = ["base.html", "have.html", "index.html",
                             "almanak.html", "planter.html"]
    if os.path.isdir("templates"):
        mangler_tmpl = [t for t in PÅKRÆVEDE_SKABELONER
                        if not os.path.isfile(os.path.join("templates", t))]
        if mangler_tmpl:
            for t in mangler_tmpl:
                E(f"templates/{t} mangler — er templates/-mappen ufuldstændig?")
        else:
            OK(f"templates/ komplet ({len(PÅKRÆVEDE_SKABELONER)} filer)")
    else:
        OK("templates/ bruger pakkedata (ingen lokal tilpasning)")

    fotos_entries = os.path.join("fotos", "entries", str(AKTIVT_ÅR))
    if not os.path.isdir(fotos_entries):
        W(f"{fotos_entries}/ mangler — "
          f"opret mappen eller kør: have nyt-år {AKTIVT_ÅR}")
    else:
        OK(f"{fotos_entries}/ fundet")

    if fejl:
        print(f"\n{'─'*40}")
        print(f"❌ {fejl} kritiske fejl — ret dem før du fortsætter.\n")
        return

    # ── 1. planter.yaml ────────────────────────────────────────────────────────
    print(f"\n🔍 1. planter.yaml\n")

    planter_data = load_yaml(PLANTER_FIL)
    alle_planter = planter_data if isinstance(planter_data, list) \
                   else planter_data.get("planter", [])

    # Unikke id'er
    ids = [p.get("id") for p in alle_planter]
    duplikater = {pid for pid in ids if pid and ids.count(pid) > 1}
    ingen_id   = [p for p in alle_planter if not p.get("id")]
    for p in ingen_id:
        E(f"Plante uden id: '{p.get('navn','?')}' — tilføj et unikt id-felt")
    for pid in sorted(duplikater):
        positioner = [i+1 for i, p in enumerate(alle_planter) if p.get("id") == pid]
        E(f"Duplikat id '{pid}' — den {positioner}. plante i rækkefølgen i "
          f"{PLANTER_FIL.name} (ikke fil-linjenummer). id'er skal være unikke")
    if not ingen_id and not duplikater:
        OK(f"{len(alle_planter)} planter — id'er unikke")

    # Påkrævede felter
    for p in alle_planter:
        if not p.get("navn"):
            E(f"id='{p.get('id','?')}': mangler navn-felt — tilføj navn til planten")

    # Anbefalede felter
    mangler_latin = [p for p in alle_planter if not p.get("latin")]
    if mangler_latin:
        W(f"{len(mangler_latin)} planter mangler latin-felt "
          f"({', '.join(p.get('id','?') for p in mangler_latin[:5])}"
          f"{'…' if len(mangler_latin) > 5 else ''}) — "
          f"have hent-fotos kan ikke søge dem")
    else:
        OK(f"Alle {len(alle_planter)} planter har latin-felt")

    mangler_farve = [p for p in alle_planter if not p.get("farve")]
    if mangler_farve:
        W(f"{len(mangler_farve)} planter mangler farve-felt "
          f"({', '.join(p.get('id','?') for p in mangler_farve[:5])}"
          f"{'…' if len(mangler_farve) > 5 else ''}) — "
          f"bede vises med standardfarve")
    else:
        OK(f"Alle {len(alle_planter)} planter har farve-felt")

    # Billeder
    fotos_planter = os.path.join("fotos", "planter")
    for p in alle_planter:
        foto_data = p.get("foto")
        if isinstance(foto_data, dict):
            foto = foto_data.get("fil", "")
            if foto and not foto.startswith("http"):
                sti = os.path.join(fotos_planter, foto)
                if not os.path.isfile(sti):
                    W(f"fotos/planter/{foto} refereret i '{p.get('id','?')}' "
                      f"men filen eksisterer ikke — "
                      f"tilføj filen eller ret foto-feltet")

    # Kalenderdata
    kal_advarsler_før = advarsler
    for p in alle_planter:
        navn = p.get("navn", "?")
        pid  = p.get("id", "?")
        hf   = p.get("høst_fra")
        ht   = p.get("høst_til")
        ind  = p.get("indendørs")
        upl  = p.get("udplantning")
        dir_ = p.get("direkte")

        if hf and ht and hf > ht:
            if not (hf > 6 and ht < 6):
                W(f"'{pid}' ({navn}): høst_fra={hf} > høst_til={ht} — "
                  f"ret tallene, eller er det wrap-around (fx grønkål okt–mar)?")
            else:
                OK(f"'{pid}' ({navn}): wrap-around høst ({hf}–{ht}) antaget")

        if ind and upl and ind > upl:
            W(f"'{pid}' ({navn}): indendørs={ind} > udplantning={upl} — "
              f"udplantning skal være efter forspiring")

        if not any([hf, ind, upl, dir_]):
            W(f"'{pid}' ({navn}): ingen kalenderdata — "
              f"tilføj mindst ét af høst_fra/indendørs/udplantning/direkte")

        for felt, val in [("indendørs", ind), ("udplantning", upl),
                          ("direkte", dir_), ("høst_fra", hf), ("høst_til", ht)]:
            if val is not None and not (1 <= val <= 12):
                E(f"'{pid}' ({navn}): {felt}={val} er ikke 1–12 — "
                  f"brug månedsnummer 1–12")

    if advarsler == kal_advarsler_før and fejl == 0:
        OK("Kalenderdata ser fornuftig ud")

    # ── 2. YAML-projektfiler ───────────────────────────────────────────────────
    print(f"\n🔍 2. YAML-projektfiler\n")

    plante_ids_db = {p["id"] for p in alle_planter if p.get("id")}
    kendte_html_navne = set()

    for yaml_sti in yaml_filer:
        if not os.path.isfile(yaml_sti):
            E(f"{yaml_sti} mangler — ret bede-listen i haven.yaml "
              f"eller opret filen med: have ny-bed")
            continue

        data  = load_bed_yaml(yaml_sti)
        meta  = data.get("meta", {})
        titel = meta.get("titel", yaml_sti)

        # meta.html_navn
        html_navn = meta.get("html_navn")
        if not html_navn:
            E(f"{yaml_sti}: meta.html_navn mangler — "
              f"siden kan ikke genereres, tilføj fx 'html_navn: hoejbede'")
        else:
            kendte_html_navne.add(html_navn)

        # meta.år
        meta_år = meta.get("år")
        if meta_år and meta_år != AKTIVT_ÅR:
            W(f"{yaml_sti}: meta.år={meta_år} men AKTIVT_ÅR={AKTIVT_ÅR} — "
              f"opdatér meta.år i filen eller aktivt_år i haven.yaml")

        # plante_id krydsreferencer
        ukendte = []
        for bed in data.get("bede", []):
            bed_navn = bed.get("navn", "?")
            for zone in bed.get("zoner", []):
                for kilde in zone.get("afgrøder", []):
                    pid = kilde.get("plante_id", "")
                    if pid and pid not in plante_ids_db:
                        ukendte.append(f"{bed_navn}/{pid}")
        for pid in data.get("kalender_planter", []):
            if pid not in plante_ids_db:
                ukendte.append(f"kalender_planter/{pid}")
        if ukendte:
            W(f"{titel}: {len(ukendte)} ukendt(e) plante_id(er): "
              f"{', '.join(ukendte[:4])}{'…' if len(ukendte) > 4 else ''} — "
              f"tilføj dem til {PLANTER_FIL}")
        else:
            OK(f"{titel}: alle plante_id'er fundet i databasen")

        # Bredde-sum pr. bed
        for bed in data.get("bede", []):
            zoner = bed.get("zoner", [])
            if not zoner:
                continue
            if not all(z.get("bredde") is not None for z in zoner):
                continue  # ingen bredde-felter — spring over
            total = sum(z.get("bredde", 0) for z in zoner)
            if abs(total - 1.0) > 0.01:
                W(f"{titel} / {bed.get('navn','?')}: "
                  f"bredde-sum = {total:.2f} (forventet 1.0) — "
                  f"hul eller overlap i bedvisningen")

    # ── 3. almanak.yaml ────────────────────────────────────────────────────────
    if os.path.isfile(ALMANAK_FIL) and kendte_html_navne:
        print(f"\n🔍 3. almanak.yaml\n")
        alm = load_yaml(ALMANAK_FIL)
        MÅNED_NAVNE = ["januar","februar","marts","april","maj","juni",
                       "juli","august","september","oktober","november","december"]
        mangler_ind = []
        for m in alm.get("måneder", []):
            mnr = m.get("måned")
            if not (isinstance(mnr, int) and 1 <= mnr <= 12):
                W(f"Måned-blok med ugyldigt/manglende 'måned'-felt: {mnr!r}")
                continue
            mån_navn = MÅNED_NAVNE[mnr - 1]
            ind_ids  = {i["område_id"] for i in m.get("indledninger", [])
                        if str(i.get("tekst") or "").strip()}
            for oid in kendte_html_navne:
                if oid not in ind_ids:
                    mangler_ind.append(f"{mån_navn}/{oid}")
        if mangler_ind:
            W(f"{len(mangler_ind)} indledning(er) mangler tekst i almanak.yaml "
              f"(fx {mangler_ind[0]}) — "
              f"udfyld tekst-felterne eller ignorer hvis intentionelt tomt")
        else:
            OK(f"Alle områder har indledning i alle måneder")

    # ── 4. entries.yaml ────────────────────────────────────────────────────────
    if os.path.isfile(ENTRIES_FIL) and kendte_html_navne:
        print(f"\n🔍 4. entries.yaml\n")
        entries_data = load_yaml(ENTRIES_FIL)
        entries      = entries_data.get("entries") or []
        ukendte_omr  = set()
        for e in entries:
            oid = e.get("område_id", "")
            if oid and oid not in kendte_html_navne:
                ukendte_omr.add(oid)
        if ukendte_omr:
            W(f"entries.yaml: {len(ukendte_omr)} ukendt(e) område_id(er): "
              f"{', '.join(sorted(ukendte_omr))} — "
              f"entries vises ikke; ret område_id til et af: "
              f"{', '.join(sorted(kendte_html_navne))}")
        else:
            OK(f"{len(entries)} entries — alle område_id'er kendte")

    # ── 5. frø.yaml ───────────────────────────────────────────────────────────
    if os.path.isfile(FRØ_FIL):
        print(f"\n🔍 5. frø.yaml\n")
        frø_rå = load_yaml(FRØ_FIL)
        alle_frø = frø_rå.get("frø") or []
        aktive_frø     = [f for f in alle_frø if str(f.get("rest", "")) != "tom"]
        arkiverede_frø = [f for f in alle_frø if str(f.get("rest", "")) == "tom"]
        issues = valider_frø(alle_frø, plante_ids_db)
        for niveau, besked in issues:
            if niveau == "E":
                E(besked)
            else:
                W(besked)
        if not issues:
            OK(f"{len(aktive_frø)} aktive frøposter, {len(arkiverede_frø)} arkiverede — ok")

    # ── 6. dyr.yaml ───────────────────────────────────────────────────────────────
    if os.path.isfile(DYR_FIL):
        print(f"\n🔍 6. dyr.yaml\n")
        dyr_rå  = load_yaml(DYR_FIL)
        alle_dyr = dyr_rå if isinstance(dyr_rå, list) else dyr_rå.get("dyr", [])
        fotos_dyr = os.path.join("fotos", "dyr")
        dyr_foto_fejl = []
        for d in alle_dyr or []:
            hid  = d.get("id") or d.get("navn") or "?"
            foto = d.get("foto")
            if not isinstance(foto, dict):
                continue
            fil = foto.get("fil", "")
            if not isinstance(fil, str) or not fil or fil.startswith("http"):
                continue
            if not os.path.isfile(os.path.join(fotos_dyr, fil)):
                dyr_foto_fejl.append((hid, fil))
        for hid, fil in dyr_foto_fejl:
            W(f"fotos/dyr/{fil} refereret i '{hid}' men filen eksisterer ikke — "
              f"tilføj filen eller ret foto.fil-feltet")
        if not dyr_foto_fejl:
            OK(f"{len(alle_dyr)} dyr — fotofiler ok")

    # ── 7. skadedyr.yaml ────────────────────────────────────────────────────────
    if os.path.isfile(SKADEDYR_FIL):
        print(f"\n🔍 7. skadedyr.yaml\n")
        skadedyr_db = load_skadedyr()
        plante_db_full = {p["id"]: p for p in alle_planter if p.get("id")}
        issues = valider_skadedyr(skadedyr_db, plante_db_full)
        for niveau, besked in issues:
            (E if niveau == "E" else W)(besked)
        if not issues:
            OK(f"{len(skadedyr_db)} skadedyr — referencer og familier ok")

    # ── 7. Sædskifte (kun hvis rotation.cyklus er sat) ──────────────────────────
    if ROTATION_CYKLUS:
        print(f"\n🔍 7. Sædskifte\n")
        if not PLANTE_DB:
            PLANTE_DB.update({p["id"]: p for p in alle_planter if p.get("id")})
        data_rod = DATA_MAPPE.parent
        tidligere = sorted(
            (int(p.name) for p in data_rod.iterdir()
             if p.is_dir() and p.name.isdigit() and int(p.name) < AKTIVT_ÅR),
            reverse=True,
        ) if data_rod.is_dir() else []
        if not tidligere:
            OK("Ingen tidligere år at sammenligne med — sædskifte kan ikke vurderes endnu")
        else:
            forrige_år = tidligere[0]
            gengangere = 0
            for i, bed_navn in enumerate(ROTATION_CYKLUS):
                iår   = find_dominerende_familier(AKTIVT_ÅR, bed_navn) & set(TUNGE_FAMILIER)
                ifjor = find_dominerende_familier(forrige_år, bed_navn) & set(TUNGE_FAMILIER)
                for familie in sorted(iår & ifjor):
                    næste = ROTATION_CYKLUS[(i + 1) % len(ROTATION_CYKLUS)]
                    W(f"{familie} ({TUNGE_FAMILIER[familie]}) er i {bed_navn} både i "
                      f"{forrige_år} og {AKTIVT_ÅR} — rotér til næste bed i cyklussen ({næste})")
                    gengangere += 1
            if gengangere == 0:
                OK(f"Ingen tunge familier går igen i samme bed ({forrige_år}→{AKTIVT_ÅR})")

    # ── 8. Farvetabel (kun ved --farver) ───────────────────────────────────────
    if farver:
        print(f"\n🔍 Farver\n")
        print(f"  {'Plante':<25} {'Sort':<20} Farve")
        print(f"  {'─'*58}")
        farve_mangler = []
        for p in alle_planter:
            farve = p.get("farve")
            navn  = p.get("navn", p.get("id", "?"))
            sort  = p.get("sort", "")
            if farve:
                try:
                    swatch = (f"\033[48;2;{int(farve[1:3],16)};"
                              f"{int(farve[3:5],16)};{int(farve[5:],16)}m   \033[0m")
                except ValueError:
                    swatch = "   "
                print(f"  {navn:<25} {sort:<20} {swatch} {farve}")
            else:
                print(f"  ⚠️  {navn:<23} {sort:<20} — mangler farve-felt")
                farve_mangler.append(p)
        print()
        if farve_mangler:
            print(f"  ⚠️  {len(farve_mangler)} planter mangler farve-felt.")
        else:
            print(f"  ✅ Alle {len(alle_planter)} planter har farve-felt.")

    # ── 6. Opsummering ─────────────────────────────────────────────────────────
    print(f"\n{'─'*40}")
    if fejl == 0 and advarsler == 0:
        print(f"✅ Alt ser fint ud! {len(alle_planter)} planter valideret.\n")
    elif fejl == 0:
        suffix = " — kør med --strict for at behandle dem som fejl" if not strict else ""
        print(f"⚠️  0 fejl, {advarsler} advarsler{suffix}.\n")
    else:
        print(f"❌ {fejl} fejl, {advarsler} advarsler — ret fejlene før du genererer.\n")


# ── Schema-generering (JSON Schema for editor-validering) ────────────────────────

def opdater_schema_plante_ids(plante_db: dict) -> None:
    """Skriv alle kendte plante_id'er som enum ind i bed.schema.json."""
    import json
    schema_sti = PROJECT_ROOT / "schema" / "bed.schema.json"
    if not schema_sti.exists():
        return
    schema = json.loads(schema_sti.read_text(encoding="utf-8"))
    ids = sorted(plante_db.keys())
    enum_felt = ids + [None]
    for def_navn in ("Zone", "Afgrøde"):
        felt = schema.get("$defs", {}).get(def_navn, {}).get("properties", {}).get("plante_id")
        if felt is not None:
            felt["enum"] = enum_felt
    ny = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    if skriv_hvis_ændret(schema_sti, ny):
        print(f"✅ Schema opdateret med {len(ids)} plante-ID'er: {schema_sti.name}")
    else:
        print(f"ℹ️  Schema uændret: {schema_sti.name}")


def opdater_schema_planter() -> None:
    """Regenerer planter.schema.json fra Plante-modellen."""
    import json
    from haven.models import Plante
    schema_sti = PROJECT_ROOT / "schema" / "planter.schema.json"
    if not schema_sti.exists():
        return
    ny = json.dumps(Plante.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    if skriv_hvis_ændret(schema_sti, ny):
        print(f"✅ Schema regenereret fra Plante-modellen: {schema_sti.name}")
    else:
        print(f"ℹ️  Schema uændret: {schema_sti.name}")
