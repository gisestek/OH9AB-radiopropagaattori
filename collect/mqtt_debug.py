"""Debug-työkalu: miksi jonkun kerääjän data ei näy?

Automatisoi sen päättelyketjun, joka muuten pitäisi tehdä käsin
mosquitto_sub:lla ja journalctl:lla joka kerta uudestaan. Käyttää valmiiksi
olemassa olevaa "kerays"-tunnusta, jolla on lukuoikeus koko oh9ab/#-puuhun —
ACL:ää ei tarvitse koskea.

Ajo (palvelimella):
    python3 collect/mqtt_debug.py                    # kaikki kerääjät, 60 s
    python3 collect/mqtt_debug.py oh8efi              # vain yksi kerääjä
    python3 collect/mqtt_debug.py oh8efi --seconds 180
    python3 collect/mqtt_debug.py --raw               # näytä myös payloadit

MITÄ SE TEKEE:
1. Tarkistaa mosquitton omasta lokista (journalctl -u mosquitto), onko
   kerääjä ylipäätään yhdistänyt äskettäin, ja kuinka usein — paljastaa
   "ei yhteyttä ollenkaan" ja "yhdistää mutta katkeilee jatkuvasti".
2. Kuuntelee live-liikennettä oh9ab/#-puusta annetun ajan ja luokittelee
   jokaisen viestin: mistä kerääjästä, JSON vai protobuf (Meshtastic
   julkaisee saman paketin kahteen rinnakkaiseen topiciin: .../2/e/... on
   salattu protobuf, .../2/json/... on JSON — molempien pitäisi tulla jos
   JSON-ulostulo on päällä laitteella).
3. Antaa lopuksi yhden konkreettisen johtopäätöksen per kerääjä:
     - ei yhteyttä mosquittoon -> tarkista tunnus/salasana/verkko solmulla
     - yhdistää mutta katkeilee -> puhelimen sovellus/verkko epävakaa
     - vain protobufia, ei JSONia -> EI HAITTAA (collect/mesh_decode.py
       purkaa protobufin suoraan). Selvisi 2026-07-27: nRF52-pohjaiset
       laitteet (esim. RAK4631) EIVÄT TUE JSON-ulostuloa lainkaan
       (laiteohjelmiston muistirajoitus) — julkaisevat aina vain
       protobufia. ESP32-pohjaisilla laitteilla kyse voi silti olla
       aktivoitumattomasta JSON-kytkimestä.
     - JSONia näkyy -> toimii, kärsivällisyyttä (havaintotiheys riippuu
       solmun lähetysvälistä)

Tämä EI vaadi ACL-muutoksia, koska kerays näkee jo koko oh9ab/#-puun. Jos
epäilet solmun julkaisevan väärään topic-juureen (esim. oh9ab/oh8efi:n
sijaan johonkin muuhun), sekään ei näkyisi tässä — silloin ainoa keino on
tilapäisesti laajentaa kerays:n ACL "topic read #" ja kuunnella koko
brokeria, ks. collect/README.md.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from collections import defaultdict

import paho.mqtt.client as mqtt

SECRET_PATH = "/etc/mosquitto/kerays.secret"

TOPIC_RE = re.compile(
    r'^(?P<root>[^/]+)/(?P<collector>[^/]+)'
    r'(?:/(?P<version>[^/]+)/(?P<fmt>[^/]+)/(?P<channel>[^/]+)/(?P<node>[^/]+))?$')


def classify_topic(topic):
    """Pura topic osiin. Tunnetut kentät None jos topic on lyhyempi kuin
    Meshtasticin tavallinen <root>/<kerääjä>/2/<e|json>/<kanava>/<solmu>."""
    m = TOPIC_RE.match(topic)
    if not m:
        return {"root": None, "collector": None, "version": None,
                "fmt": None, "channel": None, "node": None}
    return m.groupdict()


def read_secret():
    try:
        with open(SECRET_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        raise SystemExit(
            "Ei voitu lukea %s: %s\n"
            "Tämä työkalu käyttää kerays-tunnusta, jonka salasana on siinä "
            "tiedostossa (setup_server.sh luo sen)." % (SECRET_PATH, e))


def fetch_connection_log(since_minutes=60):
    """mosquitto-yksikön yhteyslogi tekstinä, tai '' jos ei saatavilla."""
    try:
        r = subprocess.run(
            ["sudo", "journalctl", "-u", "mosquitto",
             "--since", "%d minutes ago" % since_minutes, "--no-pager"],
            capture_output=True, text=True, timeout=15)
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


CONNECT_RE = re.compile(
    r"^(\w+ +\d+ [\d:]+) .*New client connected .*u'([^']+)'", re.M)
DISCONNECT_NOTAUTH_RE = re.compile(r"disconnected, not authorised")


def parse_connection_log(text, collector):
    """(yhteyksiä, viimeisin_rivi) annetulle kerääjätunnukselle.

    Pelkkä pieni parsintafunktio erillään journalctl-kutsusta, jotta sitä
    voi testata ilman oikeaa mosquittoa/sudo:a."""
    hits = [(ts, name) for ts, name in CONNECT_RE.findall(text) if name == collector]
    last = hits[-1][0] if hits else None
    return len(hits), last


# Oma admin-tunnus, ei kenenkään oikea Meshtastic-solmu — jätetään pois
# automaattisesta listauksesta, koska TÄMÄ TYÖKALU ITSE yhdistää sillä
# joka ajolla ja saisi muuten aina turhan "ei julkaise mitään" -varoituksen.
RESERVED_ACCOUNTS = {"kerays"}


def resolve_names(targets, seen_order, stat_keys, conn_keys):
    """Ketkä raportoidaan yhteenvedossa.

    Erillinen testattava funktio, koska tässä oli aiemmin bugi: tyhjä
    live-liikenneikkuna (0 viestiä) pudotti pöydältä myös ne kerääjät,
    jotka näkyivät yhteyshistoriassa — juuri se tapaus jota tätä työkalua
    eniten tarvitaan (yhdistää muttei julkaise)."""
    if targets:
        return list(targets)
    if seen_order:
        return [n for n in seen_order if n not in RESERVED_ACCOUNTS]
    return sorted((set(stat_keys) | set(conn_keys)) - RESERVED_ACCOUNTS)


def verdict(collector, n_connections, n_json, n_protobuf, n_other):
    """Yksi ihmisluettava johtopäätös — tämä on työkalun koko pointti."""
    if n_connections == 0 and n_json == 0 and n_protobuf == 0 and n_other == 0:
        return ("EI YHTEYTTÄ mosquittoon havaintoikkunassa. Tarkista solmulta "
                "tunnus, salasana ja että sillä on internet-yhteys.")
    if n_json == 0 and n_protobuf == 0 and n_other == 0:
        casing_hint = (" TARKISTA MYÖS: onko \"Palvelimen osoite (root topic)\" "
                      "kirjoitettu TÄSMÄLLEEN pienillä kirjaimilla "
                      "(esim. \"oh9ab/%s\", ei \"OH9AB/%s\")? MQTT-topicit "
                      "ovat kirjainkokoriippuvaisia — isolla kirjoitettu "
                      "julkaisisi täysin eri, näkymättömään polkuun. Tämä on "
                      "todettu oikeaksi syyksi kerran jo (oh9fkj, 2026-07-26)."
                      % (collector, collector))
        if n_connections >= 3:
            return ("Yhdistää TOISTUVASTI (%d kertaa) muttei julkaise mitään. "
                    "Todennäköisesti puhelimen sovellus tai verkkoyhteys on "
                    "epävakaa — tarkista pysyykö Meshtastic-sovellus auki "
                    "eikä akunsäästö sulje sitä." % n_connections + casing_hint)
        return ("Yhdistää mosquittoon mutta ei ole julkaissut mitään tässä "
                "ikkunassa. Voi olla vain harva lähetysväli — odota "
                "pidempään, tai tarkista mqtt.enabled/uplink_enabled "
                "kanavalta." + casing_hint)
    if n_json == 0 and (n_protobuf > 0 or n_other > 0):
        return ("Protobuf-paketteja näkyy (%d) mutta JSON-kopiota EI YHTÄÄN. "
                "EI HAITTAA validointia — collect/collector.py purkaa "
                "protobufin suoraan (collect/mesh_decode.py), JSONia ei "
                "tarvita. Todettu syy (2026-07-27): nRF52-pohjaiset "
                "laitteet (esim. RAK4631) EIVÄT TUE JSON-ulostuloa "
                "lainkaan muistirajoitusten takia — julkaisevat aina vain "
                "protobufia riippumatta asetuksista. Jos laite on "
                "ESP32-pohjainen, kyse voi silti olla siitä ettei "
                "JSON-kytkin ole oikeasti aktivoitunut — kokeile silloin "
                "kytkeä se pois/päälle ja käynnistä solmu uudelleen."
                % n_protobuf)
    return "OK: JSON-viestejä %d kpl tässä ikkunassa." % n_json


def listen(seconds, only_collector, show_raw):
    password = read_secret()
    topic = "oh9ab/%s/#" % only_collector if only_collector else "oh9ab/#"

    stats = defaultdict(lambda: {"json": 0, "protobuf": 0, "other": 0,
                                 "nodes": set(), "channels": set()})
    seen_order = []

    def on_connect(client, userdata, flags, rc, properties=None):
        ok = (rc == 0) if isinstance(rc, int) else (getattr(rc, "value", 1) == 0)
        if ok:
            client.subscribe(topic, qos=0)
            print("[debug] yhdistetty, tilattu %s (%d s)..." % (topic, seconds))
        else:
            raise SystemExit("[debug] kerays-yhteys epäonnistui: %s "
                             "(onko kerays.secret ajan tasalla?)" % rc)

    def on_message(client, userdata, msg):
        parts = classify_topic(msg.topic)
        coll = parts["collector"] or "?"
        if coll not in stats:
            seen_order.append(coll)
        s = stats[coll]
        if parts["channel"]:
            s["channels"].add(parts["channel"])
        if parts["node"]:
            s["nodes"].add(parts["node"])

        is_json_payload = False
        try:
            json.loads(msg.payload.decode("utf-8"))
            is_json_payload = True
        except (ValueError, UnicodeDecodeError):
            pass

        if is_json_payload:
            s["json"] += 1
            kind = "JSON"
        elif parts["fmt"] == "e":
            s["protobuf"] += 1
            kind = "protobuf"
        else:
            s["other"] += 1
            kind = "muu/tuntematon"

        ts = time.strftime("%H:%M:%S")
        line = "[%s] %-10s %-16s topic=%s (%d B)" % (
            ts, coll, kind, msg.topic, len(msg.payload))
        print(line)
        if show_raw and is_json_payload:
            print("           " + msg.payload.decode("utf-8", errors="replace")[:200])

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.username_pw_set("kerays", password)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("localhost", 1883, keepalive=30)
    client.loop_start()
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        print("\n[debug] keskeytetty käyttäjän toimesta.")
    client.loop_stop()
    client.disconnect()
    return stats, seen_order


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Debugaa miksi jonkun kerääjän MQTT-data ei näy.")
    ap.add_argument("collector", nargs="?",
                    help="tarkista vain tämä kerääjä (oletus: kaikki)")
    ap.add_argument("--seconds", type=int, default=60,
                    help="kuunteluaika sekunteina (oletus 60)")
    ap.add_argument("--raw", action="store_true",
                    help="näytä myös JSON-payloadien alku")
    ap.add_argument("--conn-window", type=int, default=60,
                    help="montako minuuttia yhteyshistoriaa tarkistetaan "
                         "(oletus 60)")
    args = ap.parse_args(argv)

    targets = [args.collector] if args.collector else None

    print("=== 1/2: yhteyshistoria (viimeiset %d min) ===" % args.conn_window)
    conn_text = fetch_connection_log(args.conn_window)
    conn_counts = {}
    if not conn_text:
        print("(journalctl ei ollut saatavilla — ohitetaan tämä osa)")
    else:
        names_seen = targets or sorted(
            {n for _, n in CONNECT_RE.findall(conn_text)} - RESERVED_ACCOUNTS)
        for name in names_seen:
            n, last = parse_connection_log(conn_text, name)
            conn_counts[name] = n
            print("  %-12s %3d yhteyttä, viimeisin: %s" % (name, n, last or "-"))

    print("\n=== 2/2: live-liikenne oh9ab/#-puusta ===")
    stats, seen_order = listen(args.seconds, args.collector, args.raw)

    print("\n=== YHTEENVETO ===")
    names = resolve_names(targets, seen_order, stats.keys(), conn_counts.keys())
    if not names:
        print("Ei nähty yhtään kerääjää liikenteessä eikä yhteyshistoriassa.")
        return 1

    any_problem = False
    for name in names:
        s = stats.get(name, {"json": 0, "protobuf": 0, "other": 0,
                             "nodes": set(), "channels": set()})
        nconn = conn_counts.get(name, 0)
        print("\n%s:" % name)
        print("  yhteyksiä (%dmin): %d   JSON: %d   protobuf: %d   muu: %d"
              % (args.conn_window, nconn, s["json"], s["protobuf"], s["other"]))
        if s["nodes"]:
            print("  solmuja nähty: %s" % ", ".join(sorted(s["nodes"])))
        v = verdict(name, nconn, s["json"], s["protobuf"], s["other"])
        print("  -> " + v)
        if not v.startswith("OK"):
            any_problem = True

    return 1 if any_problem else 0


if __name__ == "__main__":
    # Ilman tätä stdout on lohkopuskuroitu kun se ei mene suoraan
    # päätteeseen (esim. SSH:n yli ajettuna tiedostoon ohjattuna) —
    # elävä liikenne ei näkyisi ennen kuin koko ajo on jo päättynyt,
    # mikä tekisi juuri tästä debug-työkalusta hyödyttömän reaaliaikaisena.
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
