import math

import pytest

from pipeline import tilemath


def test_resolution_z0():
    # z0: koko maailma yhdessä 256 px ruudussa.
    assert tilemath.resolution(0) == pytest.approx(2 * tilemath.ORIGIN / 256)


def test_helsinki_tile_z10():
    # Helsinki (24.9384 E, 60.1699 N) @ z10.
    # Referenssi: OSM slippy map -kaava, n=1024:
    #   x = (24.9384+180)/360*1024 = 582.93 -> 582
    #   y = (1 - asinh(tan(60.1699 deg))/pi)/2*1024 = 296.43 -> 296
    x, y = tilemath.lonlat_to_tile(24.9384, 60.1699, 10)
    assert (x, y) == (582, 296)


def test_tile_bounds_world():
    # z0-ruutu (0,0) kattaa koko maailman.
    minx, miny, maxx, maxy = tilemath.tile_bounds_3857(0, 0, 0)
    o = tilemath.ORIGIN
    assert (minx, miny, maxx, maxy) == pytest.approx((-o, -o, o, o))


def test_tile_contains_its_point():
    # Pisteen ruudun rajojen pitää sisältää pisteen 3857-koordinaatit.
    lon, lat = 29.816, 63.100  # prototyypin oletusnäkymä (Koli)
    for z in (9, 12, 14):
        x, y = tilemath.lonlat_to_tile(lon, lat, z)
        minx, miny, maxx, maxy = tilemath.tile_bounds_3857(x, y, z)
        mx, my = tilemath.lonlat_to_3857(lon, lat)
        assert minx <= mx <= maxx
        assert miny <= my <= maxy


def test_adjacent_tiles_share_edge():
    a = tilemath.tile_bounds_3857(10, 10, 12)
    b = tilemath.tile_bounds_3857(11, 10, 12)
    assert a[2] == pytest.approx(b[0])


def test_tile_range_orientation():
    # Pohjoisempi leveysaste -> pienempi y-indeksi.
    x0, y0, x1, y1 = tilemath.tile_range(24.0, 60.0, 26.0, 61.0, 10)
    assert x0 <= x1 and y0 <= y1
    _, y_north = tilemath.lonlat_to_tile(25.0, 61.0, 10)
    _, y_south = tilemath.lonlat_to_tile(25.0, 60.0, 10)
    assert y_north == y0 and y_south == y1


def test_lonlat_to_3857_reference():
    # Tunnettu arvo: lon 180 -> ORIGIN; lat 0 -> 0.
    mx, my = tilemath.lonlat_to_3857(180.0, 0.0)
    assert mx == pytest.approx(tilemath.ORIGIN)
    assert my == pytest.approx(0.0, abs=1e-9)
