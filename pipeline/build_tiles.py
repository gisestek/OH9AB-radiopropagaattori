"""Datankäsittelyputken CLI: EPSG:3067-rasterit -> XYZ-PNG-ruudut (EPSG:3857).

Käyttö:

  # 1) Yhdistä karttalehdet virtuaalirasteriksi (ei kopioi dataa):
  python pipeline/build_tiles.py vrt --input data/dem/*.tif --out data/dem.vrt

  # 2) Korkeusruudut (Terrarium-koodaus):
  python pipeline/build_tiles.py tiles --input data/dem.vrt \
      --out tiles/dem --zoom 9-14

  # 3) Puustoruudut (R = keskipituus m, G = latvuspeittävyys %):
  python pipeline/build_tiles.py tiles --mode forest \
      --input data/mvmi_keskipituus.vrt --input-cover data/mvmi_latvus.vrt \
      --height-scale 0.1 --out tiles/forest --zoom 9-14

Testialueen voi rajata: --bounds minlon,minlat,maxlon,maxlat

Ulostulo on tavallinen slippy-XYZ-hakemistopuu out/{z}/{x}/{y}.png, jonka
selainprototyyppi lukee custom-ruutulähteenä.

Korkeudet ovat N2000-korkeuksia lähtöaineiston mukaisesti; putki ei tee
(eikä saa tehdä) pystymuunnoksia — ks. gdal_utils.py.
"""

import argparse
import glob
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

# Tukee sekä `python pipeline/build_tiles.py` että `python -m pipeline.build_tiles`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline import gdal_utils, terrarium, tilemath
else:
    from . import gdal_utils, terrarium, tilemath


def print_flush(*args):
    """Oletustulostus edistymiselle; flush jotta nohup-loki päivittyy
    reaaliajassa eikä jää puskuriin."""
    print(*args, flush=True)


def parse_zoom(spec: str):
    """'9-14' -> range(9, 15); '12' -> range(12, 13)."""
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        lo, hi = int(lo), int(hi)
    else:
        lo = hi = int(spec)
    if not (0 <= lo <= hi <= 18):
        raise ValueError("zoom-väli %s ei kelpaa" % spec)
    return range(lo, hi + 1)


def parse_bounds(spec: str):
    """'minlon,minlat,maxlon,maxlat' -> tuple[float, 4]."""
    parts = [float(p) for p in spec.split(",")]
    if len(parts) != 4 or parts[0] >= parts[2] or parts[1] >= parts[3]:
        raise ValueError("bounds %s ei kelpaa" % spec)
    return tuple(parts)


def cmd_vrt(args):
    inputs = []
    for pattern in args.input:
        hits = sorted(glob.glob(pattern))
        inputs += hits if hits else [pattern]
    if not inputs:
        raise SystemExit("Yhtään syötetiedostoa ei löytynyt.")
    gdal_utils.build_vrt(inputs, args.out)
    print("VRT kirjoitettu: %s (%d lähdettä)" % (args.out, len(inputs)))


def generate_tiles(src_path, out_dir, zooms, mode="elevation",
                   cover_path=None, height_scale=1.0, bounds=None,
                   progress=print_flush):
    """Putken ydin, kutsuttavissa myös testeistä ilman CLI:tä.

    Palauttaa kirjoitettujen ruutujen määrän.
    """
    out_dir = Path(out_dir)
    if bounds is None:
        bounds = gdal_utils.source_bounds_lonlat(src_path)
        progress("Kattavuus lähteestä: lon %.4f..%.4f lat %.4f..%.4f" % (
            bounds[0], bounds[2], bounds[1], bounds[3]))

    written = 0
    t_start = time.time()
    for zoom in zooms:
        x0, y0, x1, y1 = tilemath.tile_range(*bounds, zoom)
        n_tiles = (x1 - x0 + 1) * (y1 - y0 + 1)
        progress("z%d: %d ruutua (x %d..%d, y %d..%d)" % (
            zoom, n_tiles, x0, x1, y0, y1))

        # Keskiarvo myös korkeudelle: bilineaarinen on isossa alaspäin-
        # skaalauksessa (z9-12: 2 m lähde -> 30-250 m pikseli) käytännössä
        # pistepoimintaa, joka aliasoi mikroreliefin (esim. suo-ojaverkot)
        # hilakuvioiksi. Keskiarvo pikselin jalanjäljen yli on oikea
        # antialiasoiva suodatus, ja etenemislaskennalle pikselin
        # keskikorkeus on juuri haluttu suure.
        resample = "average"
        ds = gdal_utils.warped_vrt_for_zoom(src_path, zoom, x0, y0, x1, y1,
                                            resample)
        ds_cover = None
        if mode == "forest":
            if cover_path is None:
                raise ValueError("forest-tila vaatii --input-cover")
            ds_cover = gdal_utils.warped_vrt_for_zoom(
                cover_path, zoom, x0, y0, x1, y1, resample)

        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                arr = gdal_utils.read_tile_window(ds, tx, ty, x0, y0)
                if arr is None:
                    continue
                if mode == "elevation":
                    rgb = terrarium.encode(arr)
                else:
                    cover = gdal_utils.read_tile_window(ds_cover, tx, ty,
                                                        x0, y0)
                    if cover is None:
                        cover = np.full_like(arr, np.nan)
                    rgb = terrarium.encode_forest(arr * height_scale, cover)
                tile_dir = out_dir / str(zoom) / str(tx)
                tile_dir.mkdir(parents=True, exist_ok=True)
                Image.fromarray(rgb, "RGB").save(tile_dir / ("%d.png" % ty))
                written += 1
        # Vapauta warpatut VRT:t ennen seuraavaa zoomia.
        ds = None
        ds_cover = None

    progress("Valmis: %d ruutua kirjoitettu (%.1f s) -> %s" % (
        written, time.time() - t_start, out_dir))
    return written


def cmd_tiles(args):
    bounds = parse_bounds(args.bounds) if args.bounds else None
    generate_tiles(
        src_path=args.input,
        out_dir=args.out,
        zooms=parse_zoom(args.zoom),
        mode=args.mode,
        cover_path=args.input_cover,
        height_scale=args.height_scale,
        bounds=bounds,
    )


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="MML/Luke-rasterit -> XYZ-PNG-ruudut selainta varten.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_vrt = sub.add_parser("vrt", help="yhdistä karttalehdet VRT:ksi")
    ap_vrt.add_argument("--input", nargs="+", required=True,
                        help="tiedostot tai glob-kuviot (esim. data/*.tif)")
    ap_vrt.add_argument("--out", required=True, help="ulostulo-VRT")
    ap_vrt.set_defaults(func=cmd_vrt)

    ap_t = sub.add_parser("tiles", help="tuota XYZ-PNG-ruudut")
    ap_t.add_argument("--input", required=True,
                      help="lähderasteri (VRT tai GeoTIFF, EPSG:3067)")
    ap_t.add_argument("--out", required=True, help="ruutuhakemiston juuri")
    ap_t.add_argument("--zoom", default="9-14", help="esim. 9-14 tai 12")
    ap_t.add_argument("--mode", choices=("elevation", "forest"),
                      default="elevation")
    ap_t.add_argument("--input-cover",
                      help="latvuspeittävyysrasteri (vain --mode forest)")
    ap_t.add_argument("--height-scale", type=float, default=1.0,
                      help="kerroin lähteen korkeusyksiköstä metreihin "
                           "(MVMI: dm -> m = 0.1)")
    ap_t.add_argument("--bounds",
                      help="rajaus: minlon,minlat,maxlon,maxlat (WGS84)")
    ap_t.set_defaults(func=cmd_tiles)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
