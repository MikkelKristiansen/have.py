#!/bin/sh
# Holder have_inbox-appens dataklon frisk fra det Synology-synkede have-træ.
# Kører som system-timer under brugeren apps (ikke user-unit som på rpi5 —
# se docs/05-runbook-egne-apps.md for hvorfor lingering droppes).
# Kan kun overskrive filer der allerede findes i dataklon; det dækker
# dropdown-kilderne.
set -u
SRC=/mnt/sheevahome/Drive/synosync/3.Resources/have.py/data
DST=/srv/apps/have_inbox-data/dataklon
[ -d "$SRC" ] || exit 0   # mount nede? goer intet (appen haandterer manglende data)

# Top-niveau dropdown-/info-kilder (overskriv kun hvis de allerede findes)
for f in dyr.yaml planter.yaml kontakt.yaml om.yaml; do
  [ -f "$SRC/$f" ] && [ -f "$DST/$f" ] && cp "$SRC/$f" "$DST/$f"
done

# Aarsmapper der allerede findes i dataklon
for yd in "$DST"/[0-9][0-9][0-9][0-9]; do
  [ -d "$yd" ] || continue
  y=$(basename "$yd")
  [ -d "$SRC/$y" ] || continue
  for f in "$SRC/$y"/*.yaml; do
    [ -f "$f" ] && cp "$f" "$yd/$(basename "$f")"
  done
done
