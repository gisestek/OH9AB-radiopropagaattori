"""Puretaan Meshtastic-solmujen MQTT-protobuf-paketit (topic .../2/e/...)
samaan sanakirjamuotoon jota validate/parse_logs.py jo lukee JSON-mirrorista.

MIKSI TÄMÄ ON OLEMASSA: osa solmuista (havaittu 2026-07-26: oh8efi, oh9fkj)
ei koskaan julkaise JSON-peiliä vaikka protobuf tulee luotettavasti — syytä
ei tiedetä varmasti (JSON-kytkin ei ehkä oikeasti aktivoidu laitteella).
".../2/e/..."-topic on Meshtasticin PERUSTOPIC, joka lähtee aina kun
kanavalla on uplink_enabled, riippumatta JSON-asetuksesta. Tämä poistaa
riippuvuuden viallisesta/epäselvästä JSON-kytkimestä kokonaan.

KAKSI TAPAUSTA (firmware: src/mqtt/MQTT.cpp, MQTT::onSend(), rivit ks.
git-historia haettu 2026-07-26 commit bfd718fa1dcb019ed11b7b7185f37318abebdafc
-viitteisestä protobufs-repon rinnalla luetusta firmware/master-haarasta):

  moduleConfig.mqtt.encryption_enabled == false (OLETUS)
      -> paketti julkaistaan JO PURETTUNA (payload_variant "decoded"),
         solmu on itse purkanut sen ennen MQTT-julkaisua. EI vaadi kanavan
         PSK:ta ollenkaan. Tämä on TODETTU todellisesta liikenteestä
         (oh9dvn, oh8efi, molemmat EdgeFastLow/PSK=AQ==, 2026-07-26).

  moduleConfig.mqtt.encryption_enabled == true
      -> paketti julkaistaan yhä salattuna (payload_variant "encrypted"),
         vaatii kanavan PSK:n purkuun. TÄTÄ HAARAA EI OLE VIELÄ NÄHTY
         OIKEASSA LIIKENTEESSÄ tässä verkossa — testattu vain synteettisellä
         edestakaisin-ajolla (ks. test_mesh_decode.py). Toimii vain
         kanavan oletus-PSK:lle ("AQ==" / lyhenne-indeksi 1); räätälöity
         PSK palauttaa None eikä yritä arvata.

SALAUSALGORITMI (jos "encrypted"-haaraa joskus tarvitaan oikeasti):
  meshtastic/firmware, src/mesh/CryptoEngine.cpp:
    CryptoEngine::decrypt() kutsuu encryptPacket():a (CTR-tila on
    symmetrinen, sama operaatio purkuun ja salaukseen).
    CryptoEngine::initNonce(): 16-tavuinen nonce/laskuri =
        packetId (8 t, little-endian) + fromNode (4 t, little-endian)
        + 4 nollatavua (extraNonce=0, koska se on vain Curve25519-suoraa
        viestiä varten, ei kanavan PSK-salausta varten).
    CryptoEngine::encryptAESCtr(): AES-CTR, avaimen pituus (16=AES128 tai
        32=AES256) määrää algoritmin, IV = koko 16-tavuinen nonce.
  meshtastic/firmware, src/mesh/Channels.h ja Channels.cpp (getKey()):
    1-tavuinen PSK on lyhenne: indeksi 0 = salaus pois, indeksi 1 =
    defaultpsk sellaisenaan, indeksi N>1 = defaultpsk jonka viimeiseen
    tavuun lisätään (N-1). defaultpsk on 16 tavua, kovakoodattu ja
    julkinen (Channels.h: "16 bytes of random PSK for our _public_
    default channel that all devices power up on").

Protobuf-skeema: collect/pb/ (käännetty meshtastic/protobufs-repon
virallisista .proto-tiedostoista, ks. collect/pb/README.md commit-hash).
"""

import base64
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from collect.pb.meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2

# src/mesh/Channels.h: defaultpsk[16] — julkinen, sama kaikilla laitteilla.
DEFAULT_PSK = bytes([0xd4, 0xf1, 0xbb, 0x3a, 0x20, 0x29, 0x07, 0x59,
                      0xf0, 0xbc, 0xff, 0xab, 0xcf, 0x4e, 0x69, 0x01])

POSITION_APP = portnums_pb2.PortNum.POSITION_APP


def expand_channel_psk(psk_bytes):
    """Channels::getKey() (Channels.cpp): 1-tavuinen PSK on lyhenne.

    Palauttaa täyden AES-avaimen, tai None jos avainta ei tueta (räätälöity
    pidempi PSK — ei tarvittu eikä testattu tässä verkossa) tai salaus on
    pois päältä (indeksi 0)."""
    if len(psk_bytes) != 1:
        return None
    idx = psk_bytes[0]
    if idx == 0:
        return None  # käyttäjä on kytkenyt salauksen pois
    key = bytearray(DEFAULT_PSK)
    key[-1] = (key[-1] + idx - 1) & 0xFF
    return bytes(key)


def _nonce(from_node, packet_id):
    """CryptoEngine::initNonce(): packetId (8 t LE) + fromNode (4 t LE)
    + 4 nollatavua = 16-tavuinen IV/laskuri CTR-tilalle."""
    return struct.pack("<QI4x", packet_id & 0xFFFFFFFFFFFFFFFF,
                       from_node & 0xFFFFFFFF)


def decrypt_data(from_node, packet_id, ciphertext, psk_b64="AQ=="):
    """Purkaa MeshPacket.encrypted-kentän Data-protobufin tavuiksi, tai
    palauttaa None jos avainta ei tueta tai purku ei tuota kelvollista
    protobufia."""
    padded = psk_b64 + "=" * (-len(psk_b64) % 4)
    try:
        psk_bytes = base64.b64decode(padded)
    except Exception:
        return None
    key = expand_channel_psk(psk_bytes)
    if key is None:
        return None
    nonce = _nonce(from_node, packet_id)
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce))
    d = cipher.decryptor()
    return d.update(ciphertext) + d.finalize()


def _position_payload(data_bytes):
    """Position-protobuf -> parse_logs.py:n odottama payload-sanakirja,
    tai None jos koordinaatteja ei ole (esim. solmulla ei GPS-kiinnitystä)."""
    pos = mesh_pb2.Position()
    try:
        pos.ParseFromString(data_bytes)
    except Exception:
        return None
    if not (pos.HasField("latitude_i") and pos.HasField("longitude_i")):
        return None
    out = {"latitude_i": pos.latitude_i, "longitude_i": pos.longitude_i}
    if pos.HasField("altitude"):
        out["altitude"] = pos.altitude
    return out


def decode_service_envelope(raw_bytes, psk_b64="AQ=="):
    """ServiceEnvelope-protobuf (.../2/e/...-topicin raakatavut) ->
    validate/parse_logs.py:n JSON-mirrorin kanssa yhteensopiva sanakirja,
    tai None jos pakettia ei voitu jäsentää/purkaa.

    Kentät vastaavat tarkoituksella JSON-mirrorin nimiä (from, sender,
    id, rx_snr, rx_rssi, hop_limit, hop_start, timestamp, type, payload),
    jotta parse_logs.py ei tarvitse mitään muutoksia."""
    env = mqtt_pb2.ServiceEnvelope()
    try:
        env.ParseFromString(raw_bytes)
    except Exception:
        return None

    packet = env.packet
    which = packet.WhichOneof("payload_variant")
    if which == "decoded":
        data = packet.decoded
    elif which == "encrypted":
        plaintext = decrypt_data(getattr(packet, "from"), packet.id,
                                 packet.encrypted, psk_b64)
        if plaintext is None:
            return None
        data = mesh_pb2.Data()
        try:
            data.ParseFromString(plaintext)
        except Exception:
            return None
    else:
        return None

    obj = {
        "from": getattr(packet, "from"),
        "sender": env.gateway_id,
        "id": packet.id,
        "timestamp": packet.rx_time,
        "hop_limit": packet.hop_limit,
        "hop_start": packet.hop_start,
        "rx_snr": packet.rx_snr,
        "rx_rssi": packet.rx_rssi,
    }

    if data.portnum == POSITION_APP:
        payload = _position_payload(data.payload)
        if payload is not None:
            obj["type"] = "position"
            obj["payload"] = payload

    return obj
