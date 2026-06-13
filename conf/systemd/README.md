# Auto-publicering på serveren (RPi5)

Når have.py kører på samme maskine som [have-inbox](../../) (fx en RPi5), kan nye
dagbogsindlæg fra telefonen publiceres automatisk: en systemd `.path`-unit
overvåger inbox-mappen og kører `have alt --lokal` (importér → deploy), så snart
der lander et indlæg.

`--lokal` læser inbox-mappen direkte fra disk i stedet for via SFTP-loopback —
det kræver hverken SSH-nøgle eller agent og virker derfor headless.

## Sync-model

Koden, `data/` og `fotos/` bor i ét træ der synkroniseres via **Synology Drive**
(X1 → DS218) og ses på RPi5 via DS218-mountet. Der er **ingen git-data** og
**ingen rsync** — `have alt --lokal` importerer inboxen og deployer; de nye data
og fotos flyder tilbage til X1 via Synology Drive. RPi5 committer ingenting.

⚠️ **venv'et må ligge uden for det synkroniserede træ** (fx `~/have-venv`). Et venv
kan ikke deles på tværs af x86 (X1) og ARM (RPi5), og lå det i træet, ville det
synke til X1. `have-publicer.sh` peger på `$HAVE_VENV` (default `~/have-venv`).

## Filer

| Fil | Placering på Pi'en |
|-----|--------------------|
| `have-publicer.path` | `~/.config/systemd/user/have-publicer.path` |
| `have-publicer.service` | `~/.config/systemd/user/have-publicer.service` |
| `../../scripts/have-publicer.sh` | følger med repoet (kaldes af service'en) |

Stierne i unit-filerne antager have-træet i `~/synosync/3.Resources/have.py`
(Synology-mountet), venv'et i `~/have-venv`, og at have-inbox' inbox ligger i
`/home/yunohost.app/have_inbox/inbox`. Justér hvis din opsætning afviger.

## Installation

```bash
# 1. Lav et LOKALT venv uden for det synkroniserede træ og installér have editable
python3 -m venv ~/have-venv
~/have-venv/bin/pip install -e ~/synosync/3.Resources/have.py

# 2. Engangs: lad din user-systemd køre uden aktiv login-session (overlever reboot)
sudo loginctl enable-linger "$USER"

# 3. Læg unit-filerne på plads (justér stierne hvis dit mount/venv ligger andetsteds)
mkdir -p ~/.config/systemd/user
cp ~/synosync/3.Resources/have.py/conf/systemd/have-publicer.{path,service} ~/.config/systemd/user/

# 4. Aktivér overvågningen
systemctl --user daemon-reload
systemctl --user enable --now have-publicer.path
```

## Drift

```bash
loginctl show-user "$USER" | grep -i linger    # Linger=yes? (ellers dør den ved reboot)
systemctl --user status have-publicer.path      # er overvågningen aktiv?
systemctl --user start have-publicer.service    # kør en publicering manuelt nu
journalctl --user -u have-publicer.service -f    # se logs live
```

`flock` i `have-publicer.sh` sikrer at to publiceringer ikke kører oveni hinanden.
Kører laptoppen `have deploy` samtidig (en anden maskine), beskytter flock ikke
på tværs af maskiner — kør derfor kun automatisk publicering ét sted.

## Afinstallation

```bash
systemctl --user disable --now have-publicer.path
rm ~/.config/systemd/user/have-publicer.{path,service}
systemctl --user daemon-reload
```
