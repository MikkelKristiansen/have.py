"""Integrationstest: init → nyt-år → build kører uden fejl."""
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_HAVEN_EXAMPLE = _PROJECT_ROOT / "haven.example.yaml"


def _kør(args, *, cwd, env, stdin_input=None):
    return subprocess.run(
        [sys.executable, "-m", "haven.cli"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        input=stdin_input,
    )


def test_init_nyt_år_build(tmp_path):
    """Smoke-test: init → nyt-år → build crasher ikke og producerer HTML."""
    # Seed haven.yaml fra eksempelfilen — kræves af init (bruges til _opdater_haven_yaml)
    shutil.copy(_HAVEN_EXAMPLE, tmp_path / "haven.yaml")

    # HAVEN_ROOTDIR styrer PROJECT_ROOT i config.py, så alle stier peger på tmp_path
    env = os.environ.copy()
    env["HAVEN_ROOTDIR"] = str(tmp_path)

    # 1. have init --ja
    result = _kør(["init", "--ja"], cwd=tmp_path, env=env)
    assert result.returncode == 0, f"init fejlede:\n{result.stderr}"

    # Eksempel-planterne refererer placeholder.jpg — opret filen så build-validering passerer
    (tmp_path / "fotos" / "planter" / "placeholder.jpg").touch()

    # 2. have nyt-år <næste år>
    # Sender 'y\n' til questionary-prompt; ved ikke-interaktiv stdin kan prompt
    # afslutte med returncode 0 via sys.exit(0) ("Afbrudt.") — det er acceptabelt.
    næste_år = datetime.date.today().year + 1
    result = _kør(
        ["nyt-år", str(næste_år)],
        cwd=tmp_path,
        env=env,
        stdin_input="y\n",
    )
    assert result.returncode == 0, f"nyt-år fejlede:\n{result.stderr}"

    # 3. have build
    result = _kør(["build"], cwd=tmp_path, env=env)
    assert result.returncode == 0, f"build fejlede:\n{result.stderr}"

    # Verificér at der er genereret mindst én HTML-fil
    html_filer = list((tmp_path / "out").rglob("*.html"))
    assert html_filer, f"Ingen HTML-filer fundet i {tmp_path / 'out'}"
