# pb — käännetyt protobuf-määrittelyt

Tämä hakemisto sisältää `protoc`:lla käännetyt Python-bindaukset
Meshtastic-projektin viralliseen protobuf-skeemaan. Ei käsin kirjoitettua
koodia — generoitu suoraan yläprojektin lähteestä, jotta kenttien nimet ja
numerot ovat taatusti oikein eivätkä oman muistin varassa.

**Lähde**: https://github.com/meshtastic/protobufs
**Commit**: `bfd718fa1dcb019ed11b7b7185f37318abebdafc` (haettu 2026-07-26)

## Uudelleengenerointi

```bash
sudo apt-get install -y protobuf-compiler python3-protobuf
git clone --depth 1 https://github.com/meshtastic/protobufs.git /tmp/mt-protobufs
mkdir -p /tmp/mt-pyout
protoc -I/tmp/mt-protobufs --python_out=/tmp/mt-pyout /tmp/mt-protobufs/meshtastic/*.proto
touch /tmp/mt-pyout/meshtastic/__init__.py
cp -r /tmp/mt-pyout/meshtastic collect/pb/meshtastic
```

Päivitä tämän tiedoston commit-hash, jos skeemaa uudistetaan.

## Miksi vendorattu eikä `pip install meshtastic`

`meshtastic`-PyPI-paketti tuo mukanaan paljon riippumatonta tavaraa
(sarjaportti, BLE, Qt-pohjaiset CLI-työkalut) pelkän offline-lokien
jäsentämisen tarpeisiin. Tässä käytetään vain virallista skeemaa — itse
salauksen purku (`collect/mesh_decode.py`) on kirjoitettu erikseen
Meshtastic-*firmwaren* lähdekoodia vasten (ks. sen omat viitteet).
