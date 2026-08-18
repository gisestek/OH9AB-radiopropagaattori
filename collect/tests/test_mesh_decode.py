"""Testit protobuf-purulle (collect/mesh_decode.py).

Kaksi ensimmäistä testiä käyttävät OIKEITA MQTT:stä kaapattuja paketteja
(2026-07-26, kerays-tunnuksella .../2/e/...-topicilta, ks. commit-viesti/
collect/pb/README.md). Nämä ovat "decoded"-haaraa (moduleConfig.mqtt.
encryption_enabled == false, tämän verkon oletus), joten ne eivät testaa
salauksen purkua vaan pelkkää protobuf-jäsennystä.

Salauksen purku ("encrypted"-haara, ks. mesh_decode.py:n moduulidokumentti)
EI ole vielä nähty todellisessa liikenteessä tässä verkossa — sitä testataan
synteettisellä edestakaisin-ajolla (rakennetaan paketti käsin samalla
algoritmilla kuin firmware, salataan, ja tarkistetaan että decode purkaa sen
takaisin oikein). Tämä ei todista algoritmia oikeaksi tyhjästä, mutta
kiinnittää nonce-/tavujärjestysvirheet omassa toteutuksessa.
"""

import base64
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collect.mesh_decode import (DEFAULT_PSK, decode_service_envelope,  # noqa: E402
                                 expand_channel_psk)
from collect.pb.meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2  # noqa: E402
from cryptography.hazmat.primitives.ciphers import (Cipher, algorithms,  # noqa: E402
                                                     modes)

# Kaapattu 2026-07-26 oh9ab/oh9dvn/2/e/EdgeFastLow/!da5afd20 -topicilta.
SAMPLE_OH9DVN = (
    "Cj8NIP1a2hX/////IiAIAxIcDQCAoScVAIBZDxiNASWdQ2ZqKAF4AIABALgBEDUdsNPlPZ1D"
    "ZmpIB1gKeAeYASASC0VkZ2VGYXN0TG93GgkhZGE1YWZkMjA="
)
# Kaapattu 2026-07-26 oh9ab/oh8efi/2/e/EdgeFastLow/!eafc8216 -topicilta.
SAMPLE_OH8EFI = (
    "Ck0NrVPrtxX/////IhwIAxIWDdKLJScVaJfEDhgTKAF4AIABALgBIEgBNbjD33Q9vkNmakUA"
    "AEBBSAdgxv//////////AXgHmAGtAagBARILRWRnZUZhc3RMb3caCSFlYWZjODIxNg=="
)


def _raw(sample_b64):
    return base64.b64decode(sample_b64)


# ── oikeat kaapatut paketit ──────────────────────────────────────

def test_oh9dvn_position_puretaan_oikein():
    obj = decode_service_envelope(_raw(SAMPLE_OH9DVN))
    assert obj["from"] == 0xda5afd20
    assert obj["sender"] == "!da5afd20"
    assert obj["hop_limit"] == 7 and obj["hop_start"] == 7
    assert obj["type"] == "position"
    assert obj["payload"]["latitude_i"] == 664895488
    assert obj["payload"]["longitude_i"] == 257523712
    assert obj["payload"]["altitude"] == 141


def test_oh8efi_position_puretaan_oikein():
    obj = decode_service_envelope(_raw(SAMPLE_OH8EFI))
    assert obj["from"] == 0xb7eb53ad
    assert obj["sender"] == "!eafc8216"
    assert obj["rx_snr"] == 12.0
    assert obj["rx_rssi"] == -58
    assert obj["type"] == "position"
    assert obj["payload"]["latitude_i"] == 656772050
    assert obj["payload"]["longitude_i"] == 247764840


def test_rikkinainen_data_ei_kaadu():
    assert decode_service_envelope(b"ei protobufia tama") is None
    assert decode_service_envelope(b"") is None


# ── PSK-lyhenteen laajennus (Channels::getKey) ──────────────────

def test_oletus_psk_index_1_on_defaultpsk_sellaisenaan():
    assert expand_channel_psk(bytes([1])) == DEFAULT_PSK


def test_psk_index_0_kytkee_salauksen_pois():
    assert expand_channel_psk(bytes([0])) is None


def test_psk_index_2_lisaa_yhden_viimeiseen_tavuun():
    k = expand_channel_psk(bytes([2]))
    assert k[:-1] == DEFAULT_PSK[:-1]
    assert k[-1] == (DEFAULT_PSK[-1] + 1) & 0xFF


def test_tuntematon_pitka_psk_palauttaa_none():
    assert expand_channel_psk(b"\x00" * 32) is None


# ── synteettinen edestakaisin-ajo "encrypted"-haaralle ──────────
# Rakennetaan käsin CryptoEngine::encryptPacket()-algoritmin mukainen
# salattu paketti ja tarkistetaan että decode_service_envelope purkaa sen
# oikein. Ei todista algoritmia oikeaksi firmwarea vasten, mutta paljastaisi
# jos oma nonce-/tavujärjestystoteutus on väärä.

def _encrypt_like_firmware(from_node, packet_id, plaintext, key=DEFAULT_PSK):
    nonce = struct.pack("<QI4x", packet_id & 0xFFFFFFFFFFFFFFFF,
                        from_node & 0xFFFFFFFF)
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce))
    e = cipher.encryptor()
    return e.update(plaintext) + e.finalize()


def test_encrypted_haara_purkautuu_oikein_synteettisella_datalla():
    from_node = 0x334a685a
    packet_id = 123456789

    pos = mesh_pb2.Position()
    pos.latitude_i = 664899588
    pos.longitude_i = 257540866
    pos.altitude = 50

    data = mesh_pb2.Data()
    data.portnum = portnums_pb2.PortNum.POSITION_APP
    data.payload = pos.SerializeToString()

    ciphertext = _encrypt_like_firmware(from_node, packet_id,
                                        data.SerializeToString())

    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", from_node)
    packet.id = packet_id
    packet.rx_time = 1785000000
    packet.hop_limit = 3
    packet.hop_start = 3
    packet.encrypted = ciphertext

    env = mqtt_pb2.ServiceEnvelope()
    env.packet.CopyFrom(packet)
    env.channel_id = "LongFast"
    env.gateway_id = "!334a685a"

    obj = decode_service_envelope(env.SerializeToString())
    assert obj["from"] == from_node
    assert obj["type"] == "position"
    assert obj["payload"]["latitude_i"] == 664899588
    assert obj["payload"]["longitude_i"] == 257540866


def test_encrypted_haara_vaara_avain_palauttaa_none():
    """Jos PSK ei ole tuettu lyhenne, purku ei saa arvata mitään."""
    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", 1)
    packet.id = 1
    packet.encrypted = b"\x00" * 20
    env = mqtt_pb2.ServiceEnvelope()
    env.packet.CopyFrom(packet)
    obj = decode_service_envelope(env.SerializeToString(), psk_b64="Zm9vYmFy")
    assert obj is None
