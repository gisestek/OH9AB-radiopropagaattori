"""Testit nodes.json:n käsinmuokkauksen tarkistimelle.

Painopiste on siinä ettei virheellinen käsin muokattu tiedosto pääse
vaikuttamaan validointiin huomaamatta — jokainen tässä testattu virhe on
sellainen joka oikeasti tapahtuisi käsin kopioidessa (esim. Meshtasticin
raaka latitudeI liitettynä suoraan lat-kenttään).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from validate.check_nodes import check  # noqa: E402


def write(tmp_path, text, name="nodes.json"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def as_json(tmp_path, obj, name="nodes.json"):
    return write(tmp_path, json.dumps(obj), name)


def test_puhdas_tiedosto_ei_virheita(tmp_path):
    p = as_json(tmp_path, {
        "defaults": {"antenna_height_m": 2.0, "pol": 2},
        "nodes": {"!eafc8216": {"name": "Kapula", "mobile": True,
                                "antenna_height_m": 1.0}}
    })
    errors, warnings, overrides = check(p)
    assert errors == [] and warnings == []
    assert overrides == {}


def test_json_syntaksivirhe_kertoo_rivin(tmp_path):
    p = write(tmp_path, '{\n  "nodes": {\n    "!x": {"a": 1,}\n  }\n}')
    errors, warnings, _ = check(p)
    assert len(errors) == 1
    assert "rivi" in errors[0] and "sarake" in errors[0]


def test_nodes_puuttuu_kokonaan(tmp_path):
    p = as_json(tmp_path, {"defaults": {}})
    errors, _, _ = check(p)
    assert any("nodes" in e for e in errors)


def test_duplikaattiavain_on_varoitus(tmp_path):
    p = write(tmp_path, '{"nodes": {"!11111111": {"name": "a"}, '
                        '"!11111111": {"name": "b"}}}')
    errors, warnings, _ = check(p)
    assert errors == []
    assert any("Duplikaattiavain" in w and "!11111111" in w for w in warnings)


def test_tuntematon_kentta_on_varoitus(tmp_path):
    p = as_json(tmp_path, {"nodes": {"!11111111": {"antenna_height": 5.0}}})
    errors, warnings, _ = check(p)
    assert errors == []
    assert any("antenna_height" in w for w in warnings)


def test_ei_numero_numerokentassa_on_virhe(tmp_path):
    p = as_json(tmp_path, {"nodes": {"!11111111": {"antenna_height_m": "korkea"}}})
    errors, _, _ = check(p)
    assert any("antenna_height_m" in e for e in errors)


def test_vaara_pol_on_virhe(tmp_path):
    p = as_json(tmp_path, {"nodes": {"!11111111": {"pol": 3}}})
    errors, _, _ = check(p)
    assert any("pol" in e for e in errors)


def test_mobile_ei_boolean_on_virhe(tmp_path):
    p = as_json(tmp_path, {"nodes": {"!11111111": {"mobile": "kylla"}}})
    errors, _, _ = check(p)
    assert any("mobile" in e for e in errors)


def test_vaara_solmutunnus_on_varoitus(tmp_path):
    p = as_json(tmp_path, {"nodes": {"OH9RAB": {"name": "x"}}})
    errors, warnings, _ = check(p)
    assert errors == []
    assert any("OH9RAB" in w for w in warnings)


# ── lat/lon-turvatarkistukset (jaettu load_position_overrides:n kanssa) ──

def test_raaka_latitudei_tunnistetaan_virheeksi(tmp_path):
    """Yleisin oikea virhe: Meshtasticin latitudeI/longitudeI liitetty
    suoraan ilman 1e-7-kerrointa."""
    p = as_json(tmp_path, {"nodes": {"!da5afd20": {
        "lat": 664899588, "lon": 257540866}}})
    errors, _, overrides = check(p)
    assert len(errors) == 1
    assert "1e7" in errors[0] or "1e-7" in errors[0] or "664899588" in errors[0]
    assert overrides == {}


def test_liikkuva_ja_kiintea_sijainti_ristiriita(tmp_path):
    p = as_json(tmp_path, {"nodes": {"!eafc8216": {
        "mobile": True, "lat": 66.49, "lon": 25.75}}})
    errors, _, overrides = check(p)
    assert len(errors) == 1 and "mobile" in errors[0].lower()
    assert overrides == {}


def test_vain_lat_ilman_lonia_on_virhe(tmp_path):
    p = as_json(tmp_path, {"nodes": {"!11111111": {"lat": 66.49}}})
    errors, _, _ = check(p)
    assert any("lat" in e and "lon" in e for e in errors)


def test_kelvollinen_kiintea_sijainti_naytetaan(tmp_path):
    p = as_json(tmp_path, {"nodes": {"!da5afd20": {
        "name": "OH9DVN fd20", "lat": 66.4899588, "lon": 25.7540866}}})
    errors, warnings, overrides = check(p)
    assert errors == [] and warnings == []
    assert overrides == {0xda5afd20: pytest.approx((66.4899588, 25.7540866))}
