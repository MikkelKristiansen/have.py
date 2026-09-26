"""Tests af 'have nyt-år' — det, der kun kører én gang om året.

Fejl her opdages først i januar, og så på de rigtige data. Derfor køres
nyt_år() her mod et frisk 'have init'-projekt i tmp_path, med questionary
stubbet ud, så "Er du sikker?" svarer ja uden en terminal.
"""
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from ruamel.yaml import YAML

_PROJECT_ROOT = Path(__file__).parent.parent
_HAVEN_EXAMPLE = _PROJECT_ROOT / "haven.example.yaml"

# Kører nyt_år() i en ny proces, fordi haven.config læser HAVEN_ROOTDIR ved
# import. questionary erstattes, før nyt_år importerer det.
_KØR_NYT_ÅR = textwrap.dedent("""
    import sys, questionary
    class _Ja:
        def ask(self): return True
    questionary.confirm = lambda *a, **k: _Ja()
    questionary.press_any_key_to_continue = lambda *a, **k: _Ja()
    from haven.nyt_aar import nyt_år
    nyt_år(int(sys.argv[1]))
""")


def _projekt(tmp_path):
    """Et frisk haveprojekt (aktivt_år fra eksempelfilen) + dets miljø."""
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


def _nyt_år(rod, env, år, cwd):
    r = subprocess.run([sys.executable, "-c", _KØR_NYT_ÅR, str(år)],
                       cwd=cwd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"nyt-år fejlede:\n{r.stdout}\n{r.stderr}"
    return r


def test_nyt_år_fra_anden_mappe_skriver_i_projektet(tmp_path):
    """Det nye år skal lande i projektets data/, uanset hvor man står."""
    rod, env, år = _projekt(tmp_path)
    andet_sted = tmp_path / "andet-sted"
    andet_sted.mkdir()

    _nyt_år(rod, env, år + 1, cwd=andet_sted)

    assert (rod / "data" / str(år + 1) / "almanak.yaml").exists()
    assert (rod / "fotos" / "entries" / str(år + 1)).is_dir()
    assert not (andet_sted / "data").exists()
    assert not (andet_sted / "fotos").exists()


def test_nyt_år_tager_ikke_vejret_med(tmp_path):
    """Forrige års vejr må ikke følge med almanakken.

    Ellers springer 'have hent-vejr' månederne over (de har jo 'daglige'),
    og det nye år viser det gamle års vejr — tavst.
    """
    rod, env, år = _projekt(tmp_path)
    ryaml = YAML()
    alm_sti = rod / "data" / str(år) / "almanak.yaml"
    alm = ryaml.load(alm_sti.read_text(encoding="utf-8"))
    alm["temperatur"] = {"januar": {"middel": -0.5, "daglige": {"middel": [-0.5]}}}
    with open(alm_sti, "w", encoding="utf-8") as f:
        ryaml.dump(alm, f)

    _nyt_år(rod, env, år + 1, cwd=rod)

    ny = ryaml.load((rod / "data" / str(år + 1) / "almanak.yaml").read_text(encoding="utf-8"))
    assert "temperatur" not in ny
    assert ny["meta"]["år"] == år + 1
    # Det gamle år er urørt
    assert "temperatur" in ryaml.load(alm_sti.read_text(encoding="utf-8"))


def test_nyt_år_afviser_eksisterende_år_før_spørgsmålet(tmp_path):
    """Findes året allerede, skal der siges fra, før man bliver spurgt."""
    rod, env, år = _projekt(tmp_path)
    (rod / "data" / str(år + 1)).mkdir()

    r = subprocess.run([sys.executable, "-c", _KØR_NYT_ÅR.replace(
                            "return True", "raise AssertionError('spurgt')"),
                        str(år + 1)],
                       cwd=rod, env=env, capture_output=True, text=True)

    assert r.returncode == 1
    assert "findes allerede" in r.stdout
    assert "spurgt" not in r.stderr
