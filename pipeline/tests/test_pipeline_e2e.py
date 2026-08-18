"""Päästä päähän -testi synteettisellä aineistolla: pieni EPSG:3067-GeoTIFF
-> XYZ-ruudut -> puretut korkeudet vastaavat lähtöpintaa.

Ohitetaan automaattisesti, jos GDAL:ia ei ole asennettu.

Testipisteiden lon/lat-koordinaatit lasketaan aina osr-muunnoksella
EPSG:3067-koordinaateista — ei käsin arvattuja arvoja, jotta testi ei
riipu siitä missä päin Suomea synteettinen alue sijaitsee.
"""

import numpy as np
import pytest

osgeo = pytest.importorskip("osgeo", reason="GDAL:n Python-sidokset puuttuvat")
from osgeo import gdal, osr  # noqa: E402

from PIL import Image  # noqa: E402

from pipeline import gdal_utils, terrarium, tilemath  # noqa: E402
from pipeline.build_tiles import generate_tiles  # noqa: E402

gdal.UseExceptions()

# Synteettinen korkeuspinta: taso h(E, N) = A + B*E + C*N (EPSG:3067-metreissä).
# Tasolle bilineaarinen interpolointi on (lähes) eksakti, joten putken
# kokonaisvirhe paljastuu suoraan.
A, B, C = 100.0, 0.004, -0.002
# 2 km x 2 km alue Pohjois-Karjalassa, 2 m ruudukko. N0 on YLÄreuna
# (geotransform kulkee pohjoisesta etelään).
E0, N0 = 640000.0, 7003000.0
SIZE = 1000
RES = 2.0
# Alueen keskipiste 3067:ssä:
EC, NC = E0 + SIZE * RES / 2.0, N0 - SIZE * RES / 2.0


def plane(e, n):
    return A + B * (e - E0) + C * (n - N0)


def _transform(src_epsg, dst_epsg):
    src = osr.SpatialReference()
    src.ImportFromEPSG(src_epsg)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(dst_epsg)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(src, dst)


def to_lonlat(e, n):
    lon, lat, _ = _transform(3067, 4326).TransformPoint(e, n)
    return lon, lat


@pytest.fixture(scope="module")
def synthetic_dem(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("dem") / "synth3067.tif")
    cols = E0 + (np.arange(SIZE) + 0.5) * RES
    rows = N0 - (np.arange(SIZE) + 0.5) * RES
    ee, nn = np.meshgrid(cols, rows)
    data = plane(ee, nn).astype(np.float32)

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, SIZE, SIZE, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((E0, RES, 0, N0, 0, -RES))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3067)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(data)
    ds.FlushCache()
    ds = None
    return path


def _pixel_center_3857(tx, ty, zoom, i, j):
    minx, _, _, maxy = tilemath.tile_bounds_3857(tx, ty, zoom)
    res = tilemath.resolution(zoom)
    return minx + (j + 0.5) * res, maxy - (i + 0.5) * res


def _inside_interior(e, n, margin=100.0):
    return (E0 + margin < e < E0 + SIZE * RES - margin
            and N0 - SIZE * RES + margin < n < N0 - margin)


def test_heights_survive_warp(synthetic_dem):
    """N2000-varmistus: warp 3067->3857 ei saa muuttaa korkeusarvoja
    (ei pystymuunnosta). Verrataan warpatun rasterin pikseliarvoa samassa
    maastopisteessä laskettuun tasoon."""
    zoom = 14
    lon, lat = to_lonlat(EC, NC)
    tx, ty = tilemath.lonlat_to_tile(lon, lat, zoom)
    ds = gdal_utils.warped_vrt_for_zoom(synthetic_dem, zoom, tx, ty, tx, ty)
    arr = gdal_utils.read_tile_window(ds, tx, ty, tx, ty)
    assert arr is not None

    # Alueen keskipistettä lähin pikseli (ruudun keskipikseli voi olla
    # datan ulkopuolella, koska z14-ruutu on ~2,4 km eli aluetta suurempi):
    minx, _, _, maxy = tilemath.tile_bounds_3857(tx, ty, zoom)
    res = tilemath.resolution(zoom)
    mxc, myc = tilemath.lonlat_to_3857(lon, lat)
    j = int((mxc - minx) / res)
    i = int((maxy - myc) / res)
    mx, my = _pixel_center_3857(tx, ty, zoom, i, j)
    e, n, _ = _transform(3857, 3067).TransformPoint(mx, my)
    assert _inside_interior(e, n)
    # Sallitaan bilineaarisen resamplauksen virhe tasolla — pieni, koska
    # projektiomuunnos on lokaalisti lähes affiini.
    assert arr[i, j] == pytest.approx(plane(e, n), abs=0.05)


def test_generate_tiles_end_to_end(synthetic_dem, tmp_path):
    out = tmp_path / "tiles"
    written = generate_tiles(synthetic_dem, out, zooms=[13],
                             progress=lambda *a: None)
    assert written >= 1

    # Käy ruutujen pikseleitä harvalla otannalla läpi ja vertaa jokaista
    # aineiston sisään osuvaa pikseliä tasoon.
    tr = _transform(3857, 3067)
    checked = 0
    for png in sorted(out.glob("13/*/*.png")):
        tx = int(png.parent.name)
        ty = int(png.stem)
        rgb = np.asarray(Image.open(png).convert("RGB"))
        h = terrarium.decode(rgb)
        for i in range(8, tilemath.TILE_SIZE, 16):
            for j in range(8, tilemath.TILE_SIZE, 16):
                mx, my = _pixel_center_3857(tx, ty, 13, i, j)
                e, n, _ = tr.TransformPoint(mx, my)
                if not _inside_interior(e, n):
                    continue
                assert h[i, j] == pytest.approx(plane(e, n), abs=0.05)
                checked += 1
    # Alue on ~2 km eli ~100 x 100 px z13:lla -> otannan pitää osua moneen.
    assert checked >= 10


def _write_uint16(path, data, nodata=32767):
    """Kirjoita UInt16-rasteri samaan 3067-ruudukkoon kuin synthetic_dem,
    mutta 16 m pikselillä (MVMI:n tapaan)."""
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(str(path), data.shape[1], data.shape[0], 1,
                    gdal.GDT_UInt16)
    ds.SetGeoTransform((E0, 16.0, 0, N0, 0, -16.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3067)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(data)
    ds.FlushCache()
    return str(path)


def test_forest_uint16_nodata(tmp_path):
    """Regressio: UInt16-lähteellä (MVMI) dstNodata=-32768 ei mahdu
    arvoalueeseen. Ennen korjausta GDAL leikkasi sen nollaksi, jolloin
    nodata sekoittui arvoon 0 eikä yhtään ruutua ohitettu tyhjänä."""
    n = 125  # 2000 m / 16 m
    height_dm = np.full((n, n), 32767, dtype=np.uint16)  # nodata
    cover = np.full((n, n), 32767, dtype=np.uint16)
    # Vain lounaisneljännes on metsää: 150 dm, 60 %.
    height_dm[n // 2:, :n // 2] = 150
    cover[n // 2:, :n // 2] = 60
    kp = _write_uint16(tmp_path / "kp.tif", height_dm)
    lp = _write_uint16(tmp_path / "lp.tif", cover)

    out = tmp_path / "tiles"
    written = generate_tiles(kp, out, zooms=[15], mode="forest",
                             cover_path=lp, height_scale=0.1,
                             progress=lambda *a: None)
    # Datan bbox kattaa z15:llä useita ruutuja; koillisosa on pelkkää
    # nodataa, joten osan kandidaateista PITÄÄ jäädä kirjoittamatta.
    x0, y0, x1, y1 = tilemath.tile_range(
        *gdal_utils.source_bounds_lonlat(kp), 15)
    candidates = (x1 - x0 + 1) * (y1 - y0 + 1)
    assert 1 <= written < candidates

    # Metsäalueen sisäpisteen arvot: R = 15 m, G = 60 %.
    tr = _transform(3857, 3067)
    found = False
    for png in out.glob("15/*/*.png"):
        tx, ty = int(png.parent.name), int(png.stem)
        rgb = np.asarray(Image.open(png).convert("RGB"))
        for i in range(4, tilemath.TILE_SIZE, 8):
            for j in range(4, tilemath.TILE_SIZE, 8):
                mx, my = _pixel_center_3857(tx, ty, 15, i, j)
                e, npos, _ = tr.TransformPoint(mx, my)
                # Reilusti metsäneljänneksen sisällä:
                if (E0 + 100 < e < E0 + n * 16 / 2 - 100
                        and N0 - n * 16 + 100 < npos < N0 - n * 16 / 2 - 100):
                    assert rgb[i, j, 0] == 15
                    assert rgb[i, j, 1] == 60
                    found = True
    assert found


def test_bounds_limit_tile_count(synthetic_dem, tmp_path):
    # Rajaus pieneen laatikkoon alueen keskellä tuottaa vähemmän ruutuja
    # kuin koko alue. z15-ruutu on ~1,2 km, joten koko alue on useampi
    # ruutu ja 400 m laatikko korkeintaan pari.
    lon0, lat0 = to_lonlat(EC - 200, NC - 200)
    lon1, lat1 = to_lonlat(EC + 200, NC + 200)
    bounds = (min(lon0, lon1), min(lat0, lat1),
              max(lon0, lon1), max(lat0, lat1))
    out_all = tmp_path / "all"
    out_box = tmp_path / "box"
    n_all = generate_tiles(synthetic_dem, out_all, zooms=[15],
                           progress=lambda *a: None)
    n_box = generate_tiles(synthetic_dem, out_box, zooms=[15],
                           bounds=bounds, progress=lambda *a: None)
    assert 1 <= n_box < n_all
