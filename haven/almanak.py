"""haven.almanak — fletning af almanakdata, vejr-SVG'er og samlet almanakside.

Render-lag i cli-opdelingen (se briefs/cli-opdeling.md, fase 4). generer_samlet_almanak
bruges af orkestratoren; flet_almanakker/generer_måned_svg er dens hjælpere.
Afhænger af kontekst (ENTRIES_FIL, YAML_FILER_DEFAULT, PLANTE_DB, ALMANAK_FIL,
PLANTER_FIL, AKTIVT_ÅR, MÅNEDER, MÅNEDER_LANG) + indlaes (load_yaml,
_les_entries_mappe, skriv_hvis_ændret).
"""

import datetime
import os
from pathlib import Path

from .kontekst import (
    ENTRIES_FIL, YAML_FILER_DEFAULT, PLANTE_DB, ALMANAK_FIL, PLANTER_FIL,
    AKTIVT_ÅR, MÅNEDER, MÅNEDER_LANG,
)
from .indlaes import load_yaml, _les_entries_mappe, skriv_hvis_ændret

__all__ = ["flet_almanakker", "generer_måned_svg", "generer_samlet_almanak"]


def flet_almanakker(projekter_data, entries_fil=None):
    """
    Fletter måneder fra alle almanakfiler.
    Returnerer liste af 12 måneder med blandede entries og begivenheder.
    """
    _entries_fil = Path(entries_fil) if entries_fil else ENTRIES_FIL
    MÅNED_NAVNE = ["Januar","Februar","Marts","April","Maj","Juni",
                   "Juli","August","September","Oktober","November","December"]

    # Byg 12 tomme måneder
    måneder = [{"måned": i+1, "navn": MÅNED_NAVNE[i],
                "indledninger": [], "begivenheder": [], "entries": []}
               for i in range(12)]

    # Byg opslagsdict: html_navn -> titel
    # Indlæs fra meta.html_navn i bed-YAML'erne — filnavnet matcher ikke nødvendigvis html_navn
    # (fx har højbedshaven.yaml html_navn="hoejbede")
    område_titler: dict[str, str] = {}
    for yaml_sti in YAML_FILER_DEFAULT:
        if os.path.exists(yaml_sti):
            meta = load_yaml(yaml_sti).get("meta", {})
            hn = meta.get("html_navn")
            if hn:
                område_titler[hn] = meta.get("titel", hn)

    for html_navn, alm_data in projekter_data:
        # Kilde-css-klasse baseret på html_navn
        css_kilde = f"kilde-{html_navn.replace('_','-')}"
        # Brug YAML-titlen (samme kilde som entries) så kilde-labels er konsistente
        # på tværs af indledninger, begivenheder og entries for samme område.
        titel = område_titler.get(html_navn, html_navn)

        for mån in alm_data.get("måneder", []):
            mnr = mån.get("måned")
            if not (isinstance(mnr, int) and 1 <= mnr <= 12):
                continue
            idx = mnr - 1

            # Indledninger filtreret på dette område
            for ind in (mån.get("indledninger") or []):
                if ind.get("område_id") == html_navn:
                    måneder[idx]["indledninger"].append((titel, ind["tekst"]))

            # Begivenheder filtreret på dette område
            for b in (mån.get("begivenheder") or []):
                if b.get("område_id") == html_navn:
                    måneder[idx]["begivenheder"].append({
                        "tekst": b["tekst"],
                        "kilde": titel,
                        "css":   css_kilde,
                    })

            # Entries filtreret på dette område
            # Entries hentes fra entries.yaml

    # Indlæs entries fra entries.yaml og fordel på måneder og område
    if os.path.exists(_entries_fil):
        entries_data = load_yaml(_entries_fil)
        for e in (entries_data.get("entries") or []):
            oid = e.get("område_id", "")
            if hasattr(e.get("dato"), "isoformat"):
                e["dato"] = e["dato"].isoformat()
            try:
                måned_nr = int(str(e["dato"]).split("-")[1])
            except (KeyError, IndexError, ValueError):
                continue
            if not 1 <= måned_nr <= 12:
                continue  # ugyldig måned i dato — undgå at placere i forkert/sidste måned
            e_kopi = dict(e)
            e_kopi["kilde"]     = område_titler.get(oid, oid)
            e_kopi["css_kilde"] = f"kilde-{oid.replace('_','-')}"
            # Normaliser plante_id og berig med plantenavne
            pid = e_kopi.get("plante_id")
            if pid is None:
                e_kopi["plante_id"] = []
            elif isinstance(pid, str):
                e_kopi["plante_id"] = [pid] if pid else []
            else:
                e_kopi["plante_id"] = list(pid)
            e_kopi["plante_navne"] = [PLANTE_DB.get(p, {}).get("navn", p)
                                      for p in e_kopi["plante_id"] if p]
            måneder[måned_nr - 1]["entries"].append(e_kopi)

    # Indlæs entries fra markdown-mappe
    entries_mappe_md = Path(_entries_fil).parent / "entries" / "sektioner"
    for e in _les_entries_mappe(str(entries_mappe_md)):
        oid = e.get("zone") or e.get("område_id", "")
        if hasattr(e.get("dato"), "isoformat"):
            e["dato"] = e["dato"].isoformat()
        try:
            måned_nr = int(str(e["dato"]).split("-")[1])
        except (KeyError, IndexError, ValueError):
            continue
        if not 1 <= måned_nr <= 12:
            continue  # ugyldig måned i dato — undgå at placere i forkert/sidste måned
        e_kopi = dict(e)
        e_kopi.setdefault("titel", "")
        e_kopi["kilde"]     = område_titler.get(oid, oid)
        e_kopi["css_kilde"] = f"kilde-{oid.replace('_','-')}"
        # plante_id er allerede normaliseret til liste af _les_entries_mappe
        e_kopi["plante_navne"] = [PLANTE_DB.get(p, {}).get("navn", p)
                                  for p in e_kopi.get("plante_id", []) if p]
        måneder[måned_nr - 1]["entries"].append(e_kopi)

    # Sortér entries inden for hver måned (stigende dato)
    for mån in måneder:
        mån["entries"].sort(key=lambda e: str(e["dato"]))

    return måneder


def generer_måned_svg(måned_data: dict) -> "dict | None":
    """Generer tre SVG-grafer for én måneds daglige vejrdata."""
    daglige = måned_data.get("daglige") if måned_data else None
    if not daglige:
        return None

    d_middel = list(daglige.get("middel") or [])
    d_min    = list(daglige.get("min")    or [])
    d_ned    = list(daglige.get("nedbør") or [])
    n = len(d_middel)
    if not n:
        return None

    W, H   = 400, 80
    ML, MR = 28, 4
    PT, PB = 6, 14
    DW = W - ML - MR
    DH = H - PT - PB
    col = DW / n

    def xd(i):
        return round(ML + (i + 0.5) * col, 2)

    dag_lbl_idx = sorted({0, 4, 9, 14, 19, 24, n - 1})

    def lbl_y(x, y, txt):
        return (f'<text x="{x}" y="{y}" font-size="6.5" fill="#aaa" '
                f'text-anchor="end" font-family="sans-serif">{txt}</text>')

    def lbl_x(x, y, txt):
        return (f'<text x="{x}" y="{y}" font-size="6.5" fill="#ccc" '
                f'text-anchor="middle" font-family="sans-serif">{txt}</text>')

    def hgrid(y, stroke, da=None):
        d = f' stroke-dasharray="{da}"' if da else ""
        return (f'<line x1="{ML}" y1="{y}" x2="{W - MR}" y2="{y}" '
                f'stroke="{stroke}" stroke-width="0.5"{d}/>')

    # ── Temperaturlinje (deles af middel og min) ──────────────────────────────
    T_MIN, T_MAX = -15, 30

    def yt(t):
        return round(PT + (T_MAX - t) / (T_MAX - T_MIN) * DH, 2)

    def temp_svg(vals, c_pos, c_neg):
        els = []
        for gv, stroke, da in [
            (-5, "#e8e8e8", "2,3"), (0, "#bbb", "3,2"),
            (5, "#e8e8e8", "2,3"),  (10, "#e8e8e8", "2,3"),
            (15, "#e8e8e8", "2,3"), (20, "#e8e8e8", "2,3"),
        ]:
            yg = yt(gv)
            els.append(hgrid(yg, stroke, da))
            els.append(lbl_y(ML - 2, round(yg + 2.5, 2), f"{gv}°"))
        for i in dag_lbl_idx:
            if i < n:
                els.append(lbl_x(xd(i), H - 2, str(i + 1)))
        y0 = yt(0)
        # Brug vals' egen længde — min/middel-arrays kan have forskellig længde
        for i in range(len(vals) - 1):
            v1, v2 = vals[i], vals[i + 1]
            if v1 is None or v2 is None:
                continue
            x1, x2 = xd(i), xd(i + 1)
            y1, y2 = yt(v1), yt(v2)
            if (v1 >= 0) == (v2 >= 0):
                c = c_pos if v1 >= 0 else c_neg
                els.append(
                    f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                    f'stroke="{c}" stroke-width="1.0" stroke-linecap="round"/>'
                )
            else:
                ratio = v1 / (v1 - v2)
                xc = round(x1 + ratio * (x2 - x1), 2)
                c1, c2 = (c_pos, c_neg) if v1 >= 0 else (c_neg, c_pos)
                els.append(
                    f'<line x1="{x1}" y1="{y1}" x2="{xc}" y2="{y0}" '
                    f'stroke="{c1}" stroke-width="1.0" stroke-linecap="round"/>'
                    f'<line x1="{xc}" y1="{y0}" x2="{x2}" y2="{y2}" '
                    f'stroke="{c2}" stroke-width="1.0" stroke-linecap="round"/>'
                )
        return (
            f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
            + "".join(els) + "</svg>"
        )

    # ── Nedbør ────────────────────────────────────────────────────────────────
    N_MAX  = 20
    y_bot  = PT + DH
    bw     = max(round(col * 0.72, 2), 0.8)

    def yn(v):
        return round(PT + (N_MAX - min(v, N_MAX)) / N_MAX * DH, 2)

    ned_els = []
    for gv in [5, 10]:
        yg = yn(gv)
        ned_els.append(hgrid(yg, "#e8e8e8", "2,3"))
        ned_els.append(lbl_y(ML - 2, round(yg + 2.5, 2), str(gv)))
    ned_els.append(lbl_y(ML - 2, y_bot, "0"))
    ned_els.append(hgrid(y_bot, "#ddd"))
    for i in dag_lbl_idx:
        if i < len(d_ned):
            ned_els.append(lbl_x(xd(i), H - 2, str(i + 1)))
    for i, nv in enumerate(d_ned):
        if not nv or nv <= 0:
            continue
        bh = round(min(nv, N_MAX) / N_MAX * DH, 2)
        bx = round(xd(i) - bw / 2, 2)
        ned_els.append(
            f'<rect x="{bx}" y="{round(y_bot - bh, 2)}" '
            f'width="{bw}" height="{bh}" fill="#90aec9" rx="0.5"/>'
        )

    ned_svg = (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        + "".join(ned_els) + "</svg>"
    )

    return {
        "temperatur_linje": temp_svg(d_middel, "#4a7c59", "#5b8dd9"),
        "min_linje":        temp_svg(d_min,    "#7aadce", "#1e3a8a"),
        "nedbør_søjler":    ned_svg,
    }


def generer_samlet_almanak(projekter_yaml, almanak_sti, env, alle_planter=None, nav_context=None,
                           almanak_fil=None, entries_fil=None, år=None):
    """Generer én samlet almanakside fra alle projekters almanakfiler."""
    _almanak_fil = Path(almanak_fil) if almanak_fil else ALMANAK_FIL
    if alle_planter is None:
        pd = load_yaml(PLANTER_FIL)
        alle_planter = pd if isinstance(pd, list) else pd.get("planter", [])
    # Indlæs samlet almanak.yaml og opdel per område
    yaml_filer = projekter_yaml
    år_fra_yaml = None
    projekter_data = []
    temperatur_dict = {}
    if os.path.exists(_almanak_fil):
        alm = load_yaml(_almanak_fil)
        år_fra_yaml = alm.get("meta", {}).get("år")
        temperatur_dict = alm.get("temperatur", {})
        # Find alle unikke område_id'er i filen
        område_ids = set()
        for m in alm.get("måneder", []):
            for ind in m.get("indledninger", []):
                område_ids.add(ind["område_id"])
            for b in m.get("begivenheder", []):
                område_ids.add(b["område_id"])
            for e in (m.get("entries") or []):
                område_ids.add(e.get("område_id",""))
        projekter_data = [(oid, alm) for oid in sorted(område_ids) if oid]

    if not projekter_data:
        return

    år = år_fra_yaml or år or AKTIVT_ÅR
    måneder  = flet_almanakker(projekter_data, entries_fil=entries_fil)
    for mån in måneder:
        mån["vejr"] = generer_måned_svg(temperatur_dict.get(MÅNEDER_LANG[mån["måned"] - 1], {}))
    # Alle planter sorteret alfabetisk til samlet kalender
    alle_planter_sorteret = sorted(alle_planter, key=lambda p: p["navn"])

    # Byg opslagsdict: titel → ikon fra bed-YAML meta-blokke (ikke hårdkodet)
    område_ikoner = {}
    for yaml_sti in yaml_filer:
        if os.path.exists(yaml_sti):
            meta  = load_yaml(yaml_sti).get("meta", {})
            titel = meta.get("titel", "")
            ikon  = meta.get("ikon", "🌿")
            if titel:
                område_ikoner[titel] = ikon
    env.filters["område_ikon"] = lambda kilde: område_ikoner.get(kilde, "🌿")

    skabelon = env.get_template("almanak.html")
    output   = skabelon.render(år=år, måneder=måneder,
                               alle_planter=alle_planter_sorteret,
                               måneds_navne=MÅNEDER,
                               aktuel_måned=datetime.date.today().month,
                               **(nav_context or {}))

    if skriv_hvis_ændret(almanak_sti, output):
        print(f"✅ Samlet almanak genereret: {almanak_sti}")
    else:
        print(f"ℹ️  Samlet almanak uændret: {almanak_sti}")
