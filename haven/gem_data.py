"""haven.gem_data — `have gem-data`: commit + push af havedata-repoet (data/).

data/ er et selvstændigt, privat git-repo (remote på GitHub), adskilt fra
kode-repoet. Synology Drive synker ikke prikfiler, så data/.git findes kun på
den maskine, der har klonet det (x1) — kun dér giver kommandoen mening.

Handler-modul: afhænger kun af config/kontekst + stdlib.
"""

import datetime
import subprocess
import sys

from .config import sti
from .kontekst import _config

__all__ = ["gem_data"]


def gem_data(besked: str | None = None) -> None:
    """Commit + push af data/. Springer over, hvis intet er ændret."""
    data_rod = sti(_config, "data")
    if not (data_rod / ".git").exists():
        print(f"❌ {data_rod} er ikke et git-repo på denne maskine — kan ikke gemme havedata.\n"
              f"   (Synology Drive synker ikke .git; klon haven-data dér, hvor du vil gemme.)",
              file=sys.stderr)
        sys.exit(1)

    def git(*argv):
        return subprocess.run(["git", "-C", str(data_rod), *argv],
                              text=True, capture_output=True)

    r = git("add", "-A")
    if r.returncode != 0:
        print(f"❌ git add fejlede:\n{r.stderr}", file=sys.stderr)
        sys.exit(1)

    # Intet staged? Så er der intet at gemme.
    if git("diff", "--cached", "--quiet").returncode == 0:
        print("ℹ️  Ingen ændringer at gemme.")
        return

    antal = len([l for l in git("diff", "--cached", "--name-only").stdout.splitlines() if l.strip()])
    ord_  = "ændring" if antal == 1 else "ændringer"

    if not besked or not besked.strip():
        besked = f"opdater havedata {datetime.date.today().isoformat()}"

    r = git("commit", "-m", besked)
    if r.returncode != 0:
        print(f"❌ git commit fejlede:\n{r.stderr or r.stdout}", file=sys.stderr)
        sys.exit(1)
    print(f"  ✓ {antal} {ord_} committet: \"{besked}\"")

    r = git("push")
    if r.returncode != 0:
        print(f"⚠️  Committet lokalt, men push fejlede:\n{r.stderr.strip()}", file=sys.stderr)
        print("   Dine data er gemt lokalt — prøv igen senere med: have gem-data", file=sys.stderr)
        sys.exit(1)
    print(f"  ↑ pushet til {git('remote', 'get-url', 'origin').stdout.strip() or 'origin'}")
