"""CLI-apufunktioiden testit — eivät vaadi GDAL:ia (import on laiska)."""

import pytest

from pipeline.build_tiles import parse_bounds, parse_zoom


def test_parse_zoom_range():
    assert list(parse_zoom("9-11")) == [9, 10, 11]


def test_parse_zoom_single():
    assert list(parse_zoom("12")) == [12]


def test_parse_zoom_invalid():
    with pytest.raises(ValueError):
        parse_zoom("14-9")
    with pytest.raises(ValueError):
        parse_zoom("0-25")


def test_parse_bounds():
    assert parse_bounds("24,60,26,61") == (24.0, 60.0, 26.0, 61.0)


def test_parse_bounds_invalid():
    with pytest.raises(ValueError):
        parse_bounds("26,60,24,61")
    with pytest.raises(ValueError):
        parse_bounds("24,60,26")
