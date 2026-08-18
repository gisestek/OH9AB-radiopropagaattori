"""Tarkista validate/nodes.json käsinmuokkauksen jälkeen.

Ajo:
    python3 validate/check_nodes.py validate/nodes.json

Tarkoitus on tehdä käsinmuokkauksesta turvallista: tiedosto ei ole minkään
lomakkeen takana, joten yleisimmät virheet (pilkku puuttuu, kenttä
väärässä muodossa, sama avain kahdesti) huomataan vasta kun jotain menee
pieleen jäännöstilastoissa — jos silloinkaan. Tämä työkalu nappaa ne heti.

Tarkistukset:

  - JSON-syntaksi: virheilmoitus rivi- ja sarakenumerolla, ei pelkkä
    Pythonin oma jargon.
  - Duplikaattiavaimet: JSON-standardi hyväksyy ne hiljaa ja jälkimmäinen
    voittaa. Se on lähes aina vahinko (esim. sama solmu liitetty kahdesti
    eri kohtiin tiedostoa), joten siitä huomautetaan.
  - Tuntemattomat kentät: todennäköisin syy on kirjoitusvirhe kentän
    nimessä (esim. "antenna_height" ilman "_m"-päätettä hiljaisesti
    ohitettaisiin eikä vaikuttaisi mihinkään).
  - Numerokentät jotka eivät ole numeroita, "pol" muu kuin 1/2,
    "mobile" muu kuin true/false.
  - Solmutunnuksen muoto ("!" + 8 heksamerkkiä).
  - lat/lon-turvatarkistukset: KÄYTTÄÄ SAMAA load_position_overrides-
    funktiota kuin oikea validointiputki, joten tarkistus ja todellinen
    käyttäytyminen eivät voi valua erilleen. Nämä ovat virheitä (eivät
    varoituksia), koska ne pilaisivat tuloksen näyttämättä mitään:
      * lat ilman lon:ia tai päinvastoin
      * lat/lon asteiden vaihteluvälin ulkopuolella — yleisin syy on
        Meshtasticin RAAKA latitude_i/longitude_i liitetty suoraan ilman
        1e-7-kerrointa
      * "mobile": true yhdessä lat/lon:in kanssa
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from validate.parse_logs import load_position_overrides, node_id_to_int  # noqa: E402

NODE_ID_RE = re.compile(r'^![0-9a-fA-F]{8}$')

NUMERIC_FIELDS = {"antenna_height_m", "antenna_gain_dbi", "tx_power_dbm",
                  "cable_loss_db", "freq_mhz", "lat", "lon"}
KNOWN_FIELDS = NUMERIC_FIELDS | {"name", "shortname", "mobile", "note", "pol"}


def load_json_report_duplicates(path):
    """Lataa JSON:n ja kerää duplikaattiavaimet (mistä tahansa syvyydestä).

    Palauttaa (data, duplikaattiavaimet). JSON-syntaksivirheestä nostetaan
    ValueError selkeällä rivi/sarake-viestillä."""
    dups = []

    def hook(pairs):
        seen = set()
        d = {}
        for k, v in pairs:
            if k in seen:
                dups.append(k)
            seen.add(k)
            d[k] = v
        return d

    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        data = json.loads(text, object_pairs_hook=hook)
    except json.JSONDecodeError as e:
        raise ValueError(
            "JSON-syntaksivirhe: rivi %d, sarake %d: %s" % (e.lineno, e.colno, e.msg))
    return data, dups


def _check_entry(label, entry, errors, warnings):
    if not isinstance(entry, dict):
        errors.append("%s: arvon pitää olla objekti {...}, oli %s"
                      % (label, type(entry).__name__))
        return
    for field, value in entry.items():
        if field not in KNOWN_FIELDS:
            warnings.append("%s: tuntematon kenttä \"%s\" — kirjoitusvirhe? "
                            "Tunnetut kentät: %s"
                            % (label, field, ", ".join(sorted(KNOWN_FIELDS))))
            continue
        if field in NUMERIC_FIELDS and not isinstance(value, (int, float)):
            errors.append("%s.%s: pitäisi olla luku, oli %r" % (label, field, value))
        elif field == "pol" and value not in (1, 2):
            errors.append("%s.pol: pitää olla 1 (horisontaali) tai 2 "
                          "(vertikaali), oli %r" % (label, value))
        elif field == "mobile" and not isinstance(value, bool):
            errors.append("%s.mobile: pitää olla true/false, oli %r" % (label, value))


def check(path):
    """Palauttaa (errors, warnings, overrides). overrides on tyhjä jos
    lat/lon-tarkistus epäonnistui (virhe on jo errors-listalla)."""
    errors, warnings = [], []
    try:
        data, dups = load_json_report_duplicates(path)
    except ValueError as e:
        return [str(e)], [], {}

    for k in dups:
        warnings.append(
            "Duplikaattiavain \"%s\" — JSON hyväksyy sen hiljaa ja "
            "jälkimmäinen arvo voittaa. Tarkista ettei tämä ole vahinko." % k)

    if not isinstance(data, dict) or "nodes" not in data:
        errors.append("Tiedostosta puuttuu \"nodes\"-objekti kokonaan.")
        return errors, warnings, {}

    if "defaults" in data:
        _check_entry("defaults", data["defaults"], errors, warnings)

    nodes = data["nodes"]
    if not isinstance(nodes, dict):
        errors.append("\"nodes\" pitää olla objekti {\"!xxxxxxxx\": {...}, ...}.")
        return errors, warnings, {}

    for key, node in nodes.items():
        if not NODE_ID_RE.match(key):
            warnings.append(
                "\"%s\": solmutunnus ei näytä Meshtastic-muodolta "
                "(pitäisi olla \"!\" + 8 heksamerkkiä, esim. \"!da5afd20\")" % key)
        elif node_id_to_int(key) is None:
            errors.append("\"%s\": solmutunnusta ei voitu tulkita." % key)
        _check_entry(key, node, errors, warnings)

    try:
        overrides = load_position_overrides(path)
    except ValueError as e:
        errors.append(str(e))
        overrides = {}

    return errors, warnings, overrides


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("Käyttö: python3 validate/check_nodes.py validate/nodes.json",
              file=sys.stderr)
        return 2
    path = argv[0]

    errors, warnings, overrides = check(path)

    if not errors and not warnings:
        print("OK: %s — ei huomautettavaa." % path)
    if warnings:
        print("VAROITUKSIA (%d) — tarkista, mutta eivät välttämättä riko mitään:"
              % len(warnings))
        for w in warnings:
            print("  ! " + w)
    if errors:
        print("\nVIRHEITÄ (%d) — nämä TÄYTYY korjata, muuten tulos on hiljaa väärä:"
              % len(errors))
        for e in errors:
            print("  ✗ " + e)

    if overrides:
        print("\nKiinteä sijainti käytössä %d solmulla:" % len(overrides))
        for nid, (lat, lon) in sorted(overrides.items()):
            print("  !%08x  %.7f, %.7f" % (nid, lat, lon))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
