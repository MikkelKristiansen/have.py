"""Tests af 'have gennemgang' — årsgennemgangen, der kører over flere uger.

Det vigtigste løfte er, at Mikkels tekst aldrig overskrives: 'opret' kan
køres igen og igen. Dernæst at status kun udledes af filernes indhold.

Som test_nyt_aar.py køres alt i en ny proces mod et frisk 'have init'-
projekt i tmp_path, fordi haven.config læser HAVEN_ROOTDIR ved import.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_HAVEN_EXAMPLE = _PROJECT_ROOT / "haven.example.yaml"


def _projekt(tmp_path):
    rod = tmp_path / "haven"
    rod.mkdir()
    shutil.copy(_HAVEN_EXAMPLE, rod / "haven.yaml")
    env = os.environ.copy()
    env["HAVEN_ROOTDIR"] = str(rod)
    r = subprocess.run([sys.executable, "-m", "haven.cli", "init", "--ja"],
                       cwd=rod, env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"init fejlede:\n{r.stderr}"
    år = int(next(p.name for p in (rod / "data").iterdir() if p.name.isdigit()))
    return rod, env, år


def _have(rod, env, *args, forventet=0):
    r = subprocess.run([sys.executable, "-m", "haven.cli", "gennemgang", *args],
                       cwd=rod, env=env, capture_output=True, text=True)
    assert r.returncode == forventet, f"{args} gav {r.returncode}:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def test_opret_overskriver_aldrig(tmp_path):
    rod, env, år = _projekt(tmp_path)
    _have(rod, env, "opret")

    mappe = rod / "data" / str(år) / "gennemgang"
    sorter = sorted((mappe / "sorter").glob("*.md"))
    bede = sorted((mappe / "bede").glob("*.md"))
    assert sorter and bede
    erfaringer = rod / "data" / "erfaringer.md"
    assert f"## {år}" in erfaringer.read_text(encoding="utf-8")

    egen_tekst = "---\nplante_id: x\ndom: gentag\n---\nMin egen tekst\n"
    sorter[0].write_text(egen_tekst, encoding="utf-8")
    erfaringer.write_text(f"# Erfaringer\n\n## {år}\n\nForspir i februar.\n",
                          encoding="utf-8")

    ud = _have(rod, env, "opret")

    assert "intet oprettet" in ud
    assert sorter[0].read_text(encoding="utf-8") == egen_tekst
    assert erfaringer.read_text(encoding="utf-8").count(f"## {år}") == 1


def test_status_følger_filernes_indhold(tmp_path):
    rod, env, år = _projekt(tmp_path)
    _have(rod, env, "opret")
    mappe = rod / "data" / str(år) / "gennemgang"
    sort, anden = sorted((mappe / "sorter").glob("*.md"))[:2]
    bed = sorted((mappe / "bede").glob("*.md"))[0]

    sort.write_text(sort.read_text(encoding="utf-8").replace("dom:", "dom: gentag", 1),
                    encoding="utf-8")
    anden.write_text(anden.read_text(encoding="utf-8").replace("dom:", "dom: måske", 1),
                     encoding="utf-8")
    bed.write_text(bed.read_text(encoding="utf-8").replace("færdig: false", "færdig: true"),
                   encoding="utf-8")

    ud = _have(rod, env)

    assert f"✅ {sort.stem}" in ud
    assert f"✅ {bed.stem}" in ud
    assert "ukendt dom: måske" in ud
    assert "Erfaringer: · ikke skrevet" in ud


def test_år_før_underkommandoen_gælder(tmp_path):
    """'--år' før 'opret' må ikke overskrives af underkommandoens standard."""
    rod, env, år = _projekt(tmp_path)
    ud = _have(rod, env, "--år", str(år + 5), "opret", forventet=1)
    assert f"ingen data for {år + 5}" in ud
    assert not (rod / "data" / str(år) / "gennemgang").exists()
    assert not (rod / "data" / "erfaringer.md").exists()


def test_vis_ukendt_navn_fejler(tmp_path):
    rod, env, år = _projekt(tmp_path)
    ud = _have(rod, env, "vis", "findes-ikke", forventet=1)
    assert "hverken et bed eller en sort" in ud
