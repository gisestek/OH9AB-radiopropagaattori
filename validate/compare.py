"""Vertaa mitattua ja mallinnettua vastaanottotasoa; kalibroi R-kerroin.

Ajo:
    python3 validate/compare.py validate/ennusteet.json
    python3 validate/compare.py validate/ennusteet.json --scatter validate/sirontakuvio.csv

Kalibrointi (ajaa predict.js:n useilla R-kertoimilla ja etsii pienimmän RMSE:n):
    python3 validate/compare.py --calibrate validate/profiilit.json \
        --dn 45 --n0 325 --r-range 0.5 2.0 --r-steps 16

LORA-RSSI:N KORJAUS (--snr-correct):
Kun SNR < 0, LoRa-vastaanotin raportoi RSSI:ksi kohinatason eikä signaalin
tehoa, koska signaali on kohinan alla. Todellinen signaaliteho on tällöin
likimain RSSI + SNR. Tämä koskee juuri niitä heikkoja linkkejä, joista
mallin tarkkuus ratkeaa, joten korjauksella on iso vaikutus tuloksiin.
Korjaus on OLETUKSENA POIS, koska se riippuu radiopiiristä ja firmwaren
tavasta raportoida — kytke se päälle vasta kun tiedät kumpaa lukua
solmusi raportoivat.
"""

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def residuals(rows, snr_correct=False, max_dist=None, min_dist=None):
    out = []
    for r in rows:
        if max_dist is not None and r["dist_m"] > max_dist:
            continue
        if min_dist is not None and r["dist_m"] < min_dist:
            continue
        meas = r["rssi_meas"]
        if snr_correct and r.get("snr_meas") is not None and r["snr_meas"] < 0:
            meas = meas + r["snr_meas"]
        out.append((r, meas - r["rssi_pred"]))
    return out


def stats(res):
    if not res:
        return None
    v = [d for _, d in res]
    n = len(v)
    bias = sum(v) / n
    rmse = math.sqrt(sum(x * x for x in v) / n)
    sd = math.sqrt(sum((x - bias) ** 2 for x in v) / n) if n > 1 else 0.0
    s = sorted(v)
    return {"n": n, "bias": bias, "rmse": rmse, "sd": sd,
            "p10": s[int(0.10 * (n - 1))], "med": s[int(0.50 * (n - 1))],
            "p90": s[int(0.90 * (n - 1))], "min": s[0], "max": s[-1]}


def print_stats(title, st):
    if not st:
        print("  %-24s (ei havaintoja)" % title)
        return
    print("  %-24s n=%-5d poikkeama %+6.1f  RMSE %5.1f  hajonta %5.1f  "
          "[%+.0f .. %+.0f]"
          % (title, st["n"], st["bias"], st["rmse"], st["sd"],
             st["p10"], st["p90"]))


def report(rows, snr_correct):
    res = residuals(rows, snr_correct)
    st = stats(res)
    if not st:
        print("Ei havaintoja.", file=sys.stderr)
        return

    print("\nJÄÄNNÖS = mitattu − mallinnettu (dB). Positiivinen = malli "
          "aliarvioi kuuluvuuden.\n")
    print_stats("Kaikki", st)

    print("\nEtäisyysluokittain:")
    bins = [(0, 1000), (1000, 3000), (3000, 6000), (6000, 12000),
            (12000, 25000), (25000, 1e9)]
    for lo, hi in bins:
        sub = [x for x in res if lo <= x[0]["dist_m"] < hi]
        label = "%.0f–%.0f km" % (lo / 1000, hi / 1000) if hi < 1e9 else ">25 km"
        print_stats(label, stats(sub))

    print("\nReittityypeittäin:")
    for pt, name in ((1, "näköyhteys"), (2, "esteinen")):
        sub = [x for x in res if x[0].get("pathtype") == pt]
        print_stats(name, stats(sub))

    print("\nTulkinta:")
    print("  Poikkeama on systemaattinen virhe — se pitää saada lähelle nollaa")
    print("  kalibroimalla (--calibrate). Hajonta on satunnaisvaihtelu, joka")
    print("  vastaa P.1812:n paikkavaihtelutermiä: jos se on ~6–10 dB, malli")
    print("  käyttäytyy odotetusti. Jos hajonta on paljon suurempi, vika on")
    print("  todennäköisemmin aineistossa (antennikorkeudet, sijainnit) kuin")
    print("  mallissa.")


def calibrate(profiles, dn, n0, r_lo, r_hi, steps, snr_correct, workdir):
    root = Path(__file__).resolve().parent.parent
    tmp = Path(workdir) / "_kalibrointi.json"
    print("R-kerroin   n      poikkeama   RMSE")
    best = None
    for i in range(steps):
        k = r_lo + (r_hi - r_lo) * i / max(1, steps - 1)
        cmd = ["node", str(root / "validate" / "predict.js"), str(profiles),
               "--dn", str(dn), "--n0", str(n0), "--r-scale", "%.4f" % k,
               "--out", str(tmp)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            print("predict.js epäonnistui:", p.stderr.strip(), file=sys.stderr)
            return
        st = stats(residuals(load(tmp), snr_correct))
        if not st:
            continue
        print("  %6.3f  %5d   %+8.2f  %6.2f" % (k, st["n"], st["bias"], st["rmse"]))
        if best is None or st["rmse"] < best[1]["rmse"]:
            best = (k, st)
    if best:
        print("\nPienin RMSE kertoimella R_eff = %.3f × R_MVMI  "
              "(RMSE %.2f dB, poikkeama %+.2f dB)"
              % (best[0], best[1]["rmse"], best[1]["bias"]))
        print("Huom: kerroin kalibroi VAIN sen, miten MVMI:n keskipituus")
        print("tulkitaan P.1812:n edustavaksi latvuskorkeudeksi. Mallia ei")
        print("muuteta. Jos kerroin karkaa kauas ykkösestä, epäile ensin")
        print("antennikorkeuksia ja sijaintitietoja.")
    if tmp.exists():
        tmp.unlink()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mitattu vs. mallinnettu.")
    ap.add_argument("predictions", nargs="?", help="predict.js:n JSON")
    ap.add_argument("--snr-correct", action="store_true",
                    help="korjaa RSSI arvolla RSSI+SNR kun SNR<0 (ks. moduulin ohje)")
    ap.add_argument("--scatter", help="kirjoita sirontakuvion data CSV:ksi")
    ap.add_argument("--calibrate", metavar="PROFIILIT",
                    help="kalibroi R-kerroin annetuilla profiileilla")
    ap.add_argument("--dn", type=float, help="ΔN kalibrointia varten")
    ap.add_argument("--n0", type=float, help="N₀ kalibrointia varten")
    ap.add_argument("--r-range", nargs=2, type=float, default=[0.5, 2.0])
    ap.add_argument("--r-steps", type=int, default=16)
    args = ap.parse_args(argv)

    if args.calibrate:
        if args.dn is None or args.n0 is None:
            ap.error("--calibrate vaatii --dn ja --n0")
        calibrate(args.calibrate, args.dn, args.n0, args.r_range[0],
                  args.r_range[1], args.r_steps, args.snr_correct,
                  Path(args.calibrate).parent)
        return 0

    if not args.predictions:
        ap.error("anna ennuste-JSON tai --calibrate")

    rows = load(args.predictions)
    report(rows, args.snr_correct)

    if args.scatter:
        import csv
        res = residuals(rows, args.snr_correct)
        with open(args.scatter, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["dist_m", "rssi_meas", "rssi_pred", "residual",
                        "pathtype", "tx", "rx"])
            for r, d in res:
                w.writerow([r["dist_m"], r["rssi_meas"], round(r["rssi_pred"], 2),
                            round(d, 2), r.get("pathtype", ""), r["tx"], r["rx"]])
        print("\nSirontakuvion data: %s" % args.scatter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
