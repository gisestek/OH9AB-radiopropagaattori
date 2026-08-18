import numpy as np
import pytest

from pipeline import terrarium


def test_roundtrip_accuracy():
    # Suomen korkeudet + reunatapaukset; kvantisointivirhe <= 1/512 m.
    h = np.array([[-10.0, 0.0, 0.5], [123.456, 1324.0, 4095.996]])
    out = terrarium.decode(terrarium.encode(h))
    assert np.max(np.abs(out - h)) <= 1.0 / 512.0 + 1e-9


def test_roundtrip_random():
    rng = np.random.default_rng(42)
    h = rng.uniform(-100.0, 2000.0, size=(64, 64))
    out = terrarium.decode(terrarium.encode(h))
    assert np.max(np.abs(out - h)) <= 1.0 / 512.0 + 1e-9


def test_known_values():
    # h=0 -> v=32768*256 -> R=128, G=0, B=0 (Terrarium-referenssiarvo).
    rgb = terrarium.encode(np.array([[0.0]]))
    assert tuple(rgb[0, 0]) == (128, 0, 0)
    # AWS-ruutujen tunnettu purku: (R,G,B)=(129,4,128) -> 260.5 m.
    h = terrarium.decode(np.array([[[129, 4, 128]]], dtype=np.uint8))
    assert h[0, 0] == pytest.approx(260.5)


def test_nan_becomes_zero():
    rgb = terrarium.encode(np.array([[np.nan, np.inf]]))
    out = terrarium.decode(rgb)
    assert np.all(out == 0.0)


def test_output_dtype_and_shape():
    rgb = terrarium.encode(np.zeros((256, 256)))
    assert rgb.dtype == np.uint8 and rgb.shape == (256, 256, 3)


def test_forest_roundtrip():
    h = np.array([[0.0, 17.4, 35.0, 300.0]])   # 300 m leikkautuu 255:een
    c = np.array([[0.0, 62.7, 100.0, 150.0]])  # 150 % leikkautuu 100:aan
    rgb = terrarium.encode_forest(h, c)
    dh, dc = terrarium.decode_forest(rgb)
    assert np.allclose(dh, [[0, 17, 35, 255]])
    assert np.allclose(dc, [[0, 63, 100, 100]])
    assert np.all(rgb[..., 2] == 0)  # B-kanava varattu


def test_forest_nan():
    rgb = terrarium.encode_forest(np.array([[np.nan]]), np.array([[np.nan]]))
    assert tuple(rgb[0, 0]) == (0, 0, 0)
