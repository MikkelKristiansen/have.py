# Auto-publicering på serveren (RPi5)

Når have.py kører på samme maskine som [have-inbox](../../) (fx en RPi5), kan nye
dagbogsindlæg fra telefonen publiceres automatisk: en systemd `.path`-unit
overvåger inbox-mappen og kører `have alt --lokal` (importér → gem-data → deploy),
så snart der lander et indlæg.

`--lokal` læser inbox-mappen direkte fra disk i stedet for via SFTP-loopback —
det kræver hverken SSH-nøgle eller agent og virker derfor headless.

## Filer

| Fil | Placering på Pi'en |
|-----|--------------------|
| `have-publicer.path` | `~/.config/systemd/user/have-publicer.path` |
| `have-publicer.service` | `~/.config/systemd/user/have-publicer.service` |
| `../../scripts/have-publicer.sh` | følger med repoet (kaldes af service'en) |

Stierne i unit-filerne antager installationen i `~/lokalmidler/have.py` og at
have-inbox' inbox ligger i `/home/yunohost.app/have_inbox/inbox`. Justér hvis din
opsætning afviger.

## Installation

```bash
# 1. Engangs: lad din user-systemd køre uden aktiv login-session
sudo loginctl enable-linger "$USER"

# 2. Læg unit-filerne på plads (justér stien hvis have.py ligger et andet sted)
mkdir -p ~/.config/systemd/user
cp ~/lokalmidler/have.py/conf/systemd/have-publicer.{path,service} ~/.config/systemd/user/

# 3. Aktivér overvågningen
systemctl --user daemon-reload
systemctl --user enable --now have-publicer.path
```

## Drift

```bash
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
