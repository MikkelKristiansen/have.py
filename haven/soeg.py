"""haven.soeg — søgeindeks (søg.json) + plante-søgehjælpere til wizards.

Render-lag i cli-opdelingen (se briefs/cli-opdeling.md, fase 4). generer_søg_json
bruges af orkestratoren; _søg_planter/_plante_label bruges af wizards (fase 5).
Afhænger af indlaes (load_yaml/load_bed_yaml/skriv_hvis_ændret) + kontekst (DYR_DB).
"""

from pathlib import Path

import yaml

from .indlaes import load_yaml, load_bed_yaml, skriv_hvis_ændret
from .kontekst import DYR_DB

__all__ = ["generer_søg_json", "_søg_planter", "_plante_label"]


def generer_søg_json(out_rod: Path, data_rod: Path, plante_db: dict) -> Path:
    """Generer søg.json med alle entries på tværs af år. Returnerer stien til filen."""
    import json
    import re as _re

    søg_data = []

    for år_mappe in sorted(data_rod.iterdir()):
        if not år_mappe.is_dir() or not år_mappe.name.isdigit():
            continue
        år = int(år_mappe.name)

        # Byg zone_id → titel mapping fra YAML-filer i årets mappe
        zone_titler: dict[str, str] = {}
        for yaml_fil in sorted(år_mappe.glob("*.yaml")):
            if yaml_fil.name in {"almanak.yaml", "entries.yaml"}:
                continue
            try:
                d = load_yaml(str(yaml_fil))
                meta = d.get("meta", {}) if isinstance(d, dict) else {}
                hn = meta.get("html_navn")
                if hn:
                    zone_titler[hn] = meta.get("titel", hn)
            except Exception:
                pass

        # Entries fra markdown-filer
        entries_mappe = år_mappe / "entries"
        råentries: list[tuple[str, dict, str]] = []
        if entries_mappe.is_dir():
            for fil in sorted(entries_mappe.iterdir()):
                if fil.suffix != ".md":
                    continue
                try:
                    indhold = fil.read_text(encoding="utf-8")
                    m = _re.match(r"^---\n(.*?)\n---\n(.*)$", indhold, _re.DOTALL)
                    if not m:
                        continue
                    fm = yaml.safe_load(m.group(1))
                    if not isinstance(fm, dict):
                        continue
                    råentries.append((fil.stem, fm, m.group(2).strip()))
                except Exception:
                    pass

        # Entries fra entries.yaml (legacy / supplement)
        entries_yaml = år_mappe / "entries.yaml"
        if entries_yaml.exists():
            try:
                yd = load_yaml(str(entries_yaml))
                for e in (yd.get("entries") or []):
                    dato = e.get("dato")
                    if not dato:
                        continue
                    dato_str = dato.isoformat() if hasattr(dato, "isoformat") else str(dato)
                    zone = e.get("zone") or e.get("område_id", "")
                    stem = f"{dato_str}-{zone}"
                    råentries.append((stem, e, str(e.get("tekst", "")).strip()))
            except Exception:
                pass

        for fil_stem, fm, tekst in råentries:
            dato = fm.get("dato")
            if not dato:
                continue
            dato_str = dato.isoformat() if hasattr(dato, "isoformat") else str(dato)
            zone = fm.get("zone") or fm.get("område_id", "")
            # Normaliser plante_id: string eller liste → altid liste
            råpid = fm.get("plante_id")
            if råpid is None:
                plante_ids = []
            elif isinstance(råpid, str):
                plante_ids = [råpid] if råpid else []
            else:
                plante_ids = list(råpid)

            # Byg kommasepareret navneliste til søgeindeks
            navne_dele = []
            for pid in plante_ids:
                p = plante_db.get(pid, {})
                if p:
                    n = p.get("navn", "")
                    s = p.get("sort", "")
                    navne_dele.append(f"{n} – {s}" if s else n)
            navn = ", ".join(navne_dele) if navne_dele else None

            bed_titel = zone_titler.get(zone, zone)
            søg_data.append({
                "type":      "entry",
                "år":        år,
                "dato":      dato_str,
                "bed":       zone,
                "bed_titel": bed_titel,
                "plante_id": plante_ids,   # altid liste — konsistent felttype i søgeindekset
                "navn":      navn,
                "tekst":     tekst,
                "link":      f"{år}/almanak.html#{fil_stem}",
            })

        # ── Bedeplaner ────────────────────────────────────────────────────────────
        # (zone_html_navn, plante_id) → {bed_titel, bed_navne: set}
        SPRING = {"almanak.yaml", "entries.yaml"}
        bedeplaner: dict[tuple[str, str], dict] = {}
        for yaml_fil in sorted(år_mappe.glob("*.yaml")):
            if yaml_fil.name in SPRING:
                continue
            try:
                d = load_bed_yaml(str(yaml_fil))
                if not isinstance(d, dict):
                    continue
                meta = d.get("meta", {})
                html_navn = meta.get("html_navn")
                bed_titel = meta.get("titel", "")
                if not html_navn:
                    continue
                for bed in d.get("bede", []):
                    bed_navn = bed.get("navn") or bed.get("id", "")
                    for zone in bed.get("zoner", []):
                        pids: set[str] = {
                            afg["plante_id"]
                            for afg in zone.get("afgrøder", [])
                            if afg.get("plante_id")
                        }
                        for pid in pids:
                            key = (html_navn, pid)
                            if key not in bedeplaner:
                                bedeplaner[key] = {"bed_titel": bed_titel, "bed_navne": set()}
                            bedeplaner[key]["bed_navne"].add(bed_navn)
            except Exception:
                pass

        for (html_navn, plante_id), info in sorted(bedeplaner.items()):
            plante = plante_db.get(plante_id, {})
            navn = plante.get("navn", plante_id)
            sort = plante.get("sort", "")
            if sort:
                navn = f"{navn} – {sort}"
            bed_navne_str = ", ".join(sorted(info["bed_navne"]))
            søg_data.append({
                "type":      "bedeplan",
                "år":        år,
                "dato":      None,
                "bed":       html_navn,
                "bed_titel": info["bed_titel"],
                "plante_id": plante_id,
                "navn":      navn,
                "tekst":     bed_navne_str,
                "link":      f"{år}/{html_navn}.html#bedoversigt",
            })

    # ── Planter fra planter.yaml ─────────────────────────────────────────────
    planter_del = []
    for pid, p in sorted(plante_db.items()):
        navn = p.get("navn", pid)
        sort = p.get("sort", "")
        if sort:
            navn = f"{navn} – {sort}"
        dele = [navn]
        if p.get("latin"):
            dele.append(p["latin"])
        if p.get("familie"):
            dele.append(p["familie"])
        planter_del.append({
            "type":   "plante",
            "navn":   navn,
            "latin":  p.get("latin") or "",
            "familie": p.get("familie") or "",
            "tekst":  " · ".join(filter(None, [p.get("latin"), p.get("familie")])),
            "link":   f"planter.html#plante-{pid}",
        })
    planter_del.sort(key=lambda e: e["navn"].lower())

    # ── Høns fra dyr.yaml ────────────────────────────────────────────────────
    høns_del = []
    for hid, h in sorted(DYR_DB.items()):
        race  = str(h.get("race", "") or "")
        farve = str(h.get("farve", "") or "")
        noter = str(h.get("noter", "") or "")
        navn  = h.get("navn") or race or hid
        høns_del.append({
            "type":   "høne",
            "navn":   navn,
            "race":   race,
            "farve":  farve,
            "noter":  noter,
            # tekst gør race/farve/noter søgbare via Fuse (vises ikke direkte)
            "tekst":  " · ".join(filter(None, [race, farve, noter])),
            "link":   f"hoenseregisteret.html#høne-{hid}",
        })
    høns_del.sort(key=lambda e: e["navn"].lower())

    entries_del  = [e for e in søg_data if e["type"] == "entry"]
    bedeplaner_del = [e for e in søg_data if e["type"] == "bedeplan"]
    entries_del.sort(key=lambda e: e["dato"], reverse=True)
    bedeplaner_del.sort(key=lambda e: (-e["år"], e["bed"], e.get("navn", "")))
    søg_data = entries_del + bedeplaner_del + planter_del + høns_del
    ud_sti = out_rod / "søg.json"
    ny = json.dumps(søg_data, ensure_ascii=False, separators=(",", ":"))
    if skriv_hvis_ændret(ud_sti, ny):
        print(f"✅ Søgeindeks genereret: {ud_sti} ({len(søg_data)} entries)")
    else:
        print(f"ℹ️  Søgeindeks uændret: {ud_sti}")
    return ud_sti, søg_data


def _søg_planter(søg: str, db: dict, maks: int = 8) -> list[dict]:
    """Returnér op til `maks` planter hvis navn/sort/id matcher `søg` (case-insensitiv)."""
    søg_l = søg.lower()
    resultater = []
    for pid, p in db.items():
        felt = " ".join(filter(None, [
            str(p.get("navn", "")),
            str(p.get("sort", "")),
            pid,
        ])).lower()
        if søg_l in felt:
            resultater.append(p)
    resultater.sort(key=lambda p: p.get("navn", "").lower())
    return resultater[:maks]


def _plante_label(p: dict) -> str:
    navn = p.get("navn", p.get("id", "?"))
    sort = p.get("sort", "")
    pid  = p.get("id", "")
    if sort:
        return f"{navn} – {sort} [{pid}]"
    return f"{navn} [{pid}]"
