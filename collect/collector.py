"""Kerää Meshtastic-viestit MQTT:stä NDJSON-lokeiksi validointia varten.

Tilaa oh9ab/# ja kirjoittaa jokaisen viestin rivinä tiedostoon
logs/YYYY-MM-DD.ndjson. Lisää kaksi kenttää, joita alkuperäisessä
viestissä ei ole:

    _rx_time    palvelimen kello viestin saapuessa (unix-sekunteja)
    _collector  kerääjän nimi topicista (oh9ab/<nimi>/...)

_rx_time on tärkeä: Meshtastic-solmun oma timestamp tulee sen kellosta,
joka voi olla pielessä tunteja jos solmulla ei ole GPS-kiinnitystä.
Palvelimen kello on luotettava, ja sitä vasten voi tarkistaa epäilyttävät
aikaleimat. Jäsennin (validate/parse_logs.py) sivuuttaa ylimääräiset
kentät, joten lokit kelpaavat sellaisenaan.

Kaksi topic-muotoa tallennetaan samaan lokiin: JSON-mirror
(.../2/json/...) sellaisenaan, ja protobuf-perustopic (.../2/e/...)
collect/mesh_decode.py:llä puretun sanakirjan JSON-serialisoituna.
Jälkimmäinen on olemassa, koska osa solmuista (havaittu 2026-07-26:
oh8efi, oh9fkj) ei koskaan julkaise JSON-mirroria vaikka protobuf tulee
luotettavasti — protobuf-topic lähtee aina kun kanavalla on
uplink_enabled, riippumatta erillisestä JSON-kytkimestä. Molemmat
tuottavat parse_logs.py:n odottaman kenttämuodon, joten se ei tarvitse
mitään muutoksia.

Ajo:  python3 collect/collector.py --host localhost --user kerays --password X
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect.mesh_decode import decode_service_envelope  # noqa: E402

running = True
stats = {"viestejä": 0, "protobuf-purettu": 0, "protobuf-ei-purkautunut": 0,
         "ei-json": 0, "alkoi": time.time()}
current = {"day": None, "fh": None}


def open_log(logdir, day):
    """Avaa päivän loki, sulje edellinen. Rivit lisätään perään, joten
    uudelleenkäynnistys ei hukkaa aiempaa dataa."""
    if current["fh"] is not None:
        current["fh"].close()
    path = Path(logdir) / ("%s.ndjson" % day)
    path.parent.mkdir(parents=True, exist_ok=True)
    current["fh"] = open(path, "a", encoding="utf-8")
    current["day"] = day
    print("[%s] loki: %s" % (datetime.now().strftime("%H:%M:%S"), path),
          file=sys.stderr, flush=True)


def on_connect(client, userdata, flags, rc, properties=None):
    ok = (rc == 0) if isinstance(rc, int) else (getattr(rc, "value", 1) == 0)
    if ok:
        client.subscribe("oh9ab/#", qos=0)
        print("Yhdistetty, tilattu oh9ab/#", file=sys.stderr, flush=True)
    else:
        print("Yhteys epäonnistui: %s (tarkista tunnus/salasana)" % rc,
              file=sys.stderr, flush=True)


def on_disconnect(client, userdata, rc, properties=None, reason=None):
    print("Yhteys katkesi (%s), paho yrittää uudelleen…" % rc,
          file=sys.stderr, flush=True)


def on_message(client, userdata, msg):
    logdir = userdata["logdir"]
    now = time.time()
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    if day != current["day"]:
        open_log(logdir, day)

    parts = msg.topic.split("/")
    if len(parts) >= 4 and parts[3] == "e":
        obj = decode_service_envelope(msg.payload)
        if obj is None:
            stats["protobuf-ei-purkautunut"] += 1
            return
        stats["protobuf-purettu"] += 1
    else:
        try:
            obj = json.loads(msg.payload.decode("utf-8", errors="replace"))
            if not isinstance(obj, dict):
                raise ValueError("ei objekti")
        except (ValueError, UnicodeDecodeError):
            stats["ei-json"] += 1
            return

    obj["_rx_time"] = round(now, 3)
    obj["_collector"] = parts[1] if len(parts) > 1 else "?"
    obj["_topic"] = msg.topic

    current["fh"].write(json.dumps(obj, ensure_ascii=False) + "\n")
    current["fh"].flush()   # kestää tappamisen kesken päivän
    stats["viestejä"] += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Meshtastic MQTT -> NDJSON.")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--logdir", default="logs")
    ap.add_argument("--stats-interval", type=int, default=3600,
                    help="tilastorivin väli sekunteina (0 = ei koskaan)")
    args = ap.parse_args(argv)

    try:   # paho-mqtt 2.x vaatii API-version, 1.x ei tunne argumenttia
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             userdata={"logdir": args.logdir})
    except AttributeError:
        client = mqtt.Client(userdata={"logdir": args.logdir})

    client.username_pw_set(args.user, args.password)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=120)

    def stop(signum, frame):
        global running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    open_log(args.logdir, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    client.connect_async(args.host, args.port, keepalive=60)
    client.loop_start()

    last_stats = time.time()
    while running:
        time.sleep(1)
        if args.stats_interval and time.time() - last_stats >= args.stats_interval:
            h = (time.time() - stats["alkoi"]) / 3600
            print("[%s] %d viestiä (%.1f/h), %d protobuf-purettu, "
                  "%d protobuf-ei-purkautunut, %d ei-json"
                  % (datetime.now().strftime("%H:%M:%S"), stats["viestejä"],
                     stats["viestejä"] / h if h > 0 else 0,
                     stats["protobuf-purettu"], stats["protobuf-ei-purkautunut"],
                     stats["ei-json"]),
                  file=sys.stderr, flush=True)
            last_stats = time.time()

    client.loop_stop()
    client.disconnect()
    if current["fh"]:
        current["fh"].close()
    print("Lopetettu. Yhteensä %d viestiä." % stats["viestejä"],
          file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
