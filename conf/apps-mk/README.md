# Auto-publicering på apps-mk

apps-mk (Proxmox-VM, `/srv/apps`) kører have-inbox-webappen. Den publicerer
også nye dagbogsindlæg fra telefonen: en timer fejer inboxen hvert 10. minut,
og hvis der ligger noget, kører den `have alt --lokal` (importér → deploy).

Filerne her er **nøjagtige kopier** af dem, der kører på serveren. Ret dem her,
kopiér dem derud, og hold dem ens. `diff` mod serveren viser, om de er gledet
fra hinanden (se nederst).

## Filer

| Fil | Placering på apps-mk | Gør |
|-----|----------------------|-----|
| `have-publicer.sh` | `/srv/apps/bin/` | Tømmer inboxen og publicerer (tre vagter: mount nede, tom inbox, lås optaget) |
| `have-publicer.service` | `/etc/systemd/system/` | Kører scriptet som `apps`, med creds fra `/etc/have/deploy.env` |
| `have-publicer.timer` | `/etc/systemd/system/` | Hvert 10. minut |
| `have-dataklon-refresh.sh` | `/srv/apps/bin/` | Kopierer YAML-filer fra have-træet til appens dataklon (dropdowns) |
| `have-dataklon-refresh.service` | `/etc/systemd/system/` | Kører scriptet som `apps` |
| `have-dataklon-refresh.timer` | `/etc/systemd/system/` | Hvert 10. minut |

`/etc/have/deploy.env` (`HAVE_SFTP_KODE`/`HAVE_FTP_KODE`, chmod 600) ligger
kun på serveren og hører **aldrig** til i repoet.

## Forudsætninger

- have-træet ses via DS218's CIFS-mount på
  `/mnt/sheevahome/Drive/synosync/3.Resources/have.py`. Mountet giver ingen
  x-bit, så scriptene skal ligge lokalt i `/srv/apps/bin/`, ikke køres fra mountet.
- Et lokalt venv uden for træet: `/srv/apps/have-venv`
  (`python3 -m venv /srv/apps/have-venv && /srv/apps/have-venv/bin/pip install -e <have-træet>`).
- Der må **ikke** ligge en `.env` i have-træet med creds, der skal bruges her:
  `config.py` indlæser `.env` med `override=True` og ville overskrive dem fra
  `deploy.env`. (Drive synker ikke `.env`, så i praksis ligger der ingen.)
- apps-mk committer **ikke** data. Importerede indlæg flyder via Drive til x1,
  hvor `have gem-data` gemmer dem i det private haven-data-repo.

## Installation / opdatering

```bash
# fra x1, i have.py
scp conf/apps-mk/*.sh apps@apps-mk.lan:/srv/apps/bin/
scp conf/apps-mk/*.service conf/apps-mk/*.timer root@apps-mk.lan:/etc/systemd/system/
ssh root@apps-mk.lan 'systemctl daemon-reload && systemctl enable --now have-publicer.timer have-dataklon-refresh.timer'
```

## Drift

```bash
systemctl list-timers 'have*'                      # næste kørsel
systemctl start have-publicer.service              # publicér nu
journalctl -u have-publicer.service -n 50          # log
cat /srv/apps/have_inbox-data/sidst-publiceret     # sidste vellykkede publicering
```

Er repoet og serveren ens?

```bash
for f in have-publicer.sh have-dataklon-refresh.sh; do
  ssh apps@apps-mk.lan cat /srv/apps/bin/$f | diff -q - conf/apps-mk/$f; done
for f in conf/apps-mk/*.service conf/apps-mk/*.timer; do
  ssh apps@apps-mk.lan cat /etc/systemd/system/$(basename $f) | diff -q - $f; done
```

Drift-overblikket over alle apps på apps-mk står i repoet `ynh2proxmox`
(`docs/drift/egne-apps.md`).
