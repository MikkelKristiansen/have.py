#!/usr/bin/env bash
# have-publicer.sh — auto-publicering på serveren (RPi5).
#
# Importerer nye indlæg fra have-inbox' lokale inbox-mappe og bygger + deployer
# sitet ved at køre `have alt --lokal`. Udløses af systemd .path-unit'en
# (conf/systemd/have-publicer.path) når der lander noget i inboxen.
#
# Sync-model: koden, data/ og fotos/ bor i ét træ der synkroniseres via Synology
# Drive (X1 → DS218) og ses på RPi5 via DS218-mountet. Der er INGEN git-data og
# INGEN rsync længere — `have alt` importerer inbox og deployer; data flyder
# tilbage til X1 via Synology Drive. Derfor committer denne maskine ikke noget.
#
# flock -n sikrer at to kørsler ikke overlapper: lander flere indlæg hurtigt efter
# hinanden, eller deployer laptoppen samtidig på denne maskine, springer den
# ekstra kørsel over i stedet for at risikere dublet-import / samtidig deploy.
#
# HAVE_DIR  = haveprojektets rod (det Synology-mountede træ på RPi5).
# HAVE_VENV = det LOKALE venv (uden for træet — et venv kan ikke deles på tværs
#             af x86/ARM, og må aldrig ligge i træet, ellers synker det til X1).
# Begge kan overstyres via miljøet.
set -euo pipefail

HAVE_DIR="${HAVE_DIR:-$HOME/synosync/3.Resources/have.py}"
HAVE_VENV="${HAVE_VENV:-$HOME/have-venv}"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/have-publicer.lock"

# Mount-guard: hvis DS218-mountet ikke er oppe (fx lige efter boot eller NAS nede),
# findes haven.yaml ikke. Så springer vi pænt over i stedet for at operere på et
# tomt/manglende træ eller fejle hårdt (og brænde StartLimitBurst af).
if [ ! -f "$HAVE_DIR/haven.yaml" ]; then
    echo "⚠️  $HAVE_DIR (Synology-mountet) ser ikke ud til at være tilgængeligt — springer over."
    exit 0
fi

# Re-exec under flock (non-blocking). Konflikt-exit 75 skelner "lås optaget" fra
# en rigtig fejlkode fra `have alt`, så vi ikke fejltolker en deploy-fejl som lås.
if [ "${_HAVE_PUBLICER_LOCKED:-}" != "1" ]; then
    env _HAVE_PUBLICER_LOCKED=1 flock -n --conflict-exit-code 75 "$LOCK" "$0" "$@"
    rc=$?
    if [ "$rc" -eq 75 ]; then
        echo "ℹ️  publicering kører allerede — springer denne trigger over"
        exit 0
    fi
    exit "$rc"
fi

cd "$HAVE_DIR"
# `have alt` kalder internt `have hent-inbox`/`deploy` via PATH, så venv'ens bin/
# skal være på PATH (systemd starter os uden aktiveret venv).
export PATH="$HAVE_VENV/bin:$PATH"
exec "$HAVE_VENV/bin/have" alt --lokal
