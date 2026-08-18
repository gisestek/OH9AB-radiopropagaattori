"""Poimi Meshtastic-lokeista linkkihavainnot mallin validointia varten.

Syöte: MQTT:n JSON-topicista tallennettuja viestejä, joko rivi per JSON-objekti
(NDJSON) tai yksi JSON-taulukko. Tuotetaan CSV, jossa yksi rivi = yksi mitattu
radiolinkki: lähettäjän ja vastaanottajan sijainti + RSSI/SNR.

Ajo:
    python3 validate/parse_logs.py loki.ndjson --out validate/havainnot.csv

KRIITTINEN SUODATUS — miksi useimmat paketit hylätään:

1.  **Vain suorat vastaanotot kelpaavat.** RSSI mitataan viimeisellä hypyllä.
    Jos paketti tuli releen kautta, mitattu RSSI kuvaa releen ja gatewayn
    välistä linkkiä, EI alkuperäisen lähettäjän linkkiä. Tällaisen paketin
    käyttäminen pilaisi aineiston hiljaisesti. Hyväksytään vain kun
    hyppyjä = 0 (hops_away tai hop_start − hop_limit).

2.  **Jos hyppymäärää ei voi todeta, paketti hylätään.** Vanhemmissa
    firmwareissa kenttiä ei aina ole. Epävarmaa ei oteta mukaan.

3.  **Molempien päiden sijainti on tiedettävä.** Sijainnit kerätään saman
    lokin position-paketeista. Liikkuvilla asemilla käytetään ajallisesti
    lähintä sijaintia, ja sen ikä kirjataan sarakkeisiin tx_pos_age_s /
    rx_pos_age_s, jotta liian vanhat voi suodattaa myöhemmin.

Antennikorkeuksia, tehoja tai antennivahvistuksia EI ole lokeissa. Ne
annetaan erikseen solmukohtaisessa asetustiedostossa, ks. validate/README.md.

KIINTEIDEN ASEMIEN TUNNETTU SIJAINTI (--nodes):
Jos kiinteän aseman todellinen sijainti on operaattorin tiedossa, se voi
OHITTAA verkon oman position-paketin lisäämällä nodes.json:iin kentät
"lat" ja "lon". Tämä ratkaisee kaksi asiaa kerralla:

  - Meshtasticin position_precision voi sumentaa verkossa näkyvän sijainnin
    jopa ~1,5 km:iin. Tunnettu tarkka sijainti ohittaa sumennuksen täysin.
  - Jos solmu ei koskaan lähetä position-pakettia MQTT:hen (esim. GPS pois
    päältä kiinteältä asemalta), sen havainnot hylättäisiin muuten
    kokonaan ("sijainti puuttuu") — tunnetulla sijainnilla ne kelpaavat.

Ohitus koskee VAIN nodes.json:ssa nimenomaisesti mainittuja solmuja, ja se
on tarkoitettu kiinteille asemille — älä käytä sitä liikkuvaan solmuun,
koska silloin kaikki sen havainnot pinnataan yhteen väärään pisteeseen.
Ulostulon sarakkeet tx_fixed/rx_fixed kertovat auki mistä kunkin rivin
sijainti tuli, jotta ohitus ei jää piiloon datassa.
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict

# Meshtasticin position-paketit: koordinaatit kokonaislukuina, kerroin 1e-7.
COORD_SCALE = 1e-7


def node_id_to_int(value):
    """'!7efeee00' tai 2130636288 -> int. Palauttaa None jos ei tunnisteta."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s.startswith("!"):
        try:
            return int(s[1:], 16)
        except ValueError:
            return None
    try:
        return int(s)
    except ValueError:
        return None


def load_messages(path):
    """Lue NDJSON tai yksi JSON-taulukko. Palauttaa (viestit, rikkinäiset)."""
    msgs, broken = [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
            return ([m for m in data if isinstance(m, dict)], 0)
        except json.JSONDecodeError:
            pass  # yritetään silti riveittäin

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Sallitaan "topic {json}" -muotoiset rivit (esim. mosquitto_sub -v)
        if not line.startswith("{"):
            brace = line.find("{")
            if brace < 0:
                broken += 1
                continue
            line = line[brace:]
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                msgs.append(obj)
            else:
                broken += 1
        except json.JSONDecodeError:
            broken += 1
    return msgs, broken


def hops_taken(msg):
    """Hyppyjen määrä, tai None jos sitä ei voi todeta."""
    if isinstance(msg.get("hops_away"), int):
        return msg["hops_away"]
    hs, hl = msg.get("hop_start"), msg.get("hop_limit")
    if isinstance(hs, int) and isinstance(hl, int):
        return hs - hl
    return None


def get_rssi_snr(msg):
    """RSSI (dBm) ja SNR (dB) eri firmwareversioiden nimillä."""
    rssi = msg.get("rssi", msg.get("rx_rssi"))
    snr = msg.get("snr", msg.get("rx_snr"))
    rssi = float(rssi) if isinstance(rssi, (int, float)) and rssi != 0 else None
    snr = float(snr) if isinstance(snr, (int, float)) else None
    return rssi, snr


def extract_position(msg):
    """(lat, lon, alt) position-paketista, tai None."""
    p = msg.get("payload")
    if not isinstance(p, dict):
        return None
    if "latitude_i" in p and "longitude_i" in p:
        lat = p["latitude_i"] * COORD_SCALE
        lon = p["longitude_i"] * COORD_SCALE
    elif "latitude" in p and "longitude" in p:
        lat, lon = float(p["latitude"]), float(p["longitude"])
    else:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0 and lon == 0:      # tyhjä GPS-kiinnitys
        return None
    alt = p.get("altitude")
    return (lat, lon, float(alt) if isinstance(alt, (int, float)) else None)


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_position_table(msgs):
    """node_id -> [(timestamp, lat, lon, alt), ...] aikajärjestyksessä."""
    table = defaultdict(list)
    for m in msgs:
        if m.get("type") != "position":
            continue
        nid = node_id_to_int(m.get("from"))
        pos = extract_position(m)
        ts = m.get("timestamp")
        if nid is None or pos is None or not isinstance(ts, (int, float)):
            continue
        table[nid].append((float(ts), pos[0], pos[1], pos[2]))
    for nid in table:
        table[nid].sort(key=lambda r: r[0])
    return table


def load_position_overrides(nodes_path):
    """Lataa nodes.json:sta kiinteiden asemien tunnetut sijainnit.

    Palauttaa {node_id: (lat, lon)} niille solmuille, joilla on SEKÄ "lat"
    että "lon" -kentät. Näiden sijainti ohittaa verkon oman position-paketin
    kaikkina aikoina — ks. moduulin docstring miksi ja milloin tätä
    kannattaa käyttää.

    Tämä on kriittinen polku eikä vain avustava tarkistus: virheet TÄYTYY
    huomata heti, koska hiljaa läpi mennyt virhe (esim. Meshtasticin raaka
    latitudeI/longitudeI liitetty suoraan ilman 1e-7-kerrointa, tai lat/lon
    annettu liikkuvalle solmulle) pilaisi validointiaineiston näyttämättä
    mitään virhettä — tulos vain olisi väärä."""
    with open(nodes_path, encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                "%s ei jäsentynyt yhtenä JSON-oliona (%s). Yleisin syy: "
                "--nodes on saanut vahingossa lokitiedoston (NDJSON, monta "
                "JSON-riviä) argumentikseen komentorivin järjestyksen takia "
                "— esim. \"status.py --nodes logs/*.ndjson\" antaa --nodes:"
                "ille glob-osuman ENSIMMÄISEN tiedoston, ei validate/"
                "nodes.json:ia. Tarkista että --nodes osoittaa nimenomaan "
                "nodes.json-tiedostoon ja että lokipolut ovat ennen --nodes-"
                "lippua tai sen jälkeen erillisenä argumenttina."
                % (nodes_path, e))
    overrides = {}
    for key, node in cfg.get("nodes", {}).items():
        has_lat, has_lon = "lat" in node, "lon" in node
        if not has_lat and not has_lon:
            continue
        if has_lat != has_lon:
            raise ValueError(
                "%s: sekä \"lat\" että \"lon\" on annettava yhdessä, ei vain "
                "toista." % key)
        lat, lon = float(node["lat"]), float(node["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(
                "%s: lat/lon (%r, %r) on asteiden vaihteluvälin ulkopuolella. "
                "Yleisin syy: Meshtasticin RAAKA latitude_i/longitude_i-"
                "kokonaisluku liitetty suoraan — jaa se ensin 1e7:llä "
                "(esim. latitudeI 664899588 -> lat 66.4899588)."
                % (key, node["lat"], node["lon"]))
        if node.get("mobile") is True:
            raise ValueError(
                "%s: solmulla on sekä \"mobile\": true että lat/lon. "
                "Kiinteä sijainti liikkuvalle solmulle pinnaisi kaikki sen "
                "havainnot yhteen väärään pisteeseen — poista jompikumpi."
                % key)
        nid = node_id_to_int(key)
        if nid is not None:
            overrides[nid] = (lat, lon)
    return overrides


def nearest_position(table, nid, ts, overrides=None):
    """Ajallisesti lähin sijainti ja sen ikä sekunteina, tai None.

    Tunnettu kiinteä sijainti (overrides) voittaa aina verkon position-
    paketit — ikä on 0.0, koska kyse ei ole GPS-lukemasta jonka tuoreus
    vaihtelee, vaan operaattorin antamasta pysyvästä totuudesta."""
    if overrides and nid in overrides:
        lat, lon = overrides[nid]
        return (ts, lat, lon, None), 0.0
    rows = table.get(nid)
    if not rows:
        return None
    best = min(rows, key=lambda r: abs(r[0] - ts))
    return best, abs(best[0] - ts)


def parse(path, min_dist_m=50.0, max_pos_age_s=None, nodes_path=None):
    msgs, broken = load_messages(path)
    positions = build_position_table(msgs)
    overrides = load_position_overrides(nodes_path) if nodes_path else {}

    stats = {
        "viestejä": len(msgs),
        "rikkinäisiä rivejä": broken,
        "solmuja joilla sijainti": len(positions),
        "solmuja joilla kiinteä sijainti (nodes.json)": len(overrides),
        "havaintoja joissa kiinteä sijainti käytössä": 0,
        # Tähän osuvat myös paketit joissa ei ole vastaanottometatietoa
        # lainkaan, esim. gatewayn itse lähettämät.
        "ei RSSI-tietoa": 0,
        "hyppymäärä tuntematon": 0,
        "releen kautta (hyppyjä > 0)": 0,
        "lähettäjän sijainti puuttuu": 0,
        "gatewayn sijainti puuttuu": 0,
        "gateway = lähettäjä": 0,
        "liian lyhyt matka": 0,
        "sijainti liian vanha": 0,
        "kaksoiskappaleita": 0,
    }

    seen = set()
    out = []
    for m in msgs:
        rssi, snr = get_rssi_snr(m)
        if rssi is None:
            stats["ei RSSI-tietoa"] += 1
            continue

        h = hops_taken(m)
        if h is None:
            stats["hyppymäärä tuntematon"] += 1
            continue
        if h != 0:
            stats["releen kautta (hyppyjä > 0)"] += 1
            continue

        tx_id = node_id_to_int(m.get("from"))
        rx_id = node_id_to_int(m.get("sender"))
        ts = m.get("timestamp")
        if tx_id is None or rx_id is None or not isinstance(ts, (int, float)):
            stats["hyppymäärä tuntematon"] += 1
            continue
        ts = float(ts)

        if tx_id == rx_id:
            stats["gateway = lähettäjä"] += 1
            continue

        key = (m.get("id"), rx_id)
        if key in seen:
            stats["kaksoiskappaleita"] += 1
            continue
        seen.add(key)

        tx = nearest_position(positions, tx_id, ts, overrides)
        if tx is None:
            stats["lähettäjän sijainti puuttuu"] += 1
            continue
        rx = nearest_position(positions, rx_id, ts, overrides)
        if rx is None:
            stats["gatewayn sijainti puuttuu"] += 1
            continue
        (txrow, tx_age), (rxrow, rx_age) = tx, rx

        if max_pos_age_s is not None and max(tx_age, rx_age) > max_pos_age_s:
            stats["sijainti liian vanha"] += 1
            continue

        dist = haversine_m(txrow[1], txrow[2], rxrow[1], rxrow[2])
        if dist < min_dist_m:
            stats["liian lyhyt matka"] += 1
            continue

        tx_fixed, rx_fixed = tx_id in overrides, rx_id in overrides
        if tx_fixed or rx_fixed:
            stats["havaintoja joissa kiinteä sijainti käytössä"] += 1

        out.append({
            "time": int(ts),
            "tx_id": tx_id, "tx_lat": round(txrow[1], 7), "tx_lon": round(txrow[2], 7),
            "tx_gps_alt": txrow[3] if txrow[3] is not None else "",
            "tx_fixed": int(tx_fixed),
            "rx_id": rx_id, "rx_lat": round(rxrow[1], 7), "rx_lon": round(rxrow[2], 7),
            "rx_gps_alt": rxrow[3] if rxrow[3] is not None else "",
            "rx_fixed": int(rx_fixed),
            "rssi": rssi, "snr": snr if snr is not None else "",
            "dist_m": round(dist, 1),
            "tx_pos_age_s": round(tx_age, 1), "rx_pos_age_s": round(rx_age, 1),
        })

    out.sort(key=lambda r: r["time"])
    return out, stats


FIELDS = ["time", "tx_id", "tx_lat", "tx_lon", "tx_gps_alt", "tx_fixed",
          "rx_id", "rx_lat", "rx_lon", "rx_gps_alt", "rx_fixed",
          "rssi", "snr", "dist_m", "tx_pos_age_s", "rx_pos_age_s"]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Meshtastic-lokit -> linkkihavainnot mallin validointiin.")
    ap.add_argument("input", help="MQTT JSON -loki (NDJSON tai JSON-taulukko)")
    ap.add_argument("--out", required=True, help="ulostulo-CSV")
    ap.add_argument("--min-dist", type=float, default=50.0,
                    help="hylkää tätä lyhyemmät linkit (m, oletus 50)")
    ap.add_argument("--max-pos-age", type=float, default=None,
                    help="hylkää jos sijainti on tätä vanhempi (s)")
    ap.add_argument("--nodes",
                    help="nodes.json: kiinteiden asemien tunnetut sijainnit "
                         "(lat/lon) ohittavat verkon oman position-paketin")
    args = ap.parse_args(argv)

    rows, stats = parse(args.input, args.min_dist, args.max_pos_age, args.nodes)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print("Havaintoja: %d  ->  %s" % (len(rows), args.out), file=sys.stderr)
    print("\nSuodatuksen erittely (rehellinen kirjanpito):", file=sys.stderr)
    for k, v in stats.items():
        if v:
            print("  %-32s %d" % (k, v), file=sys.stderr)
    if rows:
        ds = [r["dist_m"] for r in rows]
        rs = [r["rssi"] for r in rows]
        print("\nMatkat: %.0f..%.0f m (mediaani %.0f)" %
              (min(ds), max(ds), sorted(ds)[len(ds) // 2]), file=sys.stderr)
        print("RSSI:   %.0f..%.0f dBm" % (min(rs), max(rs)), file=sys.stderr)
        nodes = sorted({r["tx_id"] for r in rows} | {r["rx_id"] for r in rows})
        print("\nSolmuja mukana: %d. Täytä niille antennikorkeudet ja tehot "
              "tiedostoon validate/nodes.json:" % len(nodes), file=sys.stderr)
        print("  " + ", ".join("!%08x" % n for n in nodes[:12])
              + (" ..." if len(nodes) > 12 else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
