"""Päästä päähän: synteettinen Meshtastic-loki -> jäsennys -> maastoprofiilit
-> P.1812-ennuste -> tilastot.

Tämä EI validoi mallia (mitatut RSSI:t ovat keksittyjä) — se validoi PUTKEN:
että vaiheet keskustelevat keskenään ja tuottavat järkevän muotoista dataa
oikeaa maastoaineistoa vasten. Varsinainen validointi vaatii oikeat lokit.

Ohitetaan jos GDAL, node tai maastoaineiston VRT puuttuu.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

pytest.importorskip("osgeo", reason="GDAL puuttuu")

from validate.parse_logs import COORD_SCALE, parse  # noqa: E402

DEM = ROOT / "data" / "kemijoki_dem.vrt"
FOREST = ROOT / "data" / "kemijoki_kp.vrt"

pytestmark = [
    pytest.mark.skipif(not DEM.exists(), reason="korkeusmallin VRT puuttuu"),
    pytest.mark.skipif(shutil.which("node") is None, reason="node puuttuu"),
]

# Solmut Kemijoki-käytävän sisällä, jotta maastoaineisto kattaa reitit.
NODES = {
    0x11111111: ("OH9RAB",        66.6087, 25.8403, 5.0),
    0x22222222: ("Rovaniemi kk",  66.4977, 25.7245, 20.0),
    0x33333333: ("Muurola",       66.3700, 25.3600, 8.0),
    0x44444444: ("Tervola",       66.0830, 24.8070, 12.0),
}


def pos_msg(nid, lat, lon, ts):
    return {"type": "position", "from": nid, "sender": "!%08x" % nid,
            "timestamp": ts, "id": ts * 17 + nid % 11,
            "payload": {"latitude_i": int(round(lat / COORD_SCALE)),
                        "longitude_i": int(round(lon / COORD_SCALE)),
                        "altitude": 120}}


def rx_msg(frm, gw, ts, rssi, snr, pid):
    return {"type": "text", "from": frm, "sender": "!%08x" % gw,
            "timestamp": ts, "id": pid, "rssi": rssi, "snr": snr,
            "hops_away": 0, "payload": {"text": "testi"}}


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    d = tmp_path_factory.mktemp("validate_e2e")
    msgs = [pos_msg(nid, lat, lon, 1000)
            for nid, (_, lat, lon, _) in NODES.items()]
    ids = list(NODES)
    pid = 5000
    # Kaikki parit molempiin suuntiin, keksityt mutta uskottavat RSSI:t
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            for frm, gw in ((a, b), (b, a)):
                pid += 1
                msgs.append(rx_msg(frm, gw, 1100 + pid, -95 - (pid % 25), 3.5, pid))
    # Mukaan myös roskaa, jonka pitää suodattua pois
    msgs.append(rx_msg(ids[0], ids[1], 1200, -90, 2.0, 9001) | {"hops_away": 2})
    log = d / "loki.ndjson"
    log.write_text("\n".join(json.dumps(m) for m in msgs), encoding="utf-8")

    nodes_cfg = {"defaults": {"antenna_height_m": 2.0, "tx_power_dbm": 27.0,
                              "antenna_gain_dbi": 2.15, "cable_loss_db": 0.0,
                              "freq_mhz": 869.525, "pol": 2},
                 "nodes": {"!%08x" % nid: {"name": nm, "antenna_height_m": h}
                           for nid, (nm, _, _, h) in NODES.items()}}
    cfg = d / "nodes.json"
    cfg.write_text(json.dumps(nodes_cfg), encoding="utf-8")
    return d, log, cfg


def test_koko_putki(synthetic):
    d, log, cfg = synthetic

    # 1. jäsennys
    obs_csv = d / "havainnot.csv"
    rows, stats = parse(str(log))
    assert stats["releen kautta (hyppyjä > 0)"] == 1, "relepaketin pitää suodattua"
    assert len(rows) == 12, "4 solmua -> 6 paria -> 12 suuntaa"
    import csv as _csv
    from validate.parse_logs import FIELDS
    with open(obs_csv, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader(); w.writerows(rows)

    # 2. maastoprofiilit oikeasta aineistosta
    prof = d / "profiilit.json"
    cmd = [sys.executable, str(ROOT / "validate" / "extract_profiles.py"),
           str(obs_csv), "--dem", str(DEM), "--nodes", str(cfg),
           "--out", str(prof), "--step", "50"]
    if FOREST.exists():
        cmd += ["--forest", str(FOREST)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    profs = json.loads(prof.read_text(encoding="utf-8"))
    assert len(profs) == 12, r.stderr

    p = profs[0]
    assert p["d"][0] == 0.0 and len(p["d"]) > 4
    assert len(p["d"]) == len(p["h"]) == len(p["R"]) == len(p["zone"])
    # Kemijokivarren maasto on kymmenistä pariinsataan metriin
    assert all(0 < x < 400 for x in p["h"]), "korkeudet eivät ole uskottavia"
    assert all(0 <= x < 40 for x in p["R"]), "latvuskorkeudet eivät ole uskottavia"

    # 3. P.1812-ennuste
    pred = d / "ennusteet.json"
    r = subprocess.run(
        ["node", str(ROOT / "validate" / "predict.js"), str(prof),
         "--dn", "45", "--n0", "325", "--out", str(pred)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    preds = json.loads(pred.read_text(encoding="utf-8"))
    assert len(preds) == 12, r.stderr

    for q in preds:
        # 868 MHz, 5–60 km: perusvaimennuksen pitää olla tällä haarukalla
        assert 80 < q["Lb"] < 250, q
        assert q["pathtype"] in (1, 2)
        assert q["rssi_pred"] == pytest.approx(
            27.0 + 2.15 - q["Lb"] + 2.15, abs=1e-9)

    # 4. tilastot
    from validate.compare import residuals, stats as cstats
    st = cstats(residuals(preds))
    assert st["n"] == 12
    assert all(k in st for k in ("bias", "rmse", "sd"))


def test_r_kerroin_vaikuttaa_ennusteeseen(synthetic):
    """Kalibrointikertoimen pitää oikeasti muuttaa tulosta — muuten
    kalibrointi olisi hiljainen ei-operaatio."""
    d, log, cfg = synthetic
    prof = d / "profiilit.json"
    if not prof.exists():
        pytest.skip("profiilit puuttuvat (aja test_koko_putki ensin)")

    def run(scale, out):
        r = subprocess.run(
            ["node", str(ROOT / "validate" / "predict.js"), str(prof),
             "--dn", "45", "--n0", "325", "--r-scale", str(scale),
             "--out", str(d / out)],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return json.loads((d / out).read_text(encoding="utf-8"))

    a = run(1.0, "e_1.json")
    b = run(2.0, "e_2.json")
    erot = [abs(x["Lb"] - y["Lb"]) for x, y in zip(a, b)]
    assert max(erot) > 0.1, "R-kertoimella ei ollut vaikutusta"
