#!/bin/sh
# Päivittää validate/havainnot.csv kaikista tähän mennessä kertyneistä
# lokeista. Tarkoitettu ajettavaksi cronista säännöllisin väliajoin, jotta
# havainnot.html näyttää tuoreen datan ilman käsin ajamista.
#
# validate/parse_logs.py ottaa vain yhden syötetiedoston, joten päivät
# yhdistetään ensin (sama menettely kuin collect/README.md:n käsiohjeessa).
# Kirjoitus on atominen: väliaikaistiedosto luodaan SAMAAN hakemistoon kuin
# lopputulos (mv samalla tiedostojärjestelmällä on atominen), jottei
# havainnot.html koskaan lue puolittain kirjoitettua CSV:tä.

set -eu
cd "$(dirname "$0")/.."

TMP_LOG=$(mktemp)
TMP_CSV=$(mktemp validate/havainnot.csv.XXXXXX)
trap 'rm -f "$TMP_LOG" "$TMP_CSV"' EXIT

cat logs/*.ndjson > "$TMP_LOG" 2>/dev/null || true
python3 validate/parse_logs.py "$TMP_LOG" --out "$TMP_CSV" --nodes validate/nodes.json

# Havaittu 2026-07-27: havainnot.csv päätyi kerran tyhjäksi (vain otsikkorivi)
# ilman että syy näkyi tässä lokissa. logs/*.ndjson kasvaa vain, joten
# havaintomäärä ei koskaan laillisesti putoa nollaan kunhan sitä on kerran
# ollut — nollarivinen tulos on siis AINA epäilyttävä eikä saa hiljaa
# ylikirjoittaa toimivaa tiedostoa.
ROWS=$(($(wc -l < "$TMP_CSV") - 1))
if [ "$ROWS" -le 0 ]; then
    echo "$(date -Is) VAROITUS: uusi tulos oli tyhjä (0 riviä) - EI " \
         "ylikirjoiteta validate/havainnot.csv:tä. Tarkista logs/*.ndjson " \
         "ja validate/nodes.json." >&2
    exit 1
fi

mv "$TMP_CSV" validate/havainnot.csv
