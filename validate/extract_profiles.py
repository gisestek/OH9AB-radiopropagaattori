"""Poimi maastoprofiilit havaituille linkeille suoraan lähdeaineistosta.

Syöte:  parse_logs.py:n tuottama havainto-CSV + solmuasetukset (nodes.json)
Tuotos: JSON, jossa jokaiselle havainnolle P.1812:n vaatimat syötteet
        (d, h, R, zone, htg, hrg, taajuus, polarisaatio) sekä mitattu RSSI.

Korkeudet luetaan MML:n korkeusmallin VRT:stä ja latvuskorkeus MVMI:n
VRT:stä — siis alkuperäisestä 2 m / 16 m aineistosta, ei selaimen ruuduista.
Ruudut on tehty peittokartan tarpeisiin ja niissä on tarkoituksellista
keskiarvoistusta; validoinnissa halutaan paras saatavilla oleva profiili.

Antennikorkeus on maanpinnasta, ei GPS-korkeudesta: Meshtastic-solmujen
GPS-korkeus on usein puuttuva tai kymmeniä metrejä pielessä, kun taas
maanpinta tiedetään korkeusmallista senttimetreissä. Antennin korkeus
maanpinnasta annetaan nodes.json:ssa.

Ajo:
    python3 validate/extract_profiles.py validate/havainnot.csv \
        --dem data/kemijoki_dem.vrt --forest data/kemijoki_kp.vrt \
        --nodes validate/nodes.json --out validate/profiilit.json
"""

import argparse
import csv
import json
import math
import sys

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

MVMI_NODATA = 32767
MVMI_DM_TO_M = 0.1     # MVMI:n keskipituus on desimetreinä


class RasterSampler:
    """Pistepoiminta rasterista bilineaarisesti, EPSG:3067-koordinaateilla."""

    def __init__(self, path, nodata_above=None, scale=1.0):
        self.ds = gdal.Open(path)
        if self.ds is None:
            raise SystemExit("Rasteria ei voi avata: " + path)
        self.gt = self.ds.GetGeoTransform()
        self.band = self.ds.GetRasterBand(1)
        self.nodata = self.band.GetNoDataValue()
        self.nodata_above = nodata_above
        self.scale = scale
        self.w, self.h = self.ds.RasterXSize, self.ds.RasterYSize
        self._cache = {}

    def _block(self, col, row):
        key = (col, row)
        v = self._cache.get(key)
        if v is None:
            if col < 0 or row < 0 or col + 1 >= self.w or row + 1 >= self.h:
                return None
            v = self.band.ReadAsArray(col, row, 2, 2).astype(np.float64)
            if len(self._cache) > 20000:
                self._cache.clear()
            self._cache[key] = v
        return v

    def sample(self, e, n):
        """Arvo pisteessä (E, N) EPSG:3067, tai None jos nodata/ulkopuolella."""
        fx = (e - self.gt[0]) / self.gt[1] - 0.5
        fy = (n - self.gt[3]) / self.gt[5] - 0.5
        col, row = int(math.floor(fx)), int(math.floor(fy))
        blk = self._block(col, row)
        if blk is None:
            return None
        tx, ty = fx - col, fy - row
        vals = blk.copy()
        if self.nodata is not None:
            vals[vals == self.nodata] = np.nan
        if self.nodata_above is not None:
            vals[vals >= self.nodata_above] = np.nan
        if np.isnan(vals).any():
            # Reunalla tai nodatan vieressä: lähin kelvollinen naapuri
            ok = vals[~np.isnan(vals)]
            if ok.size == 0:
                return None
            return float(ok.mean()) * self.scale
        v = (vals[0, 0] * (1 - tx) * (1 - ty) + vals[0, 1] * tx * (1 - ty)
             + vals[1, 0] * (1 - tx) * ty + vals[1, 1] * tx * ty)
        return float(v) * self.scale


def make_transform():
    wgs = osr.SpatialReference(); wgs.ImportFromEPSG(4326)
    tm35 = osr.SpatialReference(); tm35.ImportFromEPSG(3067)
    wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tm35.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(wgs, tm35)


def great_circle_points(lat1, lon1, lat2, lon2, n):
    """n+1 pistettä isoympyrää pitkin, päätepisteet mukaan lukien."""
    p1, l1 = math.radians(lat1), math.radians(lon1)
    p2, l2 = math.radians(lat2), math.radians(lon2)
    d = 2 * math.asin(math.sqrt(
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2))
    pts = []
    for i in range(n + 1):
        f = i / n
        if d < 1e-12:
            pts.append((lat1, lon1))
            continue
        a = math.sin((1 - f) * d) / math.sin(d)
        b = math.sin(f * d) / math.sin(d)
        x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
        y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
        z = a * math.sin(p1) + b * math.sin(p2)
        pts.append((math.degrees(math.atan2(z, math.hypot(x, y))),
                    math.degrees(math.atan2(y, x))))
    return pts


def node_cfg(nodes, node_id):
    """Solmun asetukset: nodes.json:n solmukohtaiset arvot + oletukset."""
    key = "!%08x" % int(node_id)
    cfg = dict(nodes.get("defaults", {}))
    cfg.update(nodes.get("nodes", {}).get(key, {}))
    cfg["_key"] = key
    return cfg


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Havaitut linkit -> P.1812:n maastoprofiilit.")
    ap.add_argument("observations", help="parse_logs.py:n CSV")
    ap.add_argument("--dem", required=True, help="korkeusmallin VRT (EPSG:3067)")
    ap.add_argument("--forest", help="MVMI keskipituus -VRT (dm)")
    ap.add_argument("--nodes", required=True, help="solmuasetukset (JSON)")
    ap.add_argument("--out", required=True, help="ulostulo-JSON")
    ap.add_argument("--step", type=float, default=30.0,
                    help="profiilin näyteväli metreinä (oletus 30)")
    ap.add_argument("--max-points", type=int, default=1500,
                    help="profiilin pisteiden yläraja (oletus 1500)")
    args = ap.parse_args(argv)

    with open(args.nodes, encoding="utf-8") as f:
        nodes = json.load(f)
    with open(args.observations, encoding="utf-8") as f:
        obs = list(csv.DictReader(f))

    dem = RasterSampler(args.dem)
    forest = (RasterSampler(args.forest, nodata_above=MVMI_NODATA,
                            scale=MVMI_DM_TO_M) if args.forest else None)
    tr = make_transform()

    out, skipped = [], {"profiili ulkona aineistosta": 0, "liian lyhyt": 0}
    for i, o in enumerate(obs):
        tx_lat, tx_lon = float(o["tx_lat"]), float(o["tx_lon"])
        rx_lat, rx_lon = float(o["rx_lat"]), float(o["rx_lon"])
        dist = float(o["dist_m"])

        n = max(5, min(args.max_points, int(round(dist / args.step))))
        if dist < 5 * args.step:
            n = 5
        pts = great_circle_points(tx_lat, tx_lon, rx_lat, rx_lon, n)

        d_km, h_m, r_m = [], [], []
        bad = False
        for j, (la, lo) in enumerate(pts):
            e, nn, _ = tr.TransformPoint(lo, la)
            g = dem.sample(e, nn)
            if g is None:
                bad = True
                break
            d_km.append(dist / 1000.0 * j / n)
            h_m.append(round(g, 2))
            rv = forest.sample(e, nn) if forest else None
            r_m.append(round(rv, 2) if rv is not None else 0.0)
        if bad:
            skipped["profiili ulkona aineistosta"] += 1
            continue

        # P.1812 §4.6: latvustoa ei lisätä päätepisteisiin — antennit ovat
        # latvuston sisällä, ja korkeusvahvistus hoidetaan erikseen.
        tx_cfg, rx_cfg = node_cfg(nodes, o["tx_id"]), node_cfg(nodes, o["rx_id"])

        out.append({
            "index": i,
            "time": int(o["time"]),
            "tx": tx_cfg["_key"], "rx": rx_cfg["_key"],
            "tx_lat": tx_lat, "tx_lon": tx_lon,
            "rx_lat": rx_lat, "rx_lon": rx_lon,
            "dist_m": dist,
            "d": d_km, "h": h_m, "R": r_m,
            # Maanpeiteaineistoa ei ole: koko reitti sisämaata (4).
            # Perämeren rannalla tämä on tiedossa oleva virhelähde.
            "zone": [4] * len(d_km),
            "htg": float(tx_cfg.get("antenna_height_m", 2.0)),
            "hrg": float(rx_cfg.get("antenna_height_m", 2.0)),
            "freq_mhz": float(tx_cfg.get("freq_mhz",
                              nodes.get("defaults", {}).get("freq_mhz", 869.525))),
            "pol": int(nodes.get("defaults", {}).get("pol", 2)),
            "tx_power_dbm": float(tx_cfg.get("tx_power_dbm", 27.0)),
            "tx_gain_dbi": float(tx_cfg.get("antenna_gain_dbi", 2.15)),
            "tx_cable_db": float(tx_cfg.get("cable_loss_db", 0.0)),
            "rx_gain_dbi": float(rx_cfg.get("antenna_gain_dbi", 2.15)),
            "rx_cable_db": float(rx_cfg.get("cable_loss_db", 0.0)),
            "rssi": float(o["rssi"]),
            "snr": float(o["snr"]) if o.get("snr") not in (None, "") else None,
            "ground_tx": h_m[0], "ground_rx": h_m[-1],
        })

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f)

    print("Profiileja: %d / %d  ->  %s" % (len(out), len(obs), args.out),
          file=sys.stderr)
    for k, v in skipped.items():
        if v:
            print("  ohitettu, %s: %d" % (k, v), file=sys.stderr)
    if out:
        ns = [len(p["d"]) for p in out]
        print("  profiilipisteitä: %d..%d (näyteväli %.0f m)"
              % (min(ns), max(ns), args.step), file=sys.stderr)
        print("  maanpinta lähettäjillä: %.0f..%.0f m"
              % (min(p["ground_tx"] for p in out),
                 max(p["ground_tx"] for p in out)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
