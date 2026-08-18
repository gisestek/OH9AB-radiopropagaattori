"""Testit Meshtastic-lokien jäsentimelle.

Painopiste on suodatuksessa: väärin mukaan päässyt relepaketti pilaisi
kalibrointiaineiston hiljaisesti, koska sen RSSI kuvaa eri linkkiä kuin
mitä koordinaateista päättelisi.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from validate.parse_logs import (COORD_SCALE, haversine_m, hops_taken,  # noqa: E402
                                 load_position_overrides, node_id_to_int, parse)

TX = 0x11111111      # kiinteä asema, Rovaniemi
GW = 0x22222222      # gateway, ~13 km etelään
RELAY = 0x33333333   # rele
TX_LL = (66.6087, 25.8403)
GW_LL = (66.4977, 25.7245)
RELAY_LL = (66.5500, 25.8000)


def pos_msg(node, lat, lon, ts, alt=100):
    return {"type": "position", "from": node, "sender": "!%08x" % node,
            "timestamp": ts, "id": ts * 10 + node % 7,
            "payload": {"latitude_i": int(round(lat / COORD_SCALE)),
                        "longitude_i": int(round(lon / COORD_SCALE)),
                        "altitude": alt}}


def rx_msg(frm, gw, ts, rssi=-100, snr=5.0, hops_away=0, pid=None, **extra):
    m = {"type": "text", "from": frm, "sender": "!%08x" % gw,
         "timestamp": ts, "id": pid if pid is not None else ts * 100,
         "rssi": rssi, "snr": snr, "hops_away": hops_away,
         "payload": {"text": "moi"}}
    m.update(extra)
    return m


def write_log(tmp_path, msgs, name="loki.ndjson"):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(m) for m in msgs), encoding="utf-8")
    return str(p)


def base_positions(ts=1000):
    return [pos_msg(TX, *TX_LL, ts), pos_msg(GW, *GW_LL, ts),
            pos_msg(RELAY, *RELAY_LL, ts)]


# ── perustapaus ────────────────────────────────────────────────

def test_suora_vastaanotto_kelpaa(tmp_path):
    log = write_log(tmp_path, base_positions() + [rx_msg(TX, GW, 1100, rssi=-97)])
    rows, stats = parse(log)
    assert len(rows) == 1
    r = rows[0]
    assert r["tx_id"] == TX and r["rx_id"] == GW
    assert r["rssi"] == -97
    # dist_m kirjoitetaan desimetrin tarkkuudella
    assert r["dist_m"] == pytest.approx(haversine_m(*TX_LL, *GW_LL), abs=0.05)


def test_koordinaattien_skaalaus(tmp_path):
    log = write_log(tmp_path, base_positions() + [rx_msg(TX, GW, 1100)])
    rows, _ = parse(log)
    assert rows[0]["tx_lat"] == pytest.approx(TX_LL[0], abs=1e-7)
    assert rows[0]["tx_lon"] == pytest.approx(TX_LL[1], abs=1e-7)


# ── kriittinen: releen kautta tulleet on hylättävä ─────────────

def test_relepaketti_hylataan(tmp_path):
    log = write_log(tmp_path, base_positions() + [rx_msg(TX, GW, 1100, hops_away=1)])
    rows, stats = parse(log)
    assert rows == []
    assert stats["releen kautta (hyppyjä > 0)"] == 1


def test_hop_start_ja_hop_limit_kaytetaan_kun_hops_away_puuttuu(tmp_path):
    suora = rx_msg(TX, GW, 1100); del suora["hops_away"]
    suora.update(hop_start=3, hop_limit=3)
    rele = rx_msg(TX, GW, 1200, pid=999); del rele["hops_away"]
    rele.update(hop_start=3, hop_limit=2)
    rows, stats = parse(write_log(tmp_path, base_positions() + [suora, rele]))
    assert len(rows) == 1
    assert stats["releen kautta (hyppyjä > 0)"] == 1


def test_tuntematon_hyppymaara_hylataan(tmp_path):
    m = rx_msg(TX, GW, 1100); del m["hops_away"]
    rows, stats = parse(write_log(tmp_path, base_positions() + [m]))
    assert rows == []
    assert stats["hyppymäärä tuntematon"] == 1


# ── muut suodattimet ──────────────────────────────────────────

def test_ilman_rssia_hylataan(tmp_path):
    # Verrataan erotuksena: myös position-paketit osuvat samaan laskuriin,
    # koska niissä ei ole vastaanottometatietoa.
    m = rx_msg(TX, GW, 1100); del m["rssi"]
    _, ilman = parse(write_log(tmp_path, base_positions(), "a.ndjson"))
    rows, kanssa = parse(write_log(tmp_path, base_positions() + [m], "b.ndjson"))
    assert rows == []
    assert kanssa["ei RSSI-tietoa"] == ilman["ei RSSI-tietoa"] + 1


def test_puuttuva_sijainti_hylataan(tmp_path):
    # vain gatewaylla on sijainti
    log = write_log(tmp_path, [pos_msg(GW, *GW_LL, 1000), rx_msg(TX, GW, 1100)])
    rows, stats = parse(log)
    assert rows == [] and stats["lähettäjän sijainti puuttuu"] == 1


def test_gateway_kuulee_itsensa_hylataan(tmp_path):
    log = write_log(tmp_path, base_positions() + [rx_msg(GW, GW, 1100)])
    rows, stats = parse(log)
    assert rows == [] and stats["gateway = lähettäjä"] == 1


def test_liian_lyhyt_matka_hylataan(tmp_path):
    lahella = (TX_LL[0] + 0.0001, TX_LL[1])       # ~11 m
    log = write_log(tmp_path, [pos_msg(TX, *TX_LL, 1000), pos_msg(GW, *lahella, 1000),
                               rx_msg(TX, GW, 1100)])
    rows, stats = parse(log, min_dist_m=50.0)
    assert rows == [] and stats["liian lyhyt matka"] == 1


def test_kaksoiskappale_hylataan(tmp_path):
    m = rx_msg(TX, GW, 1100, pid=4242)
    rows, stats = parse(write_log(tmp_path, base_positions() + [m, dict(m)]))
    assert len(rows) == 1 and stats["kaksoiskappaleita"] == 1


def test_sama_paketti_kahdelta_gatewaylta_on_kaksi_havaintoa(tmp_path):
    """Eri gateway = eri linkki, molemmat kelvollisia mittauksia."""
    log = write_log(tmp_path, base_positions() + [
        rx_msg(TX, GW, 1100, pid=555, rssi=-95),
        rx_msg(TX, RELAY, 1100, pid=555, rssi=-80)])
    rows, _ = parse(log)
    assert len(rows) == 2
    assert {r["rx_id"] for r in rows} == {GW, RELAY}


# ── liikkuvat asemat ──────────────────────────────────────────

def test_valitaan_ajallisesti_lahin_sijainti(tmp_path):
    liikkuva = (66.4000, 25.5000)
    msgs = [pos_msg(TX, *TX_LL, 1000), pos_msg(GW, *GW_LL, 1000),
            pos_msg(GW, *liikkuva, 5000),          # gateway siirtyi
            rx_msg(TX, GW, 4900)]                  # mittaus lähellä jälkimmäistä
    rows, _ = parse(write_log(tmp_path, msgs))
    assert rows[0]["rx_lat"] == pytest.approx(liikkuva[0], abs=1e-7)
    assert rows[0]["rx_pos_age_s"] == 100.0


def test_max_pos_age_suodattaa(tmp_path):
    msgs = base_positions(ts=1000) + [rx_msg(TX, GW, 99000)]
    rows, stats = parse(write_log(tmp_path, msgs), max_pos_age_s=3600)
    assert rows == [] and stats["sijainti liian vanha"] == 1


# ── kiinteän aseman tunnettu sijainti (nodes.json lat/lon) ─────

def write_nodes(tmp_path, nodes_dict, name="nodes.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"nodes": nodes_dict}), encoding="utf-8")
    return str(p)


def test_load_position_overrides(tmp_path):
    cfg = write_nodes(tmp_path, {
        "!11111111": {"lat": 66.6087, "lon": 25.8403},
        "!22222222": {"antenna_height_m": 8.0},   # ei lat/lon -> ei ohitusta
    })
    ov = load_position_overrides(cfg)
    assert ov == {0x11111111: (66.6087, 25.8403)}


def test_kiintea_sijainti_ohittaa_verkon_position(tmp_path):
    """Verkko raportoi TX:n väärässä (lähempänä GW:tä olevassa) pisteessä,
    mutta nodes.json:n tarkka sijainti korjaa sen ennen etäisyyslaskua."""
    vaara_sijainti = (66.4980, 25.7250)   # ~30 m GW:stä, alle min-dist:in
    msgs = [pos_msg(TX, *vaara_sijainti, 1000), pos_msg(GW, *GW_LL, 1000),
            rx_msg(TX, GW, 1100)]
    log = write_log(tmp_path, msgs)
    nodes = write_nodes(tmp_path, {"!%08x" % TX: {"lat": TX_LL[0], "lon": TX_LL[1]}})

    # Ilman ohitusta: hylätään liian lyhyenä (verkon virheellinen sijainti).
    rows_ilman, stats_ilman = parse(log, min_dist_m=50.0)
    assert rows_ilman == [] and stats_ilman["liian lyhyt matka"] == 1

    # Ohituksella: oikea, kaukainen sijainti käytössä, havainto kelpaa.
    rows, stats = parse(log, min_dist_m=50.0, nodes_path=nodes)
    assert len(rows) == 1
    assert rows[0]["tx_lat"] == pytest.approx(TX_LL[0], abs=1e-7)
    assert rows[0]["tx_lon"] == pytest.approx(TX_LL[1], abs=1e-7)
    assert rows[0]["tx_fixed"] == 1 and rows[0]["rx_fixed"] == 0
    assert rows[0]["tx_pos_age_s"] == 0.0
    assert stats["havaintoja joissa kiinteä sijainti käytössä"] == 1


def test_kiintea_sijainti_ilman_verkkopositiota_lainkaan(tmp_path):
    """Solmu ei koskaan lähetä position-pakettia — ilman ohitusta havainto
    hylätään, ohituksella se kelpaa nodes.json:n sijainnilla."""
    msgs = [pos_msg(GW, *GW_LL, 1000), rx_msg(TX, GW, 1100)]  # ei TX:n positiota
    log = write_log(tmp_path, msgs)

    rows_ilman, stats_ilman = parse(log)
    assert rows_ilman == [] and stats_ilman["lähettäjän sijainti puuttuu"] == 1

    nodes = write_nodes(tmp_path, {"!%08x" % TX: {"lat": TX_LL[0], "lon": TX_LL[1]}})
    rows, _ = parse(log, nodes_path=nodes)
    assert len(rows) == 1
    assert rows[0]["tx_lat"] == pytest.approx(TX_LL[0], abs=1e-7)
    assert rows[0]["tx_fixed"] == 1


def test_ilman_nodes_tiedostoa_kaikki_ennallaan(tmp_path):
    """Regressio: nodes_path=None ei muuta mitään aiempaan käyttäytymiseen."""
    log = write_log(tmp_path, base_positions() + [rx_msg(TX, GW, 1100)])
    rows, stats = parse(log)
    assert len(rows) == 1
    assert rows[0]["tx_fixed"] == 0 and rows[0]["rx_fixed"] == 0
    assert stats["havaintoja joissa kiinteä sijainti käytössä"] == 0


def test_raaka_koordinaatti_hylataan_heti(tmp_path):
    """Meshtasticin latitudeI liitetty suoraan ilman 1e-7-kerrointa on
    hengenvaarallinen hiljainen virhe — sen PITÄÄ nostaa poikkeus, ei
    tuottaa hiljaa väärää tulosta."""
    nodes = write_nodes(tmp_path, {"!da5afd20": {"lat": 664899588, "lon": 257540866}})
    with pytest.raises(ValueError):
        load_position_overrides(nodes)


def test_ndjson_lokitiedosto_nodesina_antaa_ymmarrettavan_virheen(tmp_path):
    """Todellinen virhe (2026-07-27): "status.py --nodes logs/*.ndjson"
    antaa shellin glob-laajennuksen takia --nodes:ille lokitiedoston eikä
    nodes.json:ia. json.load kaatuisi muuten raakaan "Extra data" ->
    JSONDecodeError-jälkeen, joka ei kerro mitään syystä. Virheen pitää
    mainita todennäköinen syy (glob/argumenttijärjestys), ei vain kaatua."""
    log = write_log(tmp_path, [pos_msg(TX, *TX_LL, 1000), pos_msg(GW, *GW_LL, 1100)])
    with pytest.raises(ValueError, match="glob|lokitiedoston|--nodes"):
        load_position_overrides(log)


def test_liikkuva_ja_kiintea_ristiriita_hylataan(tmp_path):
    nodes = write_nodes(tmp_path, {"!eafc8216": {
        "mobile": True, "lat": 66.49, "lon": 25.75}})
    with pytest.raises(ValueError):
        load_position_overrides(nodes)


def test_vajaa_lat_lon_pari_hylataan(tmp_path):
    nodes = write_nodes(tmp_path, {"!11111111": {"lat": 66.49}})
    with pytest.raises(ValueError):
        load_position_overrides(nodes)


def test_molemmat_paat_kiinteita(tmp_path):
    log = write_log(tmp_path, [rx_msg(TX, GW, 1100)])   # ei yhtaan position-pakettia
    nodes = write_nodes(tmp_path, {
        "!%08x" % TX: {"lat": TX_LL[0], "lon": TX_LL[1]},
        "!%08x" % GW: {"lat": GW_LL[0], "lon": GW_LL[1]},
    })
    rows, _ = parse(log, nodes_path=nodes)
    assert len(rows) == 1
    assert rows[0]["tx_fixed"] == 1 and rows[0]["rx_fixed"] == 1
    assert rows[0]["dist_m"] == pytest.approx(haversine_m(*TX_LL, *GW_LL), abs=0.5)


# ── formaattien sieto ─────────────────────────────────────────

def test_json_taulukko_muoto(tmp_path):
    p = tmp_path / "loki.json"
    p.write_text(json.dumps(base_positions() + [rx_msg(TX, GW, 1100)]), encoding="utf-8")
    rows, _ = parse(str(p))
    assert len(rows) == 1


def test_topic_etuliite_rivilla(tmp_path):
    """mosquitto_sub -v tuottaa 'topic {json}' -rivejä."""
    msgs = base_positions() + [rx_msg(TX, GW, 1100)]
    p = tmp_path / "loki.txt"
    p.write_text("\n".join("msh/EU_868/2/json/LongFast/!x " + json.dumps(m)
                           for m in msgs), encoding="utf-8")
    rows, _ = parse(str(p))
    assert len(rows) == 1


def test_rikkinaiset_rivit_lasketaan_eika_kaadeta(tmp_path):
    p = tmp_path / "loki.ndjson"
    good = "\n".join(json.dumps(m) for m in base_positions() + [rx_msg(TX, GW, 1100)])
    p.write_text(good + "\nEI OLE JSONIA\n{rikki\n", encoding="utf-8")
    rows, stats = parse(str(p))
    assert len(rows) == 1 and stats["rikkinäisiä rivejä"] == 2


def test_node_id_muunnos():
    assert node_id_to_int("!7efeee00") == 0x7EFEEE00
    assert node_id_to_int(2130636288) == 2130636288
    assert node_id_to_int("ei-numero") is None


def test_hops_taken_prioriteetti():
    assert hops_taken({"hops_away": 0, "hop_start": 3, "hop_limit": 1}) == 0
    assert hops_taken({"hop_start": 3, "hop_limit": 1}) == 2
    assert hops_taken({}) is None
