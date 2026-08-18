"""Poimi ITU:n VIRALLISET validointiprofiilit JSON-muotoon core/p1812.js:lle.

Tämä on CLAUDE.md:n vaatima ehdoton testi: JS-portti ajetaan täsmälleen
samoilla syötteillä kuin ITU:n oma validointiaineisto, ja tulosta verrataan
aineiston referenssiarvoon (MeasuredFieldStrength = odotettu kentänvoimakkuus).

Logiikka on kopioitu Py1812:n validateP1812.py:stä, jotta syötteet
rakennetaan identtisesti (mm. latvuskorkeuksien täydennys päätepisteissä).

Ajo VM:llä:
    cd ~/Py1812/tests
    PYTHONPATH=~/Py1812/src python3 ~/oh9ab/core/tests/itu_vectors.py \
        > ~/oh9ab/core/tests/itu_vectors.json
"""

import json
import os
import sys

import numpy as np

from Py1812 import P1812

PATHNAME = "./validation_profiles/"
FILEFORMAT = "Fryderyk_csv"
CLUTTER_CODE = "GlobCover"
FLAG4 = 0
PL = 50
SIGMAL = 0

out = []
files = sorted(f for f in os.listdir(PATHNAME) if f.endswith(".csv"))
if not files:
    raise IOError("validointiprofiileja ei löytynyt: " + PATHNAME)

for fn in files:
    sg3db = P1812.read_sg3_measurements2(PATHNAME + fn, FILEFORMAT)
    sg3db.debug = 0
    sg3db.pathinfo = 1

    # Lähetysteho kW, kuten validateP1812.py
    for kindex in range(0, sg3db.Ndata):
        PERP = sg3db.ERPMaxTotal[kindex]
        PkW = 10.0 ** (PERP / 10.0) * 1e-3
        if np.isnan(PkW):
            E = sg3db.MeasuredFieldStrength[kindex]
            PL_ = sg3db.BasicTransmissionLoss[kindex]
            f_ = sg3db.frequency[kindex]
            PdBkW = -137.2217 + E - 20 * np.log10(f_) + PL_
            PkW = 10 ** (PdBkW / 10.0)
        sg3db.TransmittedPower = np.append(sg3db.TransmittedPower, PkW)

    hRx = sg3db.hRx

    for measID in range(0, len(hRx)):
        sg3db.userChoiceInt = measID

        # Latvuskorkeuksien täydennys päätepisteissä (validateP1812.py)
        if not P1812.isempty(sg3db.coveragecode):
            i = sg3db.coveragecode[-1]
            RxClutterCode, RxP1546Clutter, R2external = P1812.clutter(i, CLUTTER_CODE)
            i = sg3db.coveragecode[0]
            TxClutterCode, TxP1546Clutter, R1external = P1812.clutter(i, CLUTTER_CODE)
            sg3db.RxClutterCodeP1546 = RxP1546Clutter
            if not P1812.isempty(sg3db.h_ground_cover):
                if not np.isnan(sg3db.h_ground_cover[-1]):
                    sg3db.RxClutterHeight = (sg3db.h_ground_cover[-1]
                                             if sg3db.h_ground_cover[-1] > 3 else R2external)
                else:
                    sg3db.RxClutterHeight = R2external
                if not np.isnan(sg3db.h_ground_cover[0]):
                    sg3db.TxClutterHeight = (sg3db.h_ground_cover[0]
                                             if sg3db.h_ground_cover[0] > 3 else R1external)
                else:
                    sg3db.TxClutterHeight = R1external
            else:
                sg3db.RxClutterHeight = R2external
                sg3db.TxClutterHeight = R1external

        dct = 0 if sg3db.radio_met_code[0] == 1 else 500
        dcr = 0 if sg3db.radio_met_code[-1] == 1 else 500

        kw = dict(pL=PL, sigmaL=SIGMAL,
                  Ptx=float(sg3db.TransmittedPower[measID]),
                  DN=float(sg3db.DN), N0=float(sg3db.N0),
                  dct=float(dct), dcr=float(dcr), flag4=FLAG4)

        Lb, Ep = P1812.bt_loss(
            sg3db.frequency[measID] / 1e3,
            sg3db.TimePercent[measID],
            sg3db.x,
            sg3db.h_gamsl,
            sg3db.h_ground_cover,
            sg3db.radio_met_code,
            sg3db.hTx[measID],
            sg3db.hRx[measID],
            sg3db.polHVC[measID],
            sg3db.TxLAT, sg3db.RxLAT, sg3db.TxLON, sg3db.RxLON,
            **kw)

        out.append({
            "file": fn, "measID": measID,
            "f": float(sg3db.frequency[measID] / 1e3),
            "p": float(sg3db.TimePercent[measID]),
            "d": [float(v) for v in sg3db.x],
            "h": [float(v) for v in sg3db.h_gamsl],
            "R": [float(v) for v in sg3db.h_ground_cover],
            "zone": [int(v) for v in sg3db.radio_met_code],
            "htg": float(sg3db.hTx[measID]), "hrg": float(sg3db.hRx[measID]),
            "pol": int(sg3db.polHVC[measID]),
            "phi_t": float(sg3db.TxLAT), "phi_r": float(sg3db.RxLAT),
            "lam_t": float(sg3db.TxLON), "lam_r": float(sg3db.RxLON),
            "opt": kw,
            "Lb": float(Lb), "Ep": float(Ep),
            # ITU:n aineiston referenssiarvo, jota vasten validateP1812.py vertaa
            "Ep_ref": float(sg3db.MeasuredFieldStrength[measID]),
        })

json.dump(out, sys.stdout, allow_nan=False)
print("", file=sys.stderr)
print("Tapauksia: %d, tiedostoja: %d" % (len(out), len(files)), file=sys.stderr)
