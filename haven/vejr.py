"""haven.vejr — hent historisk vejrdata fra Open-Meteo til almanak.yaml.

Sideløbende handler-modul i cli-opdelingen (se briefs/cli-opdeling.md, fase 5).
Afhænger af config (sti) + kontekst (_config, MÅNEDER_LANG) + stdlib; requests og
ruamel importeres lokalt i funktionen.
"""

import datetime
import sys

from .config import sti
from .kontekst import _config, MÅNEDER_LANG

__all__ = ["hent_vejr"]


def hent_vejr(år: int, force: bool = False):
    """Hent historisk vejrdata fra Open-Meteo og skriv månedlig statistik til almanak.yaml."""
    try:
        import requests
    except ImportError:
        print("❌ requests er ikke installeret — kør: pip install requests")
        sys.exit(1)

    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    lok = _config.get("lokation")
    if not lok:
        print(
            "❌ Mangler 'lokation' i haven.yaml. Tilføj:\n\n"
            "  lokation:\n"
            "    breddegrad: 55.67\n"
            "    længdegrad: 12.56\n"
            "    navn: \"København NV\""
        )
        sys.exit(1)

    breddegrad = lok["breddegrad"]
    længdegrad = lok["længdegrad"]
    sted_navn  = lok.get("navn", f"{breddegrad}, {længdegrad}")

    i_dag       = datetime.date.today()
    start_dato  = datetime.date(år, 1, 1)
    if force:
        slut_dato = i_dag
    else:
        slut_dato = i_dag.replace(day=1) - datetime.timedelta(days=1)

    if slut_dato < start_dato:
        print(f"ℹ️  Ingen afsluttede måneder at hente for {år} endnu")
        return

    almanak_sti = sti(_config, "data") / str(år) / "almanak.yaml"
    if not almanak_sti.exists():
        print(f"❌ Filen findes ikke: {almanak_sti}")
        sys.exit(1)

    print(f"📡 Henter vejrdata for {sted_navn} ({start_dato} → {slut_dato})…")
    try:
        resp = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude":   breddegrad,
                "longitude":  længdegrad,
                "start_date": start_dato.isoformat(),
                "end_date":   slut_dato.isoformat(),
                "daily":      "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum",
                "timezone":   "Europe/Copenhagen",
            },
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"❌ Netværksfejl ved kald til Open-Meteo: {e}")
        sys.exit(1)
    if not resp.ok:
        print(f"❌ API-fejl {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)

    daily      = resp.json().get("daily", {})
    datoer     = daily.get("time") or []
    t_max      = daily.get("temperature_2m_max") or []
    t_min      = daily.get("temperature_2m_min") or []
    t_mean     = daily.get("temperature_2m_mean") or []
    nedbør_raw = daily.get("precipitation_sum") or []

    if not datoer:
        print("❌ Open-Meteo returnerede ingen daglige data for perioden.")
        sys.exit(1)

    # Sikker indeksering: et enkelt manglende/kortere felt i API-svaret må ikke
    # give IndexError — manglende værdier behandles som None.
    def _v(arr, i):
        return arr[i] if i < len(arr) else None

    måneds_rå: dict[str, dict] = {}
    for i, dato_str in enumerate(datoer):
        måned_navn = MÅNEDER_LANG[datetime.date.fromisoformat(dato_str).month - 1]
        d = måneds_rå.setdefault(måned_navn, {"mean": [], "min": [], "max": [], "ned": []})
        d["mean"].append(_v(t_mean, i))
        d["min"].append(_v(t_min, i))
        d["max"].append(_v(t_max, i))
        nv = _v(nedbør_raw, i)
        d["ned"].append(nv if nv is not None else 0.0)

    ryaml = YAML()
    ryaml.preserve_quotes  = True
    ryaml.default_flow_style = False
    ryaml.width = 120
    with open(almanak_sti, encoding="utf-8") as f:
        alm = ryaml.load(f) or {}

    if "temperatur" not in alm:
        alm["temperatur"] = {}

    temp_sek = alm["temperatur"]
    skrevne  = []

    def _flow_seq(vals):
        s = CommentedSeq([round(v, 1) if v is not None else None for v in vals])
        s.fa.set_flow_style()
        return s

    for måned_navn, d in måneds_rå.items():
        mean_vals = [v for v in d["mean"] if v is not None]
        if not mean_vals:
            continue

        existing = temp_sek.get(måned_navn)
        har_daglige = existing is not None and existing.get("daglige")

        if har_daglige and not force:
            continue

        daglige_cm = CommentedMap()
        daglige_cm["middel"] = _flow_seq(d["mean"])
        daglige_cm["min"]    = _flow_seq(d["min"])
        daglige_cm["max"]    = _flow_seq(d["max"])
        daglige_cm["nedbør"] = _flow_seq(d["ned"])

        if existing is not None and not force:
            existing["daglige"] = daglige_cm
            print(f"  ✓ {måned_navn} {år}: daglige data tilføjet")
        else:
            min_vals = [v for v in d["min"] if v is not None]
            max_vals = [v for v in d["max"] if v is not None]
            m = CommentedMap()
            m["middel"]    = round(sum(mean_vals) / len(mean_vals), 1)
            m["min"]       = round(min(min_vals), 1) if min_vals else None
            m["max"]       = round(max(max_vals), 1) if max_vals else None
            m["nedbør_mm"] = round(sum(d["ned"]), 1)
            m["daglige"]   = daglige_cm
            temp_sek[måned_navn] = m
            print(f"  ✓ {måned_navn} {år} skrevet")
        skrevne.append(måned_navn)

    if not skrevne:
        print("ℹ️  Ingen nye måneder at skrive (brug --force for at overskrive eksisterende)")
        return

    with open(almanak_sti, "w", encoding="utf-8") as f:
        ryaml.dump(alm, f)

    print(f"\n✅ {len(skrevne)} måned(er) skrevet til {almanak_sti.name}")
