"""Tarkista kerätyn aineiston kunto — ajetaan kun ystävä kysyy "toimiiko tämä".

    python3 collect/status.py logs/2026-07-26.ndjson
    python3 collect/status.py logs/*.ndjson

Kertoo kerääjittäin ja solmuittain kuinka paljon dataa on tullut, ja mikä
tärkeintä: **onko data käyttökelpoista validointiin**. Pelkkä viestimäärä ei
kerro sitä.

SIJAINTITARKKUUDEN TARKISTUS on tämän työkalun tärkein tehtävä. Meshtasticin
kanava-asetus position_precision voi sumentaa koordinaatit yksityisyyden
vuoksi, oletuksena jopa ~1,5 km. Sellaisella datalla maastoprofiili
poimittaisiin täysin väärästä paikasta, eikä sitä huomaisi mistään muusta
kuin oudon suurista jäännöksistä kalibroinnissa. Tarkkuus päätellään
koordinaattien alimmista biteistä: Meshtastic maskaa ne pois sumentaessaan.

Jos --nodes annetaan, tunnetut kiinteät sijainnit (nodes.json:n "lat"/"lon")
ohittavat tämän varoituksen niiden solmujen osalta — ei koska sumennusta ei
olisi, vaan koska sitä ei tarvitse korjata verkosta: tarkka sijainti on jo
käytössä toisaalta. Ks. validate/parse_logs.py:n docstring.
"""

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate.parse_logs import (hops_taken, load_position_overrides,  # noqa: E402
                                 node_id_to_int, parse)


def trailing_zero_bits(v):
    v = abs(int(v))
    if v == 0:
        return 32
    n = 0
    while v & 1 == 0:
        v >>= 1
        n += 1
    return n


def analyse(paths):
    per_collector = defaultdict(lambda: defaultdict(int))
    per_node = defaultdict(lambda: {
        "viestejä": 0, "positioita": 0, "kuultu": 0, "gateway": 0,
        "tz": [], "kerääjä": set()})
    hops_hist = defaultdict(int)
    total = 0

    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                total += 1
                coll = m.get("_collector", "?")
                per_collector[coll]["viestejä"] += 1

                nid = node_id_to_int(m.get("from"))
                if nid is None:
                    continue
                node = per_node[nid]
                node["viestejä"] += 1
                node["kerääjä"].add(coll)

                gw = node_id_to_int(m.get("sender"))
                if gw is not None and gw != nid:
                    per_node[gw]["gateway"] += 1
                    node["kuultu"] += 1

                h = hops_taken(m)
                hops_hist["tuntematon" if h is None else h] += 1

                if m.get("type") == "position":
                    p = m.get("payload") or {}
                    if "latitude_i" in p and "longitude_i" in p:
                        node["positioita"] += 1
                        node["tz"].append(min(trailing_zero_bits(p["latitude_i"]),
                                              trailing_zero_bits(p["longitude_i"])))
    return per_collector, per_node, hops_hist, total


def precision_verdict(tz_list):
    """Palauttaa (teksti, ongelma?) sijaintitarkkuudesta."""
    if not tz_list:
        return ("ei sijainteja", True)
    lo = min(tz_list)
    if lo <= 4:
        return ("täysi", False)
    # Meshtastic: maskaus + puolikas -> alimmat 31-precision bittiä nollia
    precision = 31 - lo
    # Sumennuksen solu on 2^(32-precision) yksikköä; raportoidaan puolikas
    # eli suurin mahdollinen virhe. 1e-7 astetta ~ 1,1 cm leveyspiirillä.
    metres = (2 ** lo) * 1.11e-2
    return ("SUMENNETTU (virhe ≤%.0f m, precision≈%d)" % (metres, precision), True)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Tarkista kerätyn Meshtastic-datan kunto.")
    ap.add_argument("logs", nargs="+", help="loki.ndjson (glob-kuviot käyvät)")
    ap.add_argument("--nodes",
                    help="nodes.json: kiinteiden asemien tunnetut sijainnit "
                         "ohittavat sumennus-/puuttumisvaroituksen niiltä osin")
    args = ap.parse_args(argv)

    paths = []
    for a in args.logs:
        paths.extend(sorted(glob.glob(a)) or [a])
    overrides = load_position_overrides(args.nodes) if args.nodes else {}

    per_collector, per_node, hops_hist, total = analyse(paths)
    if not total:
        print("Lokeista ei löytynyt yhtään viestiä.")
        return 1

    print("Lokitiedostoja: %d, viestejä: %d\n" % (len(paths), total))

    print("KERÄÄJÄT")
    for coll, d in sorted(per_collector.items(), key=lambda x: -x[1]["viestejä"]):
        print("  %-16s %6d viestiä" % (coll, d["viestejä"]))

    print("\nSOLMUT")
    print("  %-12s %7s %7s %8s %-28s %s"
          % ("solmu", "viestit", "sijainn.", "gateway", "sijaintitarkkuus", "kerääjä"))
    ongelmia = []
    for nid, d in sorted(per_node.items(), key=lambda x: -x[1]["viestejä"]):
        verdict, bad = precision_verdict(d["tz"])
        if nid in overrides:
            # Verkon oma sijainti (sumennettu tai olematon) on tässä
            # tapauksessa harmiton — nodes.json:n tarkka sijainti käytössä.
            verdict = "kiinteä (nodes.json)" + (
                " — verkko: " + verdict if d["positioita"] else ", ei verkkopositiota")
            bad = False
        if bad and d["positioita"]:
            ongelmia.append((nid, verdict))
        print("  !%08x %7d %7d %8d %-28s %s"
              % (nid, d["viestejä"], d["positioita"], d["gateway"], verdict,
                 ",".join(sorted(d["kerääjä"]))))

    print("\nHYPPYMÄÄRÄT (vain 0 kelpaa validointiin)")
    for k in sorted(hops_hist, key=lambda x: (x == "tuntematon", x)):
        print("  %-12s %6d" % (k, hops_hist[k]))

    # Lopullinen mittari: montako kelvollista havaintoa tästä irtoaa
    rows, st = parse(paths[0] if len(paths) == 1 else _merge(paths),
                     nodes_path=args.nodes)
    print("\nKÄYTTÖKELPOISIA HAVAINTOJA: %d" % len(rows))
    if rows:
        ds = sorted(r["dist_m"] for r in rows)
        print("  matkat %.1f–%.1f km (mediaani %.1f km)"
              % (ds[0] / 1000, ds[-1] / 1000, ds[len(ds) // 2] / 1000))
        kiinteita = sum(1 for r in rows if r["tx_fixed"] or r["rx_fixed"])
        if kiinteita:
            print("  joista %d käytti nodes.json:n kiinteää sijaintia" % kiinteita)

    if ongelmia:
        print("\n" + "=" * 62)
        print("ONGELMA: sijainnit on sumennettu %d solmulla." % len(ongelmia))
        print("Näistä ei saa käyttökelpoista validointidataa — maastoprofiili")
        print("poimittaisiin väärästä paikasta. Kaksi tapaa korjata:")
        print("  1) solmun omistaja: meshtastic --ch-index 0 --ch-set position_precision 32")
        print("  2) jos tiedät sijainnin itse (esim. kiinteä asema): lisää")
        print("     validate/nodes.json:iin \"lat\"/\"lon\" ja aja tämä --nodes-lipulla")
        print("=" * 62)
    return 0


def _merge(paths):
    """Yhdistä useampi loki väliaikaistiedostoksi parse():a varten."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False,
                                      encoding="utf-8")
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip().startswith("{"):
                    tmp.write(line)
    tmp.close()
    return tmp.name


if __name__ == "__main__":
    sys.exit(main())
