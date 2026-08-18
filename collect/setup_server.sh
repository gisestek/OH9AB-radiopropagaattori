#!/bin/bash
# Pystytä MQTT-keruupalvelin. Ajetaan kerran, sudolla.
#
#   sudo collect/setup_server.sh
#
# Luo: mosquitto-asetukset, ACL-pohjan, "kerays"-tunnuksen (jolla oma
# collector.py lukee kaiken) ja systemd-palvelun kerääjälle.
# Yksittäiset datankerääjät lisätään erikseen: sudo collect/add_collector.sh <nimi>

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNUSER="${SUDO_USER:-claude}"
LOGDIR="$REPO/logs"

if [ "$(id -u)" -ne 0 ]; then
    echo "Aja sudolla: sudo $0" >&2
    exit 1
fi

echo "== 1/4 mosquitto-asetukset =="
cp "$REPO/collect/mosquitto-oh9ab.conf" /etc/mosquitto/conf.d/oh9ab.conf

if [ ! -f /etc/mosquitto/oh9ab.acl ]; then
    cat > /etc/mosquitto/oh9ab.acl <<'ACLEOF'
# OH9AB-mittausdatan ACL.
# Kerääjäkohtaiset säännöt lisätään add_collector.sh:lla.
# Jokainen kerääjä saa kirjoittaa vain omaan juureensa, jotta yhden
# tunnuksen vuoto ei anna mahdollisuutta sotkea muiden dataa.

user kerays
topic read oh9ab/#
ACLEOF
    echo "  ACL luotu"
else
    echo "  ACL on jo olemassa, ei koskettu"
fi

echo "== 2/4 kerays-tunnus (oman kerääjän lukuoikeus) =="
touch /etc/mosquitto/oh9ab.passwd
if [ -f /etc/mosquitto/kerays.secret ]; then
    echo "  salasana on jo olemassa, säilytetään"
else
    # Pythonilla eikä tr|head:llä: jälkimmäisessä head sulkee putken ja
    # tr saa SIGPIPEn, mikä kaataa skriptin pipefailin kanssa.
    KERAYS_PASS="$(python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("".join(secrets.choice(a) for _ in range(28)))')"
    mosquitto_passwd -b /etc/mosquitto/oh9ab.passwd kerays "$KERAYS_PASS"
    printf '%s\n' "$KERAYS_PASS" > /etc/mosquitto/kerays.secret
    chown "$RUNUSER":"$RUNUSER" /etc/mosquitto/kerays.secret
    chmod 600 /etc/mosquitto/kerays.secret
    echo "  luotu"
fi
chown mosquitto:mosquitto /etc/mosquitto/oh9ab.passwd /etc/mosquitto/oh9ab.acl
chmod 600 /etc/mosquitto/oh9ab.passwd
chmod 640 /etc/mosquitto/oh9ab.acl

echo "== 3/4 mosquitto käyntiin =="
systemctl restart mosquitto
sleep 1
systemctl is-active --quiet mosquitto && echo "  mosquitto käynnissä"

echo "== 4/4 kerääjäpalvelu =="
mkdir -p "$LOGDIR"
chown "$RUNUSER":"$RUNUSER" "$LOGDIR"
cat > /etc/systemd/system/oh9ab-collector.service <<SVCEOF
[Unit]
Description=OH9AB Meshtastic MQTT -> NDJSON kerääjä
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
User=$RUNUSER
WorkingDirectory=$REPO
ExecStart=/bin/sh -c '/usr/bin/python3 $REPO/collect/collector.py \\
    --host localhost --user kerays \\
    --password "\$(cat /etc/mosquitto/kerays.secret)" \\
    --logdir $LOGDIR'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF
systemctl daemon-reload
systemctl enable --now oh9ab-collector.service
sleep 2
systemctl is-active --quiet oh9ab-collector.service \
    && echo "  kerääjä käynnissä, lokit: $LOGDIR" \
    || { echo "  kerääjä EI käynnistynyt:"; journalctl -u oh9ab-collector -n 20 --no-pager; exit 1; }

cat <<EOF

Valmis. Lisää datankerääjä komennolla:

    sudo $REPO/collect/add_collector.sh <nimi>

(oletusosoite on propagation.rupsu.fi; OH9AB_MQTT_HOST=<muu> ohittaa sen)

Tarkista aineiston kunto:

    python3 $REPO/collect/status.py $LOGDIR/*.ndjson
EOF
