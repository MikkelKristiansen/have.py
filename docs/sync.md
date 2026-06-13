# Synkronisering mellem maskiner

haven køres på to maskiner — **X1** (laptop, hvor du redigerer) og **RPi5**
(server, hvor have-inbox-webappen og auto-publiceringen kører). Hele
have-træet (kode, `data/` og `fotos/`) holdes i sync af **ét** værktøj:
**Synology Drive**. Der er ingen git-data-hub og ingen rsync længere.

## Topologi

```
X1 (lokal kopi)  ⇄  Synology Drive  ⇄  DS218 (NAS)  ⇄  mount  ⇄  RPi5
~/…/have.py (X1's lokale kopi)               ~/…/have.py (RPi5: symlink → DS218-mount)
```

- **X1** har en rigtig lokal kopi som Synology Drive-klienten spejler til DS218.
- **RPi5** monterer DS218-sharet og ser samme træ via et symlink. Den har altså
  *ikke* sin egen kopi — den arbejder direkte på NAS'ens filer.
- Resultat: en ændring ét sted dukker op det andet sted, automatisk. X1 er i
  praksis altid den nyeste, fordi det er der du redigerer.

| | Transport | X1 | RPi5 |
|---|---|---|---|
| **Kode** (`have.py`) | Synology Drive | redigerer | læser (kører fra mountet) |
| **Data** (`data/`) | Synology Drive | redigerer | skriver via inbox-import |
| **Fotos** (`fotos/`) | Synology Drive | planter/baggrunde/frø | entry-/dyrefotos fra inbox |

> Versionering af data var tidligere et git-repo; nu varetages det af **Synology
> Drives egen versionshistorik** (papirkurv/versioner på DS218). Det gamle
> data-git (`data/.git` + bare-repo på RPi5) er inert og kan arkiveres/slettes.

## Hvad der IKKE skal synkroniseres

Sæt disse i Synology Drives selektive sync (ekskludér), så de ikke spejles:

| Mappe | Hvorfor |
|---|---|
| `.venv/` | venv kan ikke deles på tværs af x86 (X1) og ARM (RPi5) — hver maskine har sit eget, uden for træet (se nedenfor) |
| `out/` | genereret af build; begge maskiner bygger → ellers konflikt-filer |
| `data/.git/` | inert rest fra den gamle git-model; undgå at spejle en `.git` |
| `__pycache__/` | bytecode-cache, maskinespecifik |

`haven.yaml` og `.env` er maskinespecifik config/creds. De bør være ens nok til at
køre begge steder (relative stier), men hold `.env` (creds) ude af alt offentligt.

## venv ligger uden for træet ⚠️

Et virtuelt miljø er arkitektur- og stиafhængigt og må **aldrig** ligge i det
synkroniserede træ. Hver maskine har sit eget:

```bash
# X1
python -m venv .venv && .venv/bin/pip install -e .   # (ekskludér .venv fra Synology Drive)

# RPi5 — uden for træet, så det ikke synker til X1
python3 -m venv ~/have-venv
~/have-venv/bin/pip install -e ~/synosync/3.Resources/have.py
```

## Den daglige rytme

- **X1:** rediger frit. `have build` / `have deploy` som vanligt. Synology Drive
  bærer dine ændringer til RPi5 i baggrunden. Vil du publicere mobil-indlæg der
  ligger i inboxen manuelt: `have alt` (henter inbox via SFTP → deploy).
- **RPi5:** intet manuelt. Et nyt indlæg fra have-inbox-webappen udløser
  auto-publicering: `have alt --lokal` (importér inbox fra disk → deploy). De
  importerede data + fotos flyder tilbage til X1 via Synology Drive.

`have alt` = `hent-inbox --skriv → deploy`. Et fejlende trin stopper ikke det
øvrige; kommandoen afslutter med fejlkode hvis noget gik galt.

## Auto-publicering på RPi5

En systemd **user** `.path`-unit overvåger inbox-mappen og kører
`have-publicer.sh` (flock-beskyttet `have alt --lokal`). Opsætning, units og
drift: se [`conf/systemd/README.md`](../conf/systemd/README.md).

⚠️ **Linger skal være slået til** (`sudo loginctl enable-linger "$USER"`), ellers
kører user-systemd ikke efter en reboot uden login — og så stopper auto-deploy
lydløst. Tjek: `loginctl show-user "$USER" | grep -i Linger`.

## To skribenter på data — den ene fælde at kende

Både X1 (din redigering) og RPi5 (inbox-import) skriver i `data/`. Synology Drive
håndterer normale, tidsadskilte ændringer fint. Skriver **begge** maskiner i den
*samme fil i samme øjeblik*, laver Synology Drive en synlig konflikt-kopi
(`… (conflict).yaml`) frem for at tabe data — sjældent, og altid genoprettelig.
Kun én maskine bør auto-deploye (flock beskytter kun lokalt på RPi5).

## Backup

- **Data + fotos:** Synology Drive-versioner på DS218 + de to eksterne diske på
  arbejdet (offsite). Det er nu den eneste versionering af data.
- **Kode:** GitHub (offentligt repo, eneste skribent er X1).
