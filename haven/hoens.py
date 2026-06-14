"""haven.hoens — hønse-/husdyrregister: entries, beriget visning, HTML + ICS.

Render-lag i cli-opdelingen (se briefs/cli-opdeling.md, fase 4). generer_hons_html/
generer_hons_ics bruges af orkestratoren; _markér_dyr_inaktiv af wizards (fase 5).
Afhænger af kontekst (HONS_TYPER, DYR_DB, DATA_MAPPE, AKTIVT_ÅR, DYR_FIL) +
indlaes (load_yaml, _dyr_label, skriv_hvis_ændret).
"""

import datetime
import os
from pathlib import Path

from .kontekst import HONS_TYPER, DYR_DB, DATA_MAPPE, AKTIVT_ÅR, DYR_FIL, MÅNEDER, MÅNEDER_LANG
from .indlaes import load_yaml, _dyr_label, skriv_hvis_ændret

__all__ = ["generer_hons_html", "generer_hons_ics", "_markér_dyr_inaktiv"]


def _les_hons_entries(mappe) -> list:
    """Læs hønse-entries (én YAML-fil pr. entry) fra entries/{zone}/-mappen."""
    entries = []
    if not os.path.isdir(mappe):
        return entries
    for fil in sorted(os.listdir(mappe)):
        if not (fil.endswith(".yaml") or fil.endswith(".yml")):
            continue
        e = load_yaml(os.path.join(mappe, fil))
        if not isinstance(e, dict):
            continue
        e = dict(e)
        for nøgle in ("dato", "forventet_klæk"):
            if hasattr(e.get(nøgle), "isoformat"):
                e[nøgle] = e[nøgle].isoformat()
        # Normaliser foto: string → {fil, tekst} som skabelonen forventer (jf. dagbog)
        if "foto" in e and isinstance(e["foto"], str):
            e["foto"] = {"fil": os.path.basename(e["foto"]), "tekst": ""}
        e["_fil"] = Path(fil).stem
        entries.append(e)
    return entries


def _hons_resume(e: dict) -> str:
    """Byg en kort, menneskelæselig opsummering af en hønse-entry til loggen."""
    t = e.get("type", "")
    dele: list = []
    if t == "note":
        return e.get("høne_label") or ""
    if t == "æglægning":
        return f"{e.get('æg', 0)} æg"
    if t == "ruge-start":
        if e.get("høne_label"):
            dele.append(e["høne_label"])
        if e.get("æg_antal") is not None:
            dele.append(f"{e['æg_antal']} æg lagt til rugning")
        if e.get("forventet_klæk"):
            dele.append(f"forventet klæk {e['forventet_klæk']}")
    elif t == "foderkøb":
        if e.get("foder_type"):
            dele.append(str(e["foder_type"]))
        if e.get("mængde_kg") is not None:
            dele.append(f"{e['mængde_kg']} kg")
        if e.get("pris") is not None:
            dele.append(f"{e['pris']} kr")
        if e.get("butik"):
            dele.append(str(e["butik"]))
    elif t == "sundhedsobs":
        if e.get("høne_label"):
            dele.append(e["høne_label"])
        else:
            dele.append("hele flokken")
        if e.get("observation"):
            dele.append(str(e["observation"]))
        if e.get("handling"):
            dele.append(f"→ {e['handling']}")
    elif t == "dødsfald":
        if e.get("høne_label"):
            dele.append(e["høne_label"])
        if e.get("årsag"):
            dele.append(f"årsag: {e['årsag']}")
    elif t == "fjerfældning":
        fase = e.get("fase", "")
        return f"fældning ({fase})" if fase else "fældning"
    return " · ".join(dele)


def _berig_hons_entry(e: dict) -> dict:
    """Berig en entry med ikon, type-label, opslået høne-navn og resumé."""
    e = dict(e)
    t = e.get("type", "")
    cfg = HONS_TYPER.get(t, {"ikon": "📝", "label": t or "Note"})
    e["ikon"] = cfg["ikon"]
    e["type_label"] = cfg["label"]
    hid = e.get("høne")
    e["høne_label"] = _dyr_label(DYR_DB[hid]) if hid in DYR_DB else (hid or "")
    e["resume"] = _hons_resume(e)
    return e


def _søjle_svg(data: "list[tuple[str, int]]", vis_antal: bool = True) -> str:
    """Tegn en inline SVG-søjlegraf af (label, antal)-par.

    Hver søjle får sit label nederst, og — når vis_antal er sat — antallet skrevet
    som tal lige under søjlen (over labelet). Output er deterministisk.
    """
    if not data:
        return ""

    W, H    = 400, 100
    ML, MR  = 32, 6
    PT, PB  = 8, 26                 # ekstra bundplads til to tekstlinjer (antal + label)
    DW = W - ML - MR
    DH = H - PT - PB
    y_bot = PT + DH

    max_val = max((a for _, a in data), default=1) or 1

    def nice_step(v):
        for s in (1, 2, 5, 10, 20, 50, 100):
            if v <= s * 4:
                return s
        return 50

    y_step = nice_step(max_val)
    y_max  = max(y_step, ((max_val + y_step - 1) // y_step) * y_step)

    def yv(v):
        return round(PT + (y_max - v) / y_max * DH, 2)

    n   = len(data)
    col = DW / max(n, 1)
    bw  = max(round(col * 0.65, 2), 1.0)

    def xc(i):
        return round(ML + (i + 0.5) * col, 2)

    els: list[str] = []

    # Basislinje + gitterlinjer
    els.append(f'<line x1="{ML}" y1="{y_bot}" x2="{W - MR}" y2="{y_bot}" '
               f'stroke="#ccc" stroke-width="0.5"/>')
    gv = y_step
    while gv <= y_max:
        yg = yv(gv)
        els.append(f'<line x1="{ML}" y1="{yg}" x2="{W - MR}" y2="{yg}" '
                   f'stroke="#e8e8e8" stroke-width="0.5" stroke-dasharray="2,3"/>')
        els.append(f'<text x="{ML - 3}" y="{round(yg + 2.5, 2)}" font-size="6.5" '
                   f'fill="#aaa" text-anchor="end" font-family="sans-serif">{gv}</text>')
        gv += y_step
    els.append(f'<text x="{ML - 3}" y="{y_bot}" font-size="6.5" '
               f'fill="#aaa" text-anchor="end" font-family="sans-serif">0</text>')

    # X-akse-labels (alle — antallet af søjler holdes lavt) + antal under søjlen
    for i, (label, antal) in enumerate(data):
        els.append(f'<text x="{xc(i)}" y="{H - 2}" font-size="6.5" '
                   f'fill="#aaa" text-anchor="middle" '
                   f'font-family="sans-serif">{label}</text>')
        if vis_antal and antal > 0:
            els.append(f'<text x="{xc(i)}" y="{round(y_bot + 9, 2)}" font-size="6.5" '
                       f'fill="#7b5c0d" text-anchor="middle" font-weight="600" '
                       f'font-family="sans-serif">{antal}</text>')

    # Søjler
    for i, (_, antal) in enumerate(data):
        if antal <= 0:
            continue
        bh = round(antal / y_max * DH, 2)
        bx = round(xc(i) - bw / 2, 2)
        els.append(f'<rect x="{bx}" y="{round(y_bot - bh, 2)}" '
                   f'width="{bw}" height="{bh}" fill="#e8b84b" rx="0.8"/>')

    return (f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
            f'aria-hidden="true">' + "".join(els) + "</svg>")


def _æg_oversigt(entries: list, aktive_høner: int = 0) -> "dict | None":
    """Saml æglægnings-entries til nøgletal + søjlegrafer.

    Returnerer et samlet årsdiagram (én søjle pr. måned) plus en liste af måneder,
    hver med sit eget uge-diagram, så skabelonen kan folde dem ud enkeltvis.
    Returnerer None hvis ingen æglægning er registreret.
    Output er deterministisk — ingen wall-clock, ingen 'i dag'-markør.
    """
    aegl = [e for e in entries if e.get("type") == "æglægning"]
    if not aegl:
        return None

    uger: dict = {}                 # (iso_år, iso_uge) -> total æg (hele året, til snit)
    måned_total: dict = {}          # (år, måned) -> total æg
    måned_uger: dict = {}           # (år, måned) -> {iso_uge -> antal}
    bedste_dato = ""
    bedste_antal = 0
    total = 0

    for e in aegl:
        try:
            dato = datetime.date.fromisoformat(str(e.get("dato", "")))
        except ValueError:
            continue
        antal = int(e.get("æg", 0) or 0)
        total += antal
        if antal > bedste_antal:
            bedste_antal = antal
            bedste_dato  = str(e.get("dato", ""))
        iso = dato.isocalendar()
        uger[(iso[0], iso[1])] = uger.get((iso[0], iso[1]), 0) + antal
        mk = (dato.year, dato.month)
        måned_total[mk] = måned_total.get(mk, 0) + antal
        måned_uger.setdefault(mk, {})
        måned_uger[mk][iso[1]] = måned_uger[mk].get(iso[1], 0) + antal

    if not uger:
        return None

    antal_uger = len(uger)
    snit = round(total / antal_uger, 1) if antal_uger else 0

    # ── Årsdiagram: kontinuerligt måneds-spænd (huller udfyldes med 0) ──────────
    mk_alle = sorted(måned_total)
    (start_år, start_md), (slut_år, slut_md) = mk_alle[0], mk_alle[-1]
    år_data: list[tuple[str, int]] = []
    cur = (start_år, start_md)
    while cur <= (slut_år, slut_md):
        år_data.append((MÅNEDER[cur[1] - 1], måned_total.get(cur, 0)))
        cur = (cur[0] + 1, 1) if cur[1] == 12 else (cur[0], cur[1] + 1)

    # ── Pr. måned: uge-diagram (kun måneder med æg) ─────────────────────────────
    måneder: list[dict] = []
    for mk in mk_alle:
        if måned_total[mk] <= 0:
            continue
        u = måned_uger[mk]
        u_min, u_max = min(u), max(u)
        # Fyld kun huller ud ved et sammenhængende uge-spænd (undgå år-skifte-wrap)
        if u_max - u_min <= 6:
            uge_data = [(f"U{w}", u.get(w, 0)) for w in range(u_min, u_max + 1)]
        else:
            uge_data = [(f"U{w}", u[w]) for w in sorted(u)]
        måneder.append({
            "måned": mk[1],
            "navn":  MÅNEDER_LANG[mk[1] - 1].capitalize(),
            "total": måned_total[mk],
            "svg":   _søjle_svg(uge_data),
        })

    resultat: dict = {
        "total":        total,
        "antal_uger":   antal_uger,
        "snit_pr_uge":  snit,
        "bedste_dato":  bedste_dato,
        "bedste_antal": bedste_antal,
        "år_svg":       _søjle_svg(år_data),
        "måneder":      måneder,
    }
    if aktive_høner > 0 and antal_uger:
        resultat["æg_pr_høne_pr_uge"] = round(total / (aktive_høner * antal_uger), 2)
    return resultat


def generer_hons_html(yaml_sti, html_sti, env, nav_context=None, data_mappe_sti=None):
    """Generer en husdyr-zoneside (hønsehus): register + observationslog.

    Returnerer de berigede entries, så kalderen kan genbruge dem til ICS-generering.
    """
    _data_mappe = Path(data_mappe_sti) if data_mappe_sti else DATA_MAPPE
    data = load_yaml(yaml_sti)
    meta = data.get("meta", {})
    html_navn = meta.get("html_navn", Path(yaml_sti).stem)
    # zone-typer: 'husdyr' aktiverer alternativ template og wizard-sæt.
    # Zoner uden 'type' behandles som plantezoner (eksisterende opførsel).
    zone_type = meta.get("type", "plante")

    # Høne-register: aktive først, derefter race/farve
    dyr = sorted(
        DYR_DB.values(),
        key=lambda d: (not d.get("aktiv", True), str(d.get("race", "")), str(d.get("farve", ""))),
    )

    # Observationslog: nyeste øverst
    entries_mappe = os.path.join(_data_mappe, "entries", html_navn)
    entries = [_berig_hons_entry(e) for e in _les_hons_entries(entries_mappe)]
    entries.sort(key=lambda e: str(e.get("dato", "")), reverse=True)

    har_ics = any(e.get("type") == "ruge-start" and e.get("forventet_klæk") for e in entries)
    aktive  = sum(1 for d in dyr if d.get("aktiv", True))
    æg_data = _æg_oversigt(entries, aktive)

    skabelon = env.get_template("hons.html")
    output = skabelon.render(
        titel        = meta.get("titel", "Hønsehuset"),
        år           = meta.get("år", AKTIVT_ÅR),
        ikon         = meta.get("ikon", "🐔"),
        ikon_billede = meta.get("ikon_billede", ""),
        undertitel   = meta.get("undertitel", ""),
        beskrivelse  = meta.get("beskrivelse", ""),
        zone_type    = zone_type,
        dyr          = dyr,
        entries      = entries,
        har_ics      = har_ics,
        ics_fil      = f"{html_navn}-{AKTIVT_ÅR}.ics",
        æg_data      = æg_data,
        aktuel_måned = datetime.date.today().month,
        **(nav_context or {}),
    )
    if skriv_hvis_ændret(html_sti, output):
        print(f"✅ HTML genereret: {html_sti}")
    else:
        print(f"ℹ️  HTML uændret: {html_sti}")
    return entries


def generer_hons_ics(entries, ics_sti, år) -> bool:
    """Generer en ICS-kalender med forventede klækninger fra ruge-start-entries.

    Returnerer True hvis filen blev skrevet (mindst én klække-event), ellers False.
    """
    def ics_escape(s):
        s = str(s).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
        s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "")
        return s.strip()

    def ics_fold(line):
        chunks = []
        while True:
            if len(line.encode("utf-8")) <= 75:
                chunks.append(line)
                break
            n = 75
            while len(line[:n].encode("utf-8")) > 75:
                n -= 1
            chunks.append(line[:n])
            line = " " + line[n:]
        return "\r\n".join(chunks)

    now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    vevents = []
    for e in entries:
        if e.get("type") != "ruge-start" or not e.get("forventet_klæk"):
            continue
        try:
            d = datetime.date.fromisoformat(str(e["forventet_klæk"]))
        except ValueError:
            continue
        dato_start = d.strftime("%Y%m%d")
        dato_end   = (d + datetime.timedelta(days=1)).strftime("%Y%m%d")
        høne = e.get("høne_label") or _dyr_label(DYR_DB.get(e.get("høne"), {})) or "?"
        antal = e.get("æg_antal", "?")
        lagt = e.get("dato", "")
        description = ics_escape(f"{høne} — {antal} æg lagt {lagt}")
        uid = f"hons-klaek-{dato_start}-{e.get('_fil', '')}@have.py"
        vevents.append("\r\n".join([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_ts}",
            f"DTSTART;VALUE=DATE:{dato_start}",
            f"DTEND;VALUE=DATE:{dato_end}",
            ics_fold(f"SUMMARY:{ics_escape('🐣 Forventet klækning')}"),
            ics_fold(f"DESCRIPTION:{description}"),
            "END:VEVENT",
        ]))

    if not vevents:
        return False

    header = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//have.py//Hønsekalender//DA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Hønsehuset {år}",
    ])
    indhold = header + "\r\n" + "\r\n".join(vevents) + "\r\nEND:VCALENDAR\r\n"
    with open(ics_sti, "w", encoding="utf-8", newline="") as f:
        f.write(indhold)
    print(f"✅ Høns-ICS genereret: {ics_sti} ({len(vevents)} klækninger)")
    return True


def _markér_dyr_inaktiv(høne_id: str) -> None:
    """Sæt aktiv: false på en høne i dyr.yaml (bevarer struktur via ruamel)."""
    from ruamel.yaml import YAML as RuamelYAML
    ry = RuamelYAML()
    ry.preserve_quotes = True
    ry.width = 120
    if not os.path.exists(DYR_FIL):
        return
    with open(DYR_FIL, encoding="utf-8") as f:
        data = ry.load(f)
    dyr = data.get("dyr") if isinstance(data, dict) else data
    for d in (dyr or []):
        if d.get("id") == høne_id:
            d["aktiv"] = False
            with open(DYR_FIL, "w", encoding="utf-8") as f:
                ry.dump(data, f)
            print(f"  ✓ {høne_id} markeret som udgået (aktiv: false) i dyr.yaml")
            return
