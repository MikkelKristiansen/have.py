#!/usr/bin/env bash
# have-publicer.sh — tømmer inboxen og publicerer haven. Kører på apps-mk,
# udløst af have-publicer.timer hvert 10. minut. Installeres i /srv/apps/bin/.
#
# HELE publiceringslogikken bor her, lokalt. Tidligere var dette kun en wrapper,
# der straks exec'ede et næsten identisk script inde på DS218-mountet — og dermed
# var publiceringen afhængig af, at mountet kunne levere en EKSEKVERBAR fil. Det
# kan et CIFS-mount med file_mode=0664 aldrig: ingen fil derude har x-bit, uanset
# rettighederne på NAS'en. Vagtens `-x`-test kunne derfor aldrig blive sand, og
# publiceringen sprang over i det uendelige (fejlen 26. juli 2026 — indlæg lå og
# ventede et helt døgn). Ét script, lokalt, versionsstyret her i repoet.
#
# Tre vagter, alle med exit 0 så en sprunget kørsel ikke tæller som fejl:
#
#   1. MOUNT NEDE  → spring over. Indlæggene venter til NAS'en er vågen (den
#      sover 22.30–05.45); næste timer-kørsel tager dem. (På rpi5 var det her
#      rodårsagen til nedbruddet 5. juli 2026: en fejl brændte systemds
#      start-limit af, og så kørte timeren slet ikke mere.)
#
#   2. TOM INBOX   → spring over. Afgørende i timer-modellen: uden den ville
#      `have alt` bygge hele sitet og uploade til unoeuro HVERT 10. MINUT,
#      døgnet rundt. Med den koster en tom kørsel nogle millisekunder.
#
#   3. LÅS OPTAGET → spring over. Lander flere indlæg hurtigt efter hinanden,
#      eller deployer laptoppen samtidig, undgår vi dublet-import.
#
# Efter en vellykket publicering skrives STEMPEL_FIL. Forsiden på dagbog.mkuv.dk
# læser den og viser "sidst publiceret ..." — så en stille fejl som den 26. juli
# er synlig med det samme i stedet for at gå ubemærket hen i dagevis.
set -euo pipefail

HAVE_DIR="${HAVE_DIR:-/mnt/sheevahome/Drive/synosync/3.Resources/have.py}"
HAVE_VENV="${HAVE_VENV:-/srv/apps/have-venv}"
INBOX_DIR="${INBOX_DIR:-/srv/apps/have_inbox-data/inbox}"
STEMPEL_FIL="${STEMPEL_FIL:-$(dirname "$INBOX_DIR")/sidst-publiceret}"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/have-publicer.lock"

# 1. Er mountet oppe? haven.yaml kan kun ses hvis DS218 svarer.
if [ ! -f "$HAVE_DIR/haven.yaml" ]; then
    echo "DS218-mountet er ikke tilgaengeligt - springer over; indlaeg venter paa naeste koersel."
    exit 0
fi

# 2. Er der noget at lave?
if [ -z "$(ls -A "$INBOX_DIR" 2>/dev/null)" ]; then
    exit 0
fi

# 3. Re-exec under flock (non-blocking). Konflikt-exit 75 skelner "lås optaget"
#    fra en rigtig fejlkode ude fra `have alt`.
#    NB: `|| rc=$?` — ikke `rc=$?` på egen linje. Under `set -e` ville en simpel
#    kommando, der fejler, afbryde scriptet FØR rc kunne aflæses, og så var både
#    lås-detektionen og fejlkoden tabt.
if [ "${_HAVE_PUBLICER_LOCKED:-}" != "1" ]; then
    rc=0
    env _HAVE_PUBLICER_LOCKED=1 flock -n --conflict-exit-code 75 "$LOCK" "$0" "$@" || rc=$?
    if [ "$rc" -eq 75 ]; then
        echo "Publicering koerer allerede - springer denne trigger over."
        exit 0
    fi
    exit "$rc"
fi

echo "Indlaeg i inbox - publicerer."
cd "$HAVE_DIR"
# `have alt` kalder internt `have hent-inbox`/`deploy` via PATH, så venv'ets bin/
# skal med (systemd starter os uden aktiveret venv).
export PATH="$HAVE_VENV/bin:$PATH"
"$HAVE_VENV/bin/have" alt --lokal

# Kun nået hvis `have alt` gik godt — ellers har `set -e` afbrudt os ovenfor,
# og stemplet forbliver gammelt. Det er med vilje: et gammelt stempel er præcis
# det signal, forsiden skal kunne vise.
date --iso-8601=seconds > "$STEMPEL_FIL"
echo "Publiceret OK."
