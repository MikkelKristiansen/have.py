#!/usr/bin/env bash
# have-publicer.sh — auto-publicering på serveren (RPi5).
#
# Importerer nye indlæg fra have-inbox' lokale inbox-mappe, gemmer havedata og
# bygger + deployer sitet ved at køre `have alt --lokal`. Udløses af systemd
# .path-unit'en (conf/systemd/have-publicer.path) når der lander noget i inboxen.
#
# flock -n sikrer at to kørsler ikke overlapper: lander flere indlæg hurtigt efter
# hinanden, eller deployer laptoppen samtidig på denne maskine, springer den
# ekstra kørsel over i stedet for at risikere dublet-import / samtidig deploy.
#
# HAVE_DIR kan overstyres via miljøet; default er installationsstien på RPi5.
set -euo pipefail

HAVE_DIR="${HAVE_DIR:-$HOME/lokalmidler/have.py}"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/have-publicer.lock"

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
# `have alt` kalder internt `have hent-inbox`/`gem-data`/`deploy` via PATH, så
# venv'ens bin/ skal være på PATH (systemd starter os uden aktiveret venv).
export PATH="$HAVE_DIR/.venv/bin:$PATH"
exec "$HAVE_DIR/.venv/bin/have" alt --lokal
