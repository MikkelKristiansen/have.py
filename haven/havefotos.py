#!/usr/bin/env python3
"""
havefotos — tjekker og synkroniserer almanakfotos i entries.yaml

Brug:
    have hent-havefotos                  # tør kørsel — vis manglende filer
    have hent-havefotos --skriv          # ryd foto-felter for manglende filer, gem
    have hent-havefotos --uregistrerede  # vis fotos i fotos/ der ikke bruges i nogen entry
    have hent-havefotos --vis            # vis alle entries med foto og deres status
"""

import argparse
from pathlib import Path

import yaml

from .config import load_config, data_mappe, sti as config_sti

_config = load_config()
AKTIVT_ÅR    = _config["aktivt_år"]
ENTRIES_FIL  = data_mappe(_config) / "entries.yaml"
ENTRIES_MAPPE = data_mappe(_config) / "entries"
FOTOS_MAPPE  = config_sti(_config, "fotos") / "entries" / str(AKTIVT_ÅR)


def hent_md_fotos() -> list[dict]:
    """Returnerer liste af {dato, område_id, fil} for alle markdown-entries med foto-felt.

    Entries ligger i undermapper (fx entries/sektioner/), så der glob'es rekursivt.
    """
    import re as _re
    result = []
    if not ENTRIES_MAPPE.is_dir():
        return result
    for sti in sorted(ENTRIES_MAPPE.glob("**/*.md")):
        tekst = sti.read_text(encoding="utf-8")
        m = _re.match(r"^---\n(.*?)\n---", tekst, _re.DOTALL)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        foto = fm.get("foto")
        if not foto:
            continue
        # foto kan være string eller dict med 'fil'-nøgle
        fil = foto if isinstance(foto, str) else foto.get("fil", "")
        if fil:
            result.append({
                "dato":      str(fm.get("dato", "?")),
                "område_id": fm.get("zone") or fm.get("område_id", "?"),
                "fil":       fil,
                "_kilde":    str(sti),   # til fejlfinding
            })
    return result


def hent_hons_fotos() -> list[dict]:
    """Foto-referencer fra hønse-entries (entries/hons/*.yaml) med foto-felt."""
    result = []
    hons_mappe = ENTRIES_MAPPE / "hons"
    if not hons_mappe.is_dir():
        return result
    for sti in sorted(hons_mappe.glob("*.yaml")):
        try:
            e = yaml.safe_load(sti.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(e, dict):
            continue
        foto = e.get("foto")
        if not foto:
            continue
        fil = foto if isinstance(foto, str) else foto.get("fil", "")
        if fil:
            result.append({
                "dato":      str(e.get("dato", "?")),
                "område_id": e.get("zone") or "hons",
                "fil":       fil,
                "_kilde":    str(sti),
            })
    return result


def main():
    parser = argparse.ArgumentParser(
        prog="have hent-havefotos",
        description="Tjek og synkronisér almanakfotos i entries.",
    )
    parser.add_argument("--skriv", action="store_true",
                        help="Ryd foto-felter der peger på manglende filer, og gem")
    parser.add_argument("--uregistrerede", action="store_true",
                        help="Vis fotos i fotos/ der ikke er refereret i nogen entry")
    parser.add_argument("--vis", action="store_true",
                        help="Vis alle entries med foto og deres filstatus")
    args = parser.parse_args()

    with open(ENTRIES_FIL, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    entries = data.get("entries", [])

    def _foto_fil(e):
        foto = e.get("foto")
        if isinstance(foto, dict):
            return foto.get("fil", "")
        if foto:
            return foto
        return e.get("fil", "")  # markdown pseudo-entries gemmer filnavn i "fil"

    # Saml alle entries der har et foto-felt
    med_foto = [(i, e) for i, e in enumerate(entries) if e.get("foto")]

    # Flyt markdown- og hønse-entries ind som pseudo-entries (i=None, ingen YAML-skrivning)
    for md_e in hent_md_fotos():
        med_foto.append((None, md_e))
    for hons_e in hent_hons_fotos():
        med_foto.append((None, hons_e))

    # ── --vis: list alle entries med foto ────────────────────────────────────────
    if args.vis:
        if not med_foto:
            print("Ingen entries har et foto-felt.")
            return
        print(f"{'Dato':<12} {'Område':<14} {'Fil':<30} Status")
        print("─" * 70)
        for i, e in med_foto:
            fil   = _foto_fil(e) or "?"
            sti   = FOTOS_MAPPE / fil
            ok    = "✅" if sti.exists() else "❌ mangler"
            kilde = " (md)" if i is None else ""
            print(f"{str(e.get('dato','?')):<12} {e.get('område_id','?'):<14} {fil:<30} {ok}{kilde}")
        return

    # ── --uregistrerede: vis fotos der ikke bruges + entries med tomt foto-felt ──
    if args.uregistrerede:
        brugte  = {_foto_fil(e) for _, e in med_foto if _foto_fil(e)}
        alle    = {f.name for f in FOTOS_MAPPE.iterdir() if f.is_file()} if FOTOS_MAPPE.exists() else set()
        ubrugte = sorted(alle - brugte)
        if ubrugte:
            print(f"📂 {len(ubrugte)} uregistrerede fotos i {FOTOS_MAPPE}/:")
            for navn in ubrugte:
                print(f"   {navn}")
        else:
            print(f"✅ Alle fotos i {FOTOS_MAPPE}/ er refereret i mindst én entry.")

        tomme = [(i, e) for i, e in enumerate(entries)
                 if "foto" in e and not e.get("foto")]
        if tomme:
            print(f"\n📋 {len(tomme)} entries med tomt foto-felt:")
            for _, e in tomme:
                print(f"   {str(e.get('dato','?')):<12} {e.get('område_id','?'):<14} {e.get('titel','')}")
        return

    # ── Standard: tjek manglende filer (tør kørsel eller --skriv) ────────────────
    mangler = []
    for i, e in med_foto:
        fil = _foto_fil(e)
        if not fil:
            continue
        sti = FOTOS_MAPPE / fil
        if not sti.exists():
            mangler.append((i, e, fil))
            print(f"  🗑  {str(e.get('dato','?')):<12} {e.get('område_id','?'):<14} mangler: {fil}"
                  + ("" if args.skriv else " (tør kørsel)"))
            if args.skriv and i is not None:   # kun YAML-entries kan rettes herfra
                e.pop("foto")

    if args.skriv and mangler:
        with open(ENTRIES_FIL, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True,
                      default_flow_style=False, sort_keys=False)
        print(f"\n✅ entries.yaml opdateret ({len(mangler)} foto-felter ryddet)")
    elif not mangler:
        print("✅ Alle foto-felter i entries.yaml peger på eksisterende filer.")

    # ── Opsummering ───────────────────────────────────────────────────────────────
    if not args.skriv:
        alle_filer = {f.name for f in FOTOS_MAPPE.iterdir() if f.is_file()} if FOTOS_MAPPE.exists() else set()
        brugte     = {_foto_fil(e) for _, e in med_foto if _foto_fil(e)}
        ubrugte    = sorted(alle_filer - brugte)
        print(f"\n📷 {len(med_foto)} entries med foto  |  "
              f"{len(alle_filer)} filer i fotos/  |  "
              f"{len(ubrugte)} uregistrerede")
        for navn in ubrugte:
            print(f"     • {navn}")

    # ── Optimer overstoere fotos ──────────────────────────────────────────────────
    if FOTOS_MAPPE.exists():
        from PIL import Image
        from .fotos import optimer_foto
        BILLEDE_EKST = {".jpg", ".jpeg", ".png", ".webp"}
        optimeret = []
        for fil in sorted(FOTOS_MAPPE.iterdir()):
            if not fil.is_file() or fil.suffix.lower() not in BILLEDE_EKST:
                continue
            try:
                with Image.open(fil) as img:
                    w, h = img.size
                if w <= 1200 and h <= 1200:
                    continue
                optimer_foto(fil)
                optimeret.append(fil.name)
                print(f"  🗜  {fil.name} optimeret ({w}×{h} → maks 1200px)")
            except Exception as e:
                print(f"  ⚠️  {fil.name}: kunne ikke optimere: {e}")
        if optimeret:
            print(f"\n✅ {len(optimeret)} foto(s) optimeret og gemt")


if __name__ == "__main__":
    main()
