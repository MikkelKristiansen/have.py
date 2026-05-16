
#!/usr/bin/env python3
"""
hent_plantefotos.py — henter manglende billeder fra Wikimedia Commons
og opdaterer planter.yaml med billede-stien.

Brug:
    python3 hent_plantefotos.py                          # tør kørsel — vis hvad der ville ske
    python3 hent_plantefotos.py --skriv                  # kør begge trin og gem
    python3 hent_plantefotos.py --lokal --skriv          # registrér kun filer der ligger i fotos/
    python3 hent_plantefotos.py --wikimedia --skriv      # hent kun fra Wikimedia
    python3 hent_plantefotos.py --skriv --id dild        # kun én plante
    python3 hent_plantefotos.py --sync                   # tør kørsel: vis foto-felter der peger på manglende filer
    python3 hent_plantefotos.py --sync --skriv           # ryd foto-felter for manglende filer, gem
    python3 hent_plantefotos.py --skriv --id cayenne --force  # gendownload/re-registrér selvom foto-felt allerede er sat
    python3 hent_plantefotos.py --registrér cayenne           # re-registrér lokal fil og gem (svarer til --force --lokal --skriv --id)
    python3 hent_plantefotos.py --vis-links                   # list Wikimedia Commons-links for alle planter med registreret billede
    python3 hent_plantefotos.py --placeholder --skriv         # sæt fotos/placeholder.jpg på alle planter uden foto
"""

import argparse
import html
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import yaml
from PIL import Image, ImageOps

from .config import load_config, sti as config_sti
from .wikidata import wikidata_hent_foto_url, wikidata_hent_foto_metadata

_config = load_config()
AKTIVT_ÅR   = _config["aktivt_år"]
PLANTER_FIL = config_sti(_config, "data") / "planter.yaml"
FOTOS_MAPPE = config_sti(_config, "fotos") / "planter"
ENTRIES_FOTOS_MAPPE = config_sti(_config, "fotos") / "entries" / str(AKTIVT_ÅR)
_kontakt_email = _config.get("kontakt_email", "")
_ua_suffix = f" (kontakt: {_kontakt_email})" if _kontakt_email else ""
HEADERS     = {"User-Agent": f"have.py/1.0{_ua_suffix}"}

BILLEDE_EKST = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _har_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)


def optimer_foto(sti: Path) -> Path:
    """Resize til maks 1200px, gem som JPEG (undtagen PNG med alpha). Returnerer gem-sti."""
    with Image.open(sti) as img:
        img = ImageOps.exif_transpose(img)
        har_alpha = _har_alpha(img)
        if har_alpha:
            img.thumbnail((1200, 1200))
            img.save(sti, optimize=True)
            gem_sti = sti
        else:
            img = img.convert("RGB")
            img.thumbnail((1200, 1200))
            gem_sti = sti.with_suffix(".jpg")
            img.save(gem_sti, "JPEG", quality=82, optimize=True)
            if gem_sti != sti:
                sti.unlink()

    _generer_thumbnail(gem_sti)
    return gem_sti


def _generer_thumbnail(sti: Path):
    """Generer thumbnail (maks 400px) i thumbs/-undermappen ved siden af filen."""
    thumbs_mappe = sti.parent / "thumbs"
    thumbs_mappe.mkdir(exist_ok=True)
    thumb_sti = thumbs_mappe / sti.name
    with Image.open(sti) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((400, 400))
        if sti.suffix.lower() in (".jpg", ".jpeg"):
            img.save(thumb_sti, "JPEG", quality=82, optimize=True)
        else:
            img.save(thumb_sti, optimize=True)

# ── Wikipedia-søgning ─────────────────────────────────────────────────────────

def søgeterm(plante: dict) -> str | None:
    """Vælg bedste søgeterm for planten: wikipedia-felt > latin-felt."""
    return plante.get("wikipedia") or plante.get("latin") or None


def find_wikipedia_titel(term: str) -> str | None:
    import urllib.parse, json
    url = ("https://en.wikipedia.org/w/api.php?"
           + urllib.parse.urlencode({
               "action": "opensearch", "search": term,
               "limit": 1, "format": "json"
           }))
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        resultater = json.loads(r.read())[1]
    return resultater[0] if resultater else None


def hent_billede_info(titel: str) -> dict | None:
    import urllib.parse, json
    # Thumbnail fra Wikipedia
    url = ("https://en.wikipedia.org/w/api.php?"
           + urllib.parse.urlencode({
               "action": "query", "titles": titel,
               "prop": "pageimages", "pithumbsize": 1200,
               "pilicense": "any", "format": "json"
           }))
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    page = next(iter(data["query"]["pages"].values()))
    thumb = page.get("thumbnail")
    if not thumb:
        return None
    filnavn = page.get("pageimage", "")

    # Licensinfo fra Commons
    url2 = ("https://commons.wikimedia.org/w/api.php?"
            + urllib.parse.urlencode({
                "action": "query", "titles": f"File:{filnavn}",
                "prop": "imageinfo", "iiprop": "url|extmetadata",
                "format": "json"
            }))
    req2 = urllib.request.Request(url2, headers=HEADERS)
    with urllib.request.urlopen(req2, timeout=10) as r:
        data2 = json.loads(r.read())
    info_page = next(iter(data2["query"]["pages"].values()))
    imageinfo = info_page.get("imageinfo", [{}])[0]
    meta      = imageinfo.get("extmetadata", {})

    fotograf = html.unescape(
        re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "?"))
    ).strip()

    return {
        "download_url": thumb["source"],
        "filnavn":      filnavn,
        "licens":       meta.get("LicenseShortName", {}).get("value", "?"),
        "fotograf":     fotograf[:120],
        "commons_url":  imageinfo.get("descriptionurl", ""),
    }


def spørg_om_metadata(pid: str, lokalt: str) -> dict:
    """Returnerer foto-subdict med metadata indtastet interaktivt."""
    print(f"\n  📷 Metadata for {pid} ({lokalt})")
    print(f"  Tryk Enter for at springe et felt over.\n")
    licens    = input("  Licens    (fx 'CC BY-SA 4.0', 'Eget foto'): ").strip()
    forfatter = input("  Forfatter (fx 'Hans Jensen'): ").strip()
    kilde     = input("  Kilde URL (fx 'https://commons.wikimedia.org/...'): ").strip()
    meta: dict = {}
    if licens:    meta["licens"]    = licens
    if forfatter: meta["forfatter"] = forfatter
    if kilde:     meta["kilde"]     = kilde
    return meta


def download_foto(url: str, dest: Path) -> Path:
    """Download fil til dest, optimer og generer thumbnail. Returnerer faktisk gem-sti."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        with open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    return optimer_foto(dest)


# ── Hovedlogik ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skriv", action="store_true",
                        help="Gem ændringer til planter.yaml (ellers tør kørsel)")
    parser.add_argument("--lokal", action="store_true",
                        help="Registrér filer i fotos/ der matcher et plante-id")
    parser.add_argument("--wikimedia", action="store_true",
                        help="Søg og download fotos fra Wikimedia Commons")
    parser.add_argument("--sync", action="store_true",
                        help="Ryd foto-felter der peger på filer som ikke længere eksisterer")
    parser.add_argument("--force", action="store_true",
                        help="Gendownload/re-registrér selv om foto-feltet allerede er udfyldt")
    parser.add_argument("--id", help="Kun denne plante-id")
    parser.add_argument("--registrér", metavar="ID",
                        help="Re-registrér lokal fil for ét plante-id og gem (svarer til --force --lokal --skriv --id)")
    parser.add_argument("--vis-links", action="store_true",
                        help="List Wikimedia Commons-links for alle planter med registreret billede")
    parser.add_argument("--placeholder", action="store_true",
                        help="Sæt fotos/placeholder.jpg på alle planter uden foto")
    parser.add_argument("--check-placeholder", action="store_true",
                        help="List planter der stadig bruger placeholder.jpg")
    parser.add_argument("--generer-thumbs", action="store_true",
                        help="Generer manglende thumbnails for alle billeder i fotos/planter/ og fotos/entries/")
    args = parser.parse_args()

    # --generer-thumbs: generer thumbnails for eksisterende billeder
    if args.generer_thumbs:
        for mappe in [FOTOS_MAPPE, ENTRIES_FOTOS_MAPPE]:
            if not mappe.is_dir():
                print(f"  ⚠️  {mappe}/ ikke fundet — springer over")
                continue
            print(f"\n📁 {mappe}/")
            for fil in sorted(mappe.iterdir()):
                if not fil.is_file() or fil.suffix.lower() not in BILLEDE_EKST:
                    continue
                thumbs_mappe = mappe / "thumbs"
                thumbs_mappe.mkdir(exist_ok=True)
                thumb_sti = thumbs_mappe / fil.name
                if thumb_sti.exists():
                    print(f"  ⏭  {fil.name}")
                    continue
                try:
                    _generer_thumbnail(fil)
                    print(f"  ✅ {fil.name} → thumbs/{fil.name}")
                except Exception as e:
                    print(f"  ❌ {fil.name}: {e}")
        return

    # --vis-links: ren oplistning fra YAML, ingen API-kald
    if args.vis_links:
        with open(PLANTER_FIL, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        planter = data if isinstance(data, list) else data.get("planter", [])
        med_link = [
            (p["id"], p.get("navn",""),
             (p.get("foto") or {}).get("licens","?"),
             (p.get("foto") or {}).get("kilde",""))
            for p in planter if isinstance(p.get("foto"), dict) and p["foto"].get("kilde")
        ]
        if med_link:
            print(f"{'Plante':<25} {'Licens':<14} URL")
            print("─" * 80)
            for pid, navn, licens, url in med_link:
                print(f"{navn or pid:<25} {licens:<14} {url}")
        else:
            print("Ingen planter har et registreret kilde-felt endnu.")
        return

    # --placeholder: sæt fotos/placeholder.jpg på alle planter uden foto
    if args.placeholder:
        with open(PLANTER_FIL, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        planter = data if isinstance(data, list) else data.get("planter", [])
        PLACEHOLDER = "placeholder.jpg"
        placeholder_sti = FOTOS_MAPPE / PLACEHOLDER
        if not placeholder_sti.exists():
            print(f"  ⬇️  Henter placeholder-billede ...")
            url = ("https://upload.wikimedia.org/wikipedia/commons/8/80/"
                   "Vegetable_garden_at_Ham_House_Estate_-_geograph.org.uk_-_4530.jpg")
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                FOTOS_MAPPE.mkdir(exist_ok=True)
                with open(placeholder_sti, "wb") as f:
                    shutil.copyfileobj(r, f)
        uden = [p for p in planter if not p.get("foto")]
        for p in uden:
            print(f"  🖼  {p.get('id','?'):25} → {PLACEHOLDER}"
                  + ("" if args.skriv else " (tør kørsel)"))
            if args.skriv:
                p["foto"] = {"fil": PLACEHOLDER}
        if args.skriv and uden:
            with open(PLANTER_FIL, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True,
                          default_flow_style=False, sort_keys=False)
            print(f"\n✅ planter.yaml opdateret ({len(uden)} planter fik placeholder)")
        elif not uden:
            print("  ✅ Alle planter har allerede et foto-felt.")
        return

    # --check-placeholder: list planter med placeholder.jpg
    if args.check_placeholder:
        with open(PLANTER_FIL, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        planter = data if isinstance(data, list) else data.get("planter", [])
        med_placeholder = [
            p for p in planter
            if isinstance(p.get("foto"), dict) and p["foto"].get("fil") == "placeholder.jpg"
        ]
        if not med_placeholder:
            print("✅ Ingen planter bruger placeholder.jpg")
        else:
            print(f"🖼  {len(med_placeholder)} plante(r) med placeholder.jpg:\n")
            for p in med_placeholder:
                print(f"  {p.get('id','?'):25} {p.get('navn','')}")
            print(f"\n  Hent fotos med:")
            for p in med_placeholder:
                print(f"    have hent-fotos --id {p.get('id','?')}")
        return

    # --registrér er genvej for --force --lokal --skriv --id <ID>
    if args.registrér:
        args.force   = True
        args.lokal   = True
        args.skriv   = True
        args.id      = args.registrér
        args.wikimedia = False

    # Ingen fetch-trin valgt → kør begge (medmindre --sync er eneste flag)
    kun_sync      = args.sync and not (args.lokal or args.wikimedia)
    kør_lokal     = args.lokal     or (not args.lokal and not args.wikimedia and not kun_sync)
    kør_wikimedia = args.wikimedia or (not args.lokal and not args.wikimedia and not kun_sync)

    with open(PLANTER_FIL, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    planter = data if isinstance(data, list) else data.get("planter", [])

    if args.skriv:
        FOTOS_MAPPE.mkdir(exist_ok=True)

    def udvalgte():
        for p in planter:
            if args.id and p.get("id") != args.id:
                continue
            yield p

    manuelle_ids = set()

    # ── Sync: ryd foto-felter der peger på filer som ikke eksisterer ──────────
    if args.sync:
        mangler = []
        for p in udvalgte():
            foto_data = p.get("foto")
            if not isinstance(foto_data, dict):
                continue
            fil = foto_data.get("fil", "")
            if not fil or fil.startswith("http"):
                continue
            if not (FOTOS_MAPPE / fil).exists():
                mangler.append((p.get("id", "?"), fil))
                if args.skriv:
                    p.pop("foto", None)
                print(f"  🗑  {p.get('id','?'):25} mangler: {fil}"
                      + ("" if args.skriv else " (tør kørsel)"))
        if args.skriv and mangler:
            with open(PLANTER_FIL, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True,
                          default_flow_style=False, sort_keys=False)
            print(f"\n✅ planter.yaml opdateret ({len(mangler)} foto-felter ryddet)")
        elif not mangler:
            print("  ✅ Alle foto-felter peger på eksisterende filer.")
        if kun_sync:
            return

    # ── Trin 1: registrér manuelle fotos der ligger i fotos/ men mangler foto-felt ──
    if kør_lokal:
        manuelle = []
        for p in udvalgte():
            nuv_fil = (p.get("foto") or {}).get("fil") if isinstance(p.get("foto"), dict) else None
            if nuv_fil not in (None, "placeholder.jpg") and not args.force:
                continue
            pid = p.get("id", "")
            match = next((f for f in FOTOS_MAPPE.glob(f"{pid}.*") if f.is_file()), None)
            if not match:
                if args.registrér:
                    print(f"  ❌ {pid:25} ingen fil fundet i fotos/ — kopiér billedet hertil først:")
                    print(f"       cp <dit-billede> fotos/{pid}.jpg")
                continue
            lokalt = match.name
            manuelle_ids.add(pid)
            manuelle.append((pid, lokalt))
            print(f"  📁 {pid:25} manuel fil fundet: {lokalt}"
                  + ("" if args.skriv else " (tør kørsel)"))
            if args.skriv:
                foto_block = {"fil": lokalt}
                if args.registrér:
                    foto_block.update(spørg_om_metadata(pid, lokalt))
                p["foto"] = foto_block

        if args.skriv and manuelle:
            with open(PLANTER_FIL, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True,
                          default_flow_style=False, sort_keys=False)
            print(f"\n✅ planter.yaml opdateret ({len(manuelle)} manuelle fotos registreret)\n")

    # ── Trin 2: hent resten fra Wikimedia ──
    if kør_wikimedia:
        mangler_søgeterm = []
        resultater = []

        for p in udvalgte():
            nuv_fil = (p.get("foto") or {}).get("fil") if isinstance(p.get("foto"), dict) else None
            if (nuv_fil not in (None, "placeholder.jpg") or p.get("id") in manuelle_ids) and not args.force:
                print(f"  ⏭  {p['id']:25} har allerede foto")
                continue

            term = søgeterm(p)
            if not term:
                mangler_søgeterm.append(p)
                print(f"  ⚠️  {p['id']:25} — mangler latin-felt")
                continue

            print(f"  🔍 {p['id']:25} søger: {term!r} ...", end=" ", flush=True)
            try:
                # Lag 1: Wikidata P18-billede (direkte Commons-URL)
                qid = p.get("wikidata")
                if qid:
                    p18_url = wikidata_hent_foto_url(qid)
                    if p18_url:
                        ext    = Path(p18_url.rsplit("/", 1)[-1]).suffix.lower() or ".jpg"
                        lokalt = f"{p['id']}{ext}"
                        dest   = FOTOS_MAPPE / lokalt
                        print(f"✅ P18 [{qid}]")
                        print(f"        🔗 {p18_url}")
                        if not args.skriv:
                            print(f"        (tør kørsel — ville gemme {dest})")
                        else:
                            gem_sti = download_foto(p18_url, dest)
                            lokalt  = gem_sti.name
                            meta = wikidata_hent_foto_metadata(p18_url)
                            p["foto"] = {
                                "fil":      lokalt,
                                "kilde":    meta.get("url") or p18_url,
                                "licens":   meta.get("licens"),
                                "forfatter": meta.get("forfatter"),
                            }
                            p["foto"] = {k: v for k, v in p["foto"].items() if v is not None}
                            print(f"        💾 gemt: {gem_sti}")
                        resultater.append((p["id"], p18_url, {}))
                        continue

                # Lag 2+3: Wikipedia opensearch → pageimages
                titel = find_wikipedia_titel(term)
                if not titel:
                    print("ingen Wikipedia-side")
                    continue
                info = hent_billede_info(titel)
                if not info:
                    wiki_url = "https://en.wikipedia.org/wiki/" + titel.replace(" ", "_")
                    commons_url = "https://commons.wikimedia.org/w/index.php?search=" + titel.replace(" ", "+")
                    print(f"side fundet men intet billede")
                    print(f"        🔗 {wiki_url}")
                    print(f"        🔗 {commons_url}")
                    continue

                ext    = Path(info["filnavn"]).suffix.lower() or ".jpg"
                lokalt = f"{p['id']}{ext}"
                dest   = FOTOS_MAPPE / lokalt

                print(f"✅ {titel!r} [{info['licens']}]")
                print(f"        🔗 {info['commons_url']}")
                if not args.skriv:
                    print(f"        (tør kørsel — ville gemme {dest})")
                else:
                    gem_sti = download_foto(info["download_url"], dest)
                    lokalt = gem_sti.name
                    p["foto"] = {
                        "fil":      lokalt,
                        "licens":   info["licens"],
                        "forfatter": info["fotograf"],
                        "kilde":    info["commons_url"],
                    }
                    print(f"        💾 gemt: {gem_sti}")

                resultater.append((p["id"], titel, info))

            except Exception as e:
                print(f"❌ fejl: {e}")
            finally:
                time.sleep(1)

        if args.skriv and resultater:
            with open(PLANTER_FIL, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True,
                          default_flow_style=False, sort_keys=False)
            print(f"\n✅ planter.yaml opdateret ({len(resultater)} Wikimedia-fotos tilføjet)")

        if mangler_søgeterm:
            print(f"\n⚠️  {len(mangler_søgeterm)} planter mangler latin-felt:")
            for p in mangler_søgeterm:
                print(f"   - {p['id']:25} ({p.get('navn','')})")
            print("\n   Tilføj fx:")
            print("     latin: \"Thymus vulgaris\"")
            print("   i planter.yaml for disse planter.")

    # ── Opsummering: planter uden foto eller farve ────────────────────────────────
    if not args.id:
        uden_foto = [p for p in planter if not p.get("foto")]
        if uden_foto:
            print(f"\n📷 {len(uden_foto)} planter mangler stadig foto:")
            for p in uden_foto:
                print(f"   - {p['id']:25} ({p.get('navn','')})")
        else:
            print("\n✅ Alle planter har foto.")

        uden_farve = [p for p in planter if not p.get("farve")]
        if uden_farve:
            print(f"\n🎨 {len(uden_farve)} planter mangler farve-felt:")
            for p in uden_farve:
                print(f"   - {p['id']:25} ({p.get('navn','')})")
            print("   Tilføj fx:  farve: '#66bb6a'  i planter.yaml")


if __name__ == "__main__":
    main()
