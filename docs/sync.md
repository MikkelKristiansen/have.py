# Synkronisering mellem maskiner

haven køres på to maskiner, og to ting skal holdes i sync: **koden** og
**havedataen**. De er to adskilte git-repos med hver sin hub, plus **fotos**
som slet ikke ligger i git. Dette dokument beskriver topologien og den
best-practice der undgår divergens og afviste pushes.

## Topologi

| | Hub (sandheden) | X1 (laptop) | RPi5 |
|---|---|---|---|
| **Kode** (`have.py`) | GitHub | dev-klon — **skriver** | klon — *kun læser* |
| **Data** (`data/`) | bare-repo på RPi5 | klon — **skriver** (`gem-data`) | klon — **skriver** (inbox auto-publicering) |
| **Fotos** (`fotos/`) | — (ikke i git) | kilde for planter/baggrunde/frø | kilde for entry-/dagbogsfotos |

- Kode-hub: GitHub (`git@github.com:<bruger>/have.py.git`)
- Data-hub: `<bruger>@<server>:/sti/til/haven-data.git` (bare-repo på RPi5)

> Konkrete hostnavne, brugernavne og stier står i den git-ignorerede `haven.yaml`
> (under `inbox:` og `fotos_arkiv:`) — bevidst holdt ude af dette offentlige repo.

Den afgørende asymmetri: **koden har reelt én skribent (X1), data har to**
(X1 + RPi5'ens auto-publicering). Derfor divergerer data, og koden ikke.

## Kode — hold det én-vejs

Rediger og commit **kun på X1**. RPi5 skal aldrig committe lokalt — kun `git pull`.
Så kan den ikke divergere fra GitHub.

For at fange uheld sættes RPi5'ens kode-repo til kun at fast-forwarde, så et
utilsigtet lokalt commit får `pull` til at fejle højlydt i stedet for at lave
et merge:

```bash
# på RPi5, i ~/lokalmidler/have.py
git config pull.ff only
```

Flow:
- **X1:** `git commit` → `git push`
- **RPi5:** `git pull` (editable install → ingen geninstallation; kun `pip install` hvis afhængigheder ændres)

## Data — rebase altid, på begge kloner

Med to skribenter er den eneste holdbare regel: **ingen merge-commits, altid
rebase oven på hub'en før push.** `gem_data()` gør allerede dette
(`add -A` → commit → `pull --rebase` → push, se `haven/deploy.py`).

Gør rebase til standard for *alle* `git pull` i data-klonen, på **begge** maskiner:

```bash
# i data-klonen på X1 (data/) OG i RPi5'ens data-klon
git config pull.rebase true
git config rebase.autoStash true
```

- `pull.rebase=true` → lineær historik uden merge-støj.
- `rebase.autoStash=true` → en `pull` fejler ikke selvom et build har efterladt
  urørte ændringer i træet.

RPi5'ens auto-publicering skal pushe via `gem_data()` (eller selv køre
`pull --rebase` før push) — ellers rammer den samme afvisning fra den anden side.

### Hvis et push alligevel afvises

Sker når hub'en er foran (typisk RPi5 har auto-publiceret imellemtiden).
`gem_data()` håndterer det nu automatisk. Manuelt:

```bash
git -C data pull --rebase   # henter remote ind, lægger dine commits ovenpå
git -C data push
```

Ved konflikt: ret filerne, `git -C data rebase --continue`, så push.

## To samlekommandoer: `sync-alt` og `alt`

De to retninger er pakket ind i hver sin kommando:

- **`have sync-alt`** — *pull-ind*: bringer denne maskine up to date.
  1. `git pull --ff-only` (kode)
  2. `git -C data pull` (data — rebaser)
  3. `have hent-inbox --skriv` (importér nye mobil-indlæg)
  4. `have sync-fotos --retning ned` (hent fotos fra arkivet)
- **`have alt`** — *publicér-ud*: `hent-inbox --skriv → gem-data → deploy`.

På RPi5 køres begge med `--lokal` (inbox læses fra disk; `sync-alt --lokal`
springer desuden fotos over, da RPi5 bruger arkivet direkte via symlink).

Et fejlende trin stopper ikke de øvrige; kommandoen afslutter med fejlkode hvis
noget gik galt.

## Daglig rytme

- **Start på X1:** `have sync-alt` — ét kald henter kode, data, inbox og fotos.
- **Slut på X1:** push koden hvis ændret; `have alt` (eller blot `have gem-data` + `have deploy`). Tilføjede du plante-/baggrunds-/frøfotos, så `have sync-fotos` (op).
- **RPi5:** `have sync-alt --lokal` for at hente ind, `have alt --lokal` for at publicere. `git pull` på koden ved kodeopdateringer.

> Hvad der **ikke** synkroniseres: `haven.yaml` og `.env` (maskinespecifik config +
> creds), `out/` (genereres af build), samt eksterne *fetches* som `hent-vejr` og
> `hent-fotos` (Wikimedia) — de følger med data-git'en når de er committet.

## Fotos — centralt arkiv på RPi5 ⚠️

Binære fotos ligger ikke i nogen af de to git-repos (kun `fotos/planter/placeholder.jpg`
er sporet). Begge maskiner deployer, så **begge skal have hele fotosættet** — og
fotos opstår *begge steder*:

- `planter/`, `baggrunde/`, `frø/` opstår på **X1**.
- `entries/{år}/` (dagbogsfotos) uploades via have-inbox og opstår på **RPi5**.

Løsningen er et centralt **billedarkiv på RPi5** der fungerer som kanonisk union,
ligesom data-hub'en:

```
~/lokalmidler/have-fotos      ← kanonisk arkiv (RPi5)
```

RPi5'ens have.py bruger arkivet **direkte** via symlink, så der kun er én kopi der:

```bash
# på RPi5, engangsopsætning
rsync -a --update ~/lokalmidler/have.py/fotos/ ~/lokalmidler/have-fotos/
rm -rf ~/lokalmidler/have.py/fotos
ln -s ../have-fotos ~/lokalmidler/have.py/fotos
```

Så skriver inbox-publiceringen entry-fotos direkte i arkivet, og RPi5'ens deploy
læser derfra — **kun X1 synkroniserer aktivt**.

### `have sync-fotos`

X1 holder sit `fotos/` i sync med arkivet via:

```bash
have sync-fotos            # op derefter ned (standard) — konvergér mod unionen
have sync-fotos --retning op    # send kun X1's nye fotos til arkivet
have sync-fotos --retning ned   # hent kun unionen ned (fx frisk maskine)
```

Konfiguration i `haven.yaml` (SSH-nøgle-auth som inbox/git):

```yaml
fotos_arkiv:
  host: <din-server>
  bruger: <bruger>
  sti: /sti/til/have-fotos
```

**Sikkerhedsmodellen:** rsync med `--update` (kun nyere overskriver) og **aldrig
`--delete`**. Derfor er begge retninger ufarlige — `op` tilføjer til arkivet uden
at slette, `ned` henter unionen uden at slette lokalt. `thumbs/` udelades (afledte,
regenereres af `have build`). Sletninger propagerer **ikke** — det er en bevidst
manuel handling på arkivet (for fotos er "forsvinder aldrig ved et uheld" netop
det man vil have).

Backup af fotos er separat og uændret: Synology Drive + eksterne diske offsite.
