"""Terrarium-korkeuskoodaus (Mapzen/AWS elevation-tiles -yhteensopiva).

Purkukaava (sama kuin selainprototyypissä, kuuluvuus.html):

    h = (R*256 + G + B/256) - 32768   [m]

eli 24-bittinen kokonaisluku v = R*65536 + G*256 + B tulkitaan arvoksi
v/256 - 32768. Askel on 1/256 m ~ 3,9 mm, mikä riittää 2 m korkeusmallille
reilusti. Terrarium-formaatissa ei ole nodata-arvoa: nodata/meri koodataan
korkeudeksi 0 m (N2000-nolla on likimain merenpinta, joten tämä on
fysikaalisesti järkevä täyte).

Metsäruuduille (Luken MVMI) käytetään omaa kanavapakkausta, ks.
encode_forest().
"""

import numpy as np

_OFFSET = 32768.0


def encode(height_m: np.ndarray) -> np.ndarray:
    """Korkeus metreinä (float, NaN = nodata) -> (H, W, 3) uint8 RGB.

    Kvantisointi pyöristää lähimpään 1/256 m askeleeseen, joten
    dekoodausvirhe on enintään 1/512 m.
    """
    h = np.asarray(height_m, dtype=np.float64)
    h = np.where(np.isfinite(h), h, 0.0)
    v = np.rint((h + _OFFSET) * 256.0)
    v = np.clip(v, 0, 256 ** 3 - 1).astype(np.uint32)
    rgb = np.empty(v.shape + (3,), dtype=np.uint8)
    rgb[..., 0] = (v >> 16) & 0xFF
    rgb[..., 1] = (v >> 8) & 0xFF
    rgb[..., 2] = v & 0xFF
    return rgb


def decode(rgb: np.ndarray) -> np.ndarray:
    """(H, W, 3) uint8 RGB -> korkeus metreinä (float64)."""
    r = rgb[..., 0].astype(np.float64)
    g = rgb[..., 1].astype(np.float64)
    b = rgb[..., 2].astype(np.float64)
    return r * 256.0 + g + b / 256.0 - _OFFSET


def encode_forest(height_m: np.ndarray, cover_pct: np.ndarray) -> np.ndarray:
    """Puustoruudun kanavapakkaus:

        R = puuston keskipituus metreinä (0..255, kokonaisluku)
        G = latvuspeittävyys prosentteina (0..100)
        B = varattu tulevalle käytölle (nyt 0)

    NaN (nodata, esim. vesistö tai ei-metsämaa) -> 0 molemmissa kanavissa.
    Huom: Luken MVMI ilmoittaa keskipituuden desimetreinä — muunnos metreiksi
    tehdään ennen tätä funktiota (build_tiles.py: --height-scale).
    """
    h = np.asarray(height_m, dtype=np.float64)
    c = np.asarray(cover_pct, dtype=np.float64)
    h = np.where(np.isfinite(h), h, 0.0)
    c = np.where(np.isfinite(c), c, 0.0)
    rgb = np.zeros(h.shape + (3,), dtype=np.uint8)
    rgb[..., 0] = np.clip(np.rint(h), 0, 255).astype(np.uint8)
    rgb[..., 1] = np.clip(np.rint(c), 0, 100).astype(np.uint8)
    return rgb


def decode_forest(rgb: np.ndarray):
    """(H, W, 3) uint8 -> (keskipituus_m, peittävyys_pct) float64-pareina."""
    return rgb[..., 0].astype(np.float64), rgb[..., 1].astype(np.float64)
