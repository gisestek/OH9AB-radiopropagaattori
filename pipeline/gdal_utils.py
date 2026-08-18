"""Ohuet kääreet GDAL-kutsuille.

Kaikki GDAL-riippuvuus on tässä moduulissa, jotta terrarium.py ja
tilemath.py pysyvät testattavina ilman GDAL-asennusta.

KORKEUSJÄRJESTELMÄ (tärkeä):
MML:n korkeusmalli on N2000-korkeuksia. EPSG:3067 on 2D-koordinaatisto,
joten gdal.Warp muuntaa vain tasokoordinaatit (3067 -> 3857) eikä PROJ
yritä pystymuunnosta — pikseliarvot (korkeudet) kulkevat läpi
koskemattomina. Tämä on varmistettu testillä
tests/test_pipeline_e2e.py::test_heights_survive_warp.
Jos lähtöaineistoon joskus ilmestyy 3D-CRS (compound CRS), tämä oletus
pitää tarkistaa uudelleen.
"""

import numpy as np

from . import tilemath

# Työskentelyarvo warpin nodatalle. Suomen korkeudet ovat 0..1324 m
# (Halti), joten -32768 ei sekoitu oikeaan dataan.
NODATA = -32768.0


def import_gdal():
    """Palauttaa (gdal, osr) tai kaatuu selkeällä asennusohjeella."""
    try:
        from osgeo import gdal, osr
    except ImportError as e:
        raise SystemExit(
            "GDAL:n Python-sidokset puuttuvat.\n"
            "Asenna esim.:  pip install gdal   (viralliset wheelit, GDAL >= 3.9)\n"
            "tai conda-forge:  conda install -c conda-forge gdal"
        ) from e
    gdal.UseExceptions()
    return gdal, osr


def build_vrt(inputs, out_path):
    """gdalbuildvrt: yhdistä karttalehdet virtuaalirasteriksi (ei mosaikoi
    fyysisesti — VRT on vain viittauslista)."""
    gdal, _ = import_gdal()
    vrt = gdal.BuildVRT(str(out_path), [str(p) for p in inputs])
    if vrt is None:
        raise RuntimeError("gdal.BuildVRT epäonnistui: %s" % out_path)
    vrt.FlushCache()
    return out_path


def source_bounds_lonlat(src_path):
    """Lähderasterin kattavuus WGS84 lon/lat -laatikkona
    (minlon, minlat, maxlon, maxlat).

    Muunnetaan rasterin reunojen pisteistö (ei vain kulmat), koska
    projektiomuunnoksessa laatikon ääriarvot voivat osua reunan
    keskelle.
    """
    gdal, osr = import_gdal()
    ds = gdal.Open(str(src_path))
    gt = ds.GetGeoTransform()
    w, h = ds.RasterXSize, ds.RasterYSize

    src = osr.SpatialReference(ds.GetProjection())
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(4326)
    # Perinteinen lon/lat-järjestys riippumatta EPSG-akselimäärittelystä:
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(src, dst)

    edge = []
    n = 20  # pisteitä per reuna
    for i in range(n + 1):
        t = i / n
        edge += [(t * w, 0.0), (t * w, float(h)), (0.0, t * h), (float(w), t * h)]
    pts = [(gt[0] + c * gt[1] + r * gt[2], gt[3] + c * gt[4] + r * gt[5])
           for c, r in edge]
    ll = [tr.TransformPoint(x, y)[:2] for x, y in pts]
    lons = [p[0] for p in ll]
    lats = [p[1] for p in ll]
    return min(lons), min(lats), max(lons), max(lats)


def warped_vrt_for_zoom(src_path, zoom, tile_x0, tile_y0, tile_x1, tile_y1,
                        resample="bilinear"):
    """Luo muistinvarainen warpattu VRT, joka kattaa ruudut
    [x0..x1] x [y0..y1] zoom-tasolla ja on tasattu täsmälleen
    ruutuhilaan (256 px / ruutu).

    Kaikki saman zoomin ruudut luetaan tästä samasta datasetistä
    ikkunoituna, joten naapuriruutujen resamplaus on identtinen eikä
    saumakohtiin tule artefakteja. VRT on laiska: pikselit lasketaan
    vasta ReadAsArray-kutsussa, joten koko aluetta ei materialisoida.

    resample: 'bilinear' korkeusmallille, 'average' puustolle
    (alaspäin skaalattaessa keskiarvo säilyttää metsän tilastollisen
    peittävyyden paremmin kuin pisteotanta).
    """
    gdal, _ = import_gdal()
    minx, _, _, maxy = tilemath.tile_bounds_3857(tile_x0, tile_y0, zoom)
    _, miny, maxx, _ = tilemath.tile_bounds_3857(tile_x1, tile_y1, zoom)
    res = tilemath.resolution(zoom)
    vrt = gdal.Warp(
        "", str(src_path),
        format="VRT",
        dstSRS="EPSG:3857",
        outputBounds=(minx, miny, maxx, maxy),
        xRes=res, yRes=res,
        resampleAlg=resample,
        dstNodata=NODATA,
        # Pakota Float32: kokonaislukulähteillä (esim. MVMI UInt16)
        # dstNodata=-32768 ei mahtuisi arvoalueeseen ja GDAL leikkaisi sen
        # hiljaa nollaksi, jolloin nodata sekoittuu oikeaan arvoon 0.
        outputType=gdal.GDT_Float32,
        errorThreshold=0.0,  # eksakti muunnos, ei approksimaatiota
    )
    if vrt is None:
        raise RuntimeError("gdal.Warp epäonnistui: %s z%d" % (src_path, zoom))
    return vrt


def read_tile_window(warped_ds, tile_x, tile_y, tile_x0, tile_y0):
    """Lue yhden ruudun 256x256-ikkuna warpatusta VRT:stä.

    Palauttaa float64-taulukon, jossa nodata on NaN, tai None jos ruutu
    on kokonaan nodataa (jätetään kirjoittamatta).
    """
    ts = tilemath.TILE_SIZE
    col = (tile_x - tile_x0) * ts
    row = (tile_y - tile_y0) * ts
    arr = warped_ds.GetRasterBand(1).ReadAsArray(col, row, ts, ts)
    arr = arr.astype(np.float64)
    mask = arr <= NODATA + 0.5
    if mask.all():
        return None
    arr[mask] = np.nan
    return arr
