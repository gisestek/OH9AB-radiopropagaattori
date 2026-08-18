#!/bin/bash
# Lisää uusi datankerääjä: luo MQTT-tunnuksen, ACL-säännön ja tulostaa
# valmiit asetuskomennot ystävälle lähetettäväksi.
#
#   sudo collect/add_collector.sh oh9xyz
#
# Jokainen kerääjä saa oman topic-juurensa oh9ab/<nimi>, jotta
# 1) näemme kenen solmusta mikäkin havainto tuli
# 2) yhden tunnuksen väärinkäyttö ei sotke muiden dataa
# 3) yksittäisen kerääjän voi sulkea muita häiritsemättä

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Käyttö: sudo $0 <kerääjän-nimi>   (esim. oh9xyz, pikkukirjaimin)" >&2
    exit 1
fi

NAME="$1"
if ! [[ "$NAME" =~ ^[a-z0-9_-]+$ ]]; then
    echo "Nimessä vain pikkukirjaimia, numeroita, - ja _ (menee MQTT-topiciin)." >&2
    exit 1
fi

PASSWD=/etc/mosquitto/oh9ab.passwd
ACL=/etc/mosquitto/oh9ab.acl

# Salasana: 24 merkkiä satunnaista. Meshtastic-asetuksiin kirjoitetaan
# käsin, joten vältetään merkkejä jotka menevät sekaisin (0/O, 1/l/I).
# Pythonilla eikä tr|head:llä — jälkimmäinen kaataa skriptin SIGPIPEen.
PASS=$(python3 -c 'import secrets
a="abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
print("".join(secrets.choice(a) for _ in range(24)))')

touch "$PASSWD"
mosquitto_passwd -b "$PASSWD" "$NAME" "$PASS"
chown mosquitto:mosquitto "$PASSWD"
chmod 600 "$PASSWD"

if ! grep -q "^user ${NAME}$" "$ACL" 2>/dev/null; then
    {
        echo ""
        echo "user ${NAME}"
        echo "topic write oh9ab/${NAME}/#"
        echo "topic read oh9ab/${NAME}/#"
    } >> "$ACL"
fi
chown mosquitto:mosquitto "$ACL"
chmod 640 "$ACL"

systemctl reload mosquitto || systemctl restart mosquitto

# propagation.rupsu.fi:1883 on portti-ohjattu tälle palvelimelle (VM:n oma
# osoite on yksityinen 10.10.10.153, ei tavoiteta ulkopuolelta).
HOST_HINT="${OH9AB_MQTT_HOST:-propagation.rupsu.fi}"

cat <<EOF

════════════════════════════════════════════════════════════════
 Tunnus luotu: ${NAME}
════════════════════════════════════════════════════════════════

Lähetä nämä ystävälle. Salasana näkyy vain nyt — sitä ei voi lukea
jälkikäteen, mutta uuden voi luoda ajamalla tämän komennon uudelleen.

  Palvelin:    ${HOST_HINT}
  Portti:      1883
  Käyttäjä:    ${NAME}
  Salasana:    ${PASS}
  Topic-juuri: oh9ab/${NAME}

Komennot solmuun (meshtastic-CLI):

  meshtastic --set mqtt.address ${HOST_HINT}
  meshtastic --set mqtt.username ${NAME}
  meshtastic --set mqtt.password ${PASS}
  meshtastic --set mqtt.root oh9ab/${NAME}
  meshtastic --set mqtt.enabled true
  meshtastic --set mqtt.json_enabled true
  meshtastic --set mqtt.encryption_enabled false
  meshtastic --ch-index 0 --ch-set uplink_enabled true
  meshtastic --ch-index 0 --ch-set position_precision 32

Täydet ohjeet: docs/keraysohje.md
════════════════════════════════════════════════════════════════
EOF
