"""haven.gennemgang.vejr_normal — årets vejr ved siden af et normalår.

Så en sort ikke dømmes for et dårligt år: viser månedens middeltemperatur
og nedbør for året (fra almanak.yaml, skrevet af 'have hent-vejr') ved
siden af gennemsnittet 1991–2020 for samme sted (Open-Meteo-arkivet).

Normalåret hentes én gang og caches i .cache/ (git-ignoreret, og Drive
synker ikke prikmapper). Cachen er ikke data — slettes den, hentes den igen.
"""

import datetime
import json
import sys

from ..kontekst import _config, MÅNEDER_LANG
from ..indlaes import load_yaml
from .stier import CACHE_MAPPE, DATA_ROD

__all__ = ["NORMAL_FRA", "NORMAL_TIL", "sammenlign"]

NORMAL_FRA = 1991
NORMAL_TIL = 2020


def _hent_normal(bredde: float, længde: float) -> dict:
    """{måned (1-12): {"middel": °C, "nedbør_mm": mm pr. måned}}"""
    import requests
    print(f"📡 Henter normalår {NORMAL_FRA}–{NORMAL_TIL} fra Open-Meteo (kun første gang)…",
          file=sys.stderr)
    resp = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": bredde, "longitude": længde,
            "start_date": f"{NORMAL_FRA}-01-01", "end_date": f"{NORMAL_TIL}-12-31",
            "daily": "temperature_2m_mean,precipitation_sum",
            "timezone": "Europe/Copenhagen",
        },
        timeout=120,
    )
    resp.raise_for_status()
    daily = resp.json()["daily"]
    temp: dict[int, list] = {m: [] for m in range(1, 13)}
    nedbør: dict[int, float] = {m: 0.0 for m in range(1, 13)}
    for dato, t, n in zip(daily["time"], daily["temperature_2m_mean"],
                          daily["precipitation_sum"]):
        m = datetime.date.fromisoformat(dato).month
        if t is not None:
            temp[m].append(t)
        nedbør[m] += n or 0.0
    antal_år = NORMAL_TIL - NORMAL_FRA + 1
    return {m: {"middel": round(sum(temp[m]) / len(temp[m]), 1) if temp[m] else None,
                "nedbør_mm": round(nedbør[m] / antal_år, 1)}
            for m in range(1, 13)}


def _normal() -> dict | None:
    lok = _config.get("lokation")
    if not lok:
        return None
    bredde, længde = lok["breddegrad"], lok["længdegrad"]
    cache = CACHE_MAPPE / f"vejr-normal-{bredde}-{længde}.json"
    if cache.exists():
        return {int(k): v for k, v in json.loads(cache.read_text()).items()}
    try:
        normal = _hent_normal(bredde, længde)
    except Exception as e:  # netværk, API — gennemgangen skal virke uden
        print(f"⚠️  Kunne ikke hente normalåret: {e}", file=sys.stderr)
        return None
    CACHE_MAPPE.mkdir(exist_ok=True)
    cache.write_text(json.dumps(normal))
    return normal


def sammenlign(år: int) -> list[dict] | None:
    """Én række pr. måned med årets og normalårets tal. None uden lokation/vejr.

    Felter: måned, middel, normal_middel, nedbør, normal_nedbør (None hvor tal mangler).
    """
    alm_sti = DATA_ROD / str(år) / "almanak.yaml"
    temperatur = (load_yaml(alm_sti).get("temperatur") or {}) if alm_sti.exists() else {}
    if not temperatur:
        return None
    normal = _normal() or {}
    rækker = []
    for i, navn in enumerate(MÅNEDER_LANG, start=1):
        t = temperatur.get(navn) or {}
        n = normal.get(i) or {}
        rækker.append({"måned": navn,
                       "middel": t.get("middel"), "normal_middel": n.get("middel"),
                       "nedbør": t.get("nedbør_mm"), "normal_nedbør": n.get("nedbør_mm")})
    return rækker
