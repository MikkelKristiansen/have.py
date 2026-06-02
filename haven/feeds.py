"""haven.feeds — iCal- og RSS-generering fra almanak/entries.

Render-lag i cli-opdelingen (se briefs/cli-opdeling.md, fase 4). Afhænger kun af
indlaes (load_yaml) + stdlib. De interne helpers (_xml_escape, _rfc2822,
_rss_kanal_header) bruges kun her i modulet.
"""

import datetime
import os

from .indlaes import load_yaml

__all__ = ["generer_ics", "generer_rss_dagbog", "generer_rss_almanak"]


def generer_ics(almanak_sti, ics_sti, år, yaml_filer=None):
    """Generer en ICS-kalender fra almanak.yaml — én VEVENT pr. måned."""
    alm    = load_yaml(almanak_sti)
    now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Byg opslagsdict: område_id → {ikon, titel} fra bed-YAML meta-blokke
    område_meta = {}
    for yaml_sti in (yaml_filer or []):
        if not os.path.exists(yaml_sti):
            continue
        data = load_yaml(yaml_sti)
        meta = data.get("meta", {})
        oid  = meta.get("html_navn", "")
        if oid:
            område_meta[oid] = {
                "ikon":  meta.get("ikon", "🌿"),
                "titel": meta.get("titel", oid),
            }

    def ics_escape(s):
        """Escape ICS special chars; newlines → \\n (literal)."""
        s = s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
        s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "")
        return s.strip()

    def ics_fold(line):
        """Fold long lines per RFC 5545 (max 75 octets, continuation with SP)."""
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

    vevents = []
    for mån in alm.get("måneder", []):
        måned_nr = mån.get("måned")
        if not (isinstance(måned_nr, int) and 1 <= måned_nr <= 12):
            continue  # ugyldigt/manglende månedsnummer — spring over
        måned_navn = mån.get("navn", f"Måned {måned_nr}")
        dato_start = f"{år}{måned_nr:02d}01"
        dato_end   = (datetime.date(år, måned_nr, 1) + datetime.timedelta(days=1)).strftime("%Y%m%d")

        # Gruppér begivenheder pr. område (bevar rækkefølge)
        område_bev: dict = {}
        for bev in mån.get("begivenheder", []):
            tekst = str(bev.get("tekst") or "").strip()
            oid   = bev.get("område_id", "")
            if not tekst or not oid:
                continue
            første_linje = tekst.splitlines()[0].strip()
            if første_linje:
                område_bev.setdefault(oid, []).append(første_linje)

        if not område_bev:
            continue  # Måneden har ingen begivenheder — spring over

        # Byg DESCRIPTION: ikon+titel som overskrift, begivenheder med •
        desc_dele = []
        for oid, bevs in område_bev.items():
            om    = område_meta.get(oid, {"ikon": "🌿", "titel": oid})
            ovs   = ics_escape(f"{om['ikon']} {om['titel']}")
            punkt = "\\n• ".join(ics_escape(b) for b in bevs)
            desc_dele.append(f"{ovs}\\n• {punkt}")
        description = "\\n\\n".join(desc_dele)

        summary = f"\U0001f33f Haven — {måned_navn} {år}"
        uid     = f"{år}-{måned_nr:02d}@have.py"

        vevents.append("\r\n".join([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_ts}",
            f"DTSTART;VALUE=DATE:{dato_start}",
            f"DTEND;VALUE=DATE:{dato_end}",
            ics_fold(f"SUMMARY:{summary}"),
            ics_fold(f"DESCRIPTION:{description}"),
            "END:VEVENT",
        ]))

    header  = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//have.py//Havealmanak//DA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Havealmanak {år}",
    ])
    indhold = header + "\r\n" + "\r\n".join(vevents) + "\r\nEND:VCALENDAR\r\n"

    with open(ics_sti, "w", encoding="utf-8", newline="") as f:
        f.write(indhold)
    print(f"✅ ICS-kalender genereret: {ics_sti} ({len(vevents)} måneder)")


# ── RSS ────────────────────────────────────────────────────────────────────────

_RFC_DAGE  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_RFC_MÅNDR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _xml_escape(s):
    """Escape XML special chars i tekst-indhold."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rfc2822(dato):
    """Formater dato som RFC 2822-streng til brug i RSS pubDate/lastBuildDate."""
    d = dato if hasattr(dato, "year") else datetime.date.fromisoformat(str(dato))
    return (f"{_RFC_DAGE[d.weekday()]}, {d.day:02d} "
            f"{_RFC_MÅNDR[d.month - 1]} {d.year} 00:00:00 +0000")


def _rss_kanal_header(år, base_url):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        '  <channel>\n'
        f'    <title>Haven {år}</title>\n'
        f'    <link>{base_url}/{år}/</link>\n'
        '    <description>Havens dagbog og almanak</description>\n'
        '    <language>da</language>\n'
        f'    <lastBuildDate>{_rfc2822(datetime.date.today())}</lastBuildDate>\n'
    )


def generer_rss_dagbog(entries_sti, rss_sti, år, base_url):
    """Generer have-dagbog.rss — ét <item> pr. entry, nyeste først."""
    data    = load_yaml(entries_sti)
    entries = sorted(
        [e for e in (data.get("entries") or [])
         if e.get("dato") and e.get("titel")],
        key=lambda e: str(e["dato"]),
        reverse=True,
    )

    items = []
    for e in entries:
        dato_str = str(e["dato"])
        oid      = e.get("område_id", "")
        titel    = _xml_escape(e.get("titel", ""))
        tekst    = _xml_escape(str(e.get("tekst", "")).strip())
        pub_date = _rfc2822(e["dato"])
        guid     = f"{base_url}/{år}/have-dagbog.rss#{oid}-{dato_str}"
        items.append(
            "    <item>\n"
            f"      <title>{titel}</title>\n"
            f"      <description>{tekst}</description>\n"
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"      <category>{_xml_escape(oid)}</category>\n"
            f"      <guid isPermaLink=\"false\">{_xml_escape(guid)}</guid>\n"
            "    </item>"
        )

    indhold = (_rss_kanal_header(år, base_url)
               + "\n".join(items) + "\n"
               + "  </channel>\n</rss>\n")
    with open(rss_sti, "w", encoding="utf-8") as f:
        f.write(indhold)
    print(f"✅ RSS dagbog genereret: {rss_sti} ({len(entries)} entries)")


def generer_rss_almanak(almanak_sti, rss_sti, år, base_url, yaml_filer=None):
    """Generer have-almanak.rss — ét <item> pr. måned med begivenheder."""
    alm = load_yaml(almanak_sti)

    # Byg opslagsdict: område_id → {ikon, titel}
    område_meta = {}
    for yaml_sti in (yaml_filer or []):
        if not os.path.exists(yaml_sti):
            continue
        meta = load_yaml(yaml_sti).get("meta", {})
        oid  = meta.get("html_navn", "")
        if oid:
            område_meta[oid] = {
                "ikon":  meta.get("ikon", "🌿"),
                "titel": meta.get("titel", oid),
            }

    items = []
    for mån in alm.get("måneder", []):
        måned_nr = mån.get("måned")
        if not (isinstance(måned_nr, int) and 1 <= måned_nr <= 12):
            continue  # ugyldigt/manglende månedsnummer — spring over
        måned_navn = mån.get("navn", f"Måned {måned_nr}")

        # Gruppér begivenheder pr. område
        område_bev: dict = {}
        for bev in mån.get("begivenheder", []):
            tekst = str(bev.get("tekst") or "").strip()
            oid   = bev.get("område_id", "")
            if not tekst or not oid:
                continue
            første = tekst.splitlines()[0].strip()
            if første:
                område_bev.setdefault(oid, []).append(første)

        if not område_bev:
            continue

        # Byg description: ikon+titel som overskrift, begivenheder med •
        desc_dele = []
        for oid, bevs in område_bev.items():
            om    = område_meta.get(oid, {"ikon": "🌿", "titel": oid})
            ovs   = f"{om['ikon']} {om['titel']}"
            punkt = "\n• ".join(bevs)
            desc_dele.append(f"{ovs}\n• {punkt}")
        description = _xml_escape("\n\n".join(desc_dele))

        titel    = _xml_escape(f"🌿 Haven — {måned_navn} {år}")
        pub_date = _rfc2822(datetime.date(år, måned_nr, 1))
        guid     = f"{base_url}/{år}/have-almanak.rss#{år}-{måned_nr:02d}"

        items.append(
            "    <item>\n"
            f"      <title>{titel}</title>\n"
            f"      <description>{description}</description>\n"
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"      <guid isPermaLink=\"false\">{guid}</guid>\n"
            "    </item>"
        )

    indhold = (_rss_kanal_header(år, base_url)
               + "\n".join(items) + "\n"
               + "  </channel>\n</rss>\n")
    with open(rss_sti, "w", encoding="utf-8") as f:
        f.write(indhold)
    print(f"✅ RSS almanak genereret: {rss_sti} ({len(items)} måneder)")
