"""Testit MQTT-debug-työkalun jäsennys- ja päättelylogiikalle.

Live-MQTT-kuuntelua (listen()) ei testata tässä — se vaatisi oikean
brokerin. Testataan sen sijaan puhtaat funktiot, erityisesti verdict(),
koska se on koko työkalun pointti: automatisoitu johtopäätös siitä missä
vika on.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collect.mqtt_debug import (classify_topic, parse_connection_log,  # noqa: E402
                                resolve_names, verdict)


# ── classify_topic ──────────────────────────────────────────────

def test_tunnistaa_taydellisen_topicin():
    p = classify_topic("oh9ab/oh8efi/2/e/EdgeFastLow/!eafc8216")
    assert p == {"root": "oh9ab", "collector": "oh8efi", "version": "2",
                "fmt": "e", "channel": "EdgeFastLow", "node": "!eafc8216"}


def test_tunnistaa_json_topicin():
    p = classify_topic("oh9ab/oh9dvn/2/json/LongFast/!da5afd20")
    assert p["fmt"] == "json" and p["collector"] == "oh9dvn"


def test_lyhyt_topic_ei_kaadu():
    p = classify_topic("oh9ab/oh8efi")
    assert p["collector"] == "oh8efi"
    assert p["fmt"] is None and p["node"] is None


def test_tyhja_tai_outo_topic_ei_kaadu():
    p = classify_topic("")
    assert p["collector"] is None
    p2 = classify_topic("jotain/ihan/muuta/formaattia/tassa/nyt")
    assert p2["collector"] == "ihan"  # ei kaadu, vain tulkitsee parhaansa mukaan


# ── parse_connection_log ────────────────────────────────────────

LOG_SAMPLE = """\
Jul 26 13:54:06 ubuntu-24 mosquitto[787]: 1785074046: New client connected from 80.220.101.106:41648 as MeshtasticAndroidMqttProxy-!334a685a (p5, c1, k30, u'oh9fkj').
Jul 26 13:56:42 ubuntu-24 mosquitto[787]: 1785074202: New client connected from 80.220.101.106:37836 as MeshtasticAndroidMqttProxy-!334a685a (p5, c1, k30, u'oh9fkj').
Jul 26 14:42:55 ubuntu-24 mosquitto[787]: 1785076975: New client connected from 46.132.98.108:30808 as MeshtasticAndroidMqttProxy-paho828400082539336 (p2, c1, k60, u'oh8efi').
Jul 26 15:12:29 ubuntu-24 mosquitto[787]: 1785078749: New client connected from 83.146.152.82:56459 as !da5afd20 (p2, c1, k15, u'oh9dvn').
"""


def test_laskee_yhteydet_oikealle_kayttajalle():
    n, last = parse_connection_log(LOG_SAMPLE, "oh9fkj")
    assert n == 2
    assert last.startswith("Jul 26 13:56:42")


def test_yhta_yhteytta_ei_sekoiteta_toiseen():
    n, last = parse_connection_log(LOG_SAMPLE, "oh8efi")
    assert n == 1
    n2, _ = parse_connection_log(LOG_SAMPLE, "oh9dvn")
    assert n2 == 1


def test_tuntematon_kayttaja_antaa_nollan():
    n, last = parse_connection_log(LOG_SAMPLE, "eikukaan")
    assert n == 0 and last is None


def test_tyhja_loki():
    n, last = parse_connection_log("", "oh8efi")
    assert n == 0 and last is None


# ── resolve_names — regressiotesti aiemmalle bugille ───────────

def test_tyhja_liikenne_ei_pudota_yhteyshistoriaa():
    """Bugi joka korjattiin: 0 live-viestiä ei saa piilottaa kerääjiä
    jotka näkyvät silti yhteyshistoriassa."""
    names = resolve_names(None, [], stat_keys=[], conn_keys=["oh8efi", "oh9fkj"])
    assert names == ["oh8efi", "oh9fkj"]


def test_kohdistettu_kerays_voittaa_aina():
    names = resolve_names(["oh8efi"], ["oh9dvn"], ["oh9dvn"], ["oh9fkj"])
    assert names == ["oh8efi"]


def test_live_liikenne_jarjestys_sailyy_kun_ei_kohdetta():
    names = resolve_names(None, ["oh9dvn", "delorean"], ["oh9dvn", "delorean"], [])
    assert names == ["oh9dvn", "delorean"]


def test_ei_mitaan_antaa_tyhjan_listan():
    assert resolve_names(None, [], [], []) == []


def test_kerays_suodattuu_pois_automaattisesta_listasta():
    """kerays on oma admin-tunnus, ei kenenkään oikea solmu — se yhdistää
    joka kerta kun työkalua ajetaan, eikä sitä pidä listata "ongelmana"."""
    assert resolve_names(None, [], [], ["kerays", "oh8efi"]) == ["oh8efi"]
    assert resolve_names(None, ["kerays", "oh9dvn"], [], []) == ["oh9dvn"]


def test_kerays_nakyy_jos_eksplisiittisesti_pyydetty():
    assert resolve_names(["kerays"], [], [], []) == ["kerays"]


# ── verdict — tämä on työkalun koko pointti ────────────────────

def test_ei_yhteytta_ollenkaan():
    v = verdict("x", 0, 0, 0, 0)
    assert "EI YHTEYTTÄ" in v


def test_yhdistaa_toistuvasti_muttei_julkaise():
    """Juuri oh9fkj:n oikea tilanne: monta yhteyttä, ei yhtään dataa."""
    v = verdict("oh9fkj", 5, 0, 0, 0)
    assert "TOISTUVASTI" in v


def test_ei_julkaisua_mainitsee_topic_kirjainkoon():
    """Todettu oikea vika kerran (oh9fkj, 2026-07-26): root topic oli
    isolla kirjoitettuna. Vihjeen pitää näkyä molemmissa "ei julkaisua"
    -haaroissa ja sisältää kerääjän oma nimi oikein sijoitettuna."""
    v1 = verdict("oh9fkj", 5, 0, 0, 0)
    assert "oh9ab/oh9fkj" in v1 and "kirjainkoko" in v1
    v2 = verdict("oh8efi", 1, 0, 0, 0)
    assert "oh9ab/oh8efi" in v2 and "kirjainkoko" in v2


def test_yhdistaa_kerran_muttei_julkaise_viela():
    v = verdict("x", 1, 0, 0, 0)
    assert "TOISTUVASTI" not in v
    assert "ei ole julkaissut" in v


def test_vain_protobufia_ei_jsonia():
    """Juuri oh8efi:n oikea tilanne: protobuf näkyy, JSON ei koskaan."""
    v = verdict("oh8efi", 1, 0, 3, 0)
    assert "JSON-kytkin" in v
    assert "3" in v


def test_vain_protobufia_mainitsee_nrf52_syyn_eika_ole_enaa_ongelma():
    """Todettu 2026-07-27: nRF52-pohjaiset laitteet (esim. RAK4631) eivät
    tue JSON-ulostuloa lainkaan muistirajoitusten takia — tämä EI ole enää
    korjattava vika, koska mesh_decode.py purkaa protobufin suoraan.
    Viestin pitää kertoa tämä eikä vain neuvoa turhaan rebuuttia."""
    v = verdict("oh8efi", 1, 0, 3, 0)
    assert "EI HAITTAA" in v
    assert "nRF52" in v


def test_toimii_normaalisti():
    v = verdict("oh9dvn", 2, 12, 0, 0)
    assert v.startswith("OK")


def test_protobuf_puuttuva_json_tunnistetaan_ongelmaksi_myos_muu_luokassa():
    """"other"-luokan viestit (esim. topic-fmt tunnistamaton mutta ei-JSON)
    lasketaan samaan "julkaisee jotain muttei JSONia" -tapaukseen."""
    v = verdict("x", 1, 0, 0, 2)
    assert "JSON-kytkin" in v
