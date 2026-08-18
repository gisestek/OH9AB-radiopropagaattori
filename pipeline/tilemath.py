"""Slippy map -ruutumatematiikka (XYZ-skeema, EPSG:3857).

Kaavat: https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames
Ruudun koko on 256 px, origo vasen yläkulma (kuten OSM/Leaflet).

Web-Mercatorin maailman puolileveys on pi * 6378137 m; koko maailma
kattaa [-ORIGIN, ORIGIN] molemmilla akseleilla.
"""

import math

TILE_SIZE = 256
ORIGIN = math.pi * 6378137.0  # 20037508.342789244 m


def resolution(zoom: int) -> float:
    """Metriä per pikseli (EPSG:3857-metriä, ei maastometriä) zoom-tasolla."""
    return 2.0 * ORIGIN / (TILE_SIZE * 2 ** zoom)


def lonlat_to_tile(lon: float, lat: float, zoom: int):
    """WGS84 lon/lat -> (x, y) ruutuindeksi."""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    # Reunatapaukset (lon=180, lat=raja) leikataan ruudukon sisään.
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tile_bounds_3857(x: int, y: int, zoom: int):
    """Ruudun (x, y, z) rajat EPSG:3857-metreinä: (minx, miny, maxx, maxy)."""
    size = 2.0 * ORIGIN / 2 ** zoom
    minx = -ORIGIN + x * size
    maxy = ORIGIN - y * size
    return (minx, maxy - size, minx + size, maxy)


def lonlat_to_3857(lon: float, lat: float):
    """WGS84 -> EPSG:3857 (sferinen Mercator)."""
    mx = ORIGIN * lon / 180.0
    my = ORIGIN * math.asinh(math.tan(math.radians(lat))) / math.pi
    return mx, my


def tile_range(minlon: float, minlat: float, maxlon: float, maxlat: float,
               zoom: int):
    """Lon/lat-laatikon kattavat ruutuindeksit: (x0, y0, x1, y1), rajat
    mukaan lukien. Huom: y kasvaa etelään (pohjoinen = pienin y)."""
    x0, y0 = lonlat_to_tile(minlon, maxlat, zoom)
    x1, y1 = lonlat_to_tile(maxlon, minlat, zoom)
    return x0, y0, x1, y1
