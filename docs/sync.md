# Synkronisering mellem maskiner

have-træet (kode, `data/` og `fotos/`) bor i **Synology Drive** på DS218. Tre
maskiner bruger det:

| Maskine | Hvordan den ser træet | Rolle |
|---|---|---|
| **x1** (laptop) | lokal kopi via Drive-klienten | redigerer; committer kode **og** data |
| **x270** (laptop) | lokal kopi via Drive-klienten | redigerer; committer kode |
| **apps-mk** (Proxmox-VM) | DS218's CIFS-mount | have-inbox-webappen + auto-publicering |

## Topologi

```
x1   (lokal kopi) ⇄ Synology Drive ⇄ DS218 ⇄ CIFS-mount → apps-mk
x270 (lokal kopi) ⇄ Synology Drive ⇄   ↑
```

En ændring ét sted dukker automatisk op de andre steder.

## Drive synker ikke prikfiler ⚠️

Synology Drive springer **alle** filer og mapper over, der starter med punktum.
Derfor er disse **per maskine**:

| | Konsekvens |
|---|---|
| `.git` | hver laptop har sin egen klon af kode-repoet. Filer kommer via Drive, men git kender ikke andres commits. Efter arbejde på den anden laptop: `git fetch && git reset origin/main` (ikke `git pull`, git tror filerne er lokale ændringer) |
| `data/.git` | findes kun på x1, så kun x1 committer data |
| `.venv` | hver maskine har sit eget. apps-mk bruger `/srv/apps/have-venv` uden for træet |
| `.env` | deploy-creds per maskine. apps-mk har dem i `/etc/have/deploy.env` |

Ekskludér desuden `out/` og `__pycache__/` i Drives selektive sync. Begge
maskiner bygger, og ellers opstår konflikt-filer.

## Versionering

- **Kode:** GitHub, offentligt repo `MikkelKristiansen/have.py`.
- **Data:** `data/` er sit eget git-repo med remote i det **private** repo
  `MikkelKristiansen/haven-data`. Gem med `have gem-data [besked]` på x1
  (add + commit + push). Nye indlæg, som apps-mk har importeret, kommer med
  ved næste `gem-data`.
- **Fotos:** ikke i git (binære/store). Sikres af Drive-versioner på DS218 og
  de eksterne diske.

## Den daglige rytme

- **x1 / x270:** redigér frit. `have build` / `have deploy` som vanligt.
  `have alt` henter inbox'en via SFTP og deployer.
- **x1:** kør `have gem-data` en gang imellem, så data-historikken kommer offsite.
- **apps-mk:** intet manuelt. `have-publicer.timer` fejer inboxen hvert 10.
  minut og kører `have alt --lokal`. Scripts og systemd-units er versioneret
  i have-inbox-repoet (`MikkelKristiansen/have_inbox`, mappen `deploy/`), og
  dets README beskriver installation og drift.

## Flere skribenter på data

Både laptoppene og apps-mk (inbox-import) skriver i `data/`. Drive klarer
ændringer, der ikke sker samtidig. Skriver to maskiner i den *samme fil i samme
øjeblik*, laver Drive en synlig konflikt-kopi (`… (conflict).yaml`) i stedet for
at tabe data. Det sker sjældent og kan altid rettes op.

Kun apps-mk auto-deployer. `mirror --delete` betyder, at den sidste upload
vinder på webhotellet, så deploy ikke fra en laptop, mens apps-mk er i gang.
