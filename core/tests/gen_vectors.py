"""Tuota testivektorit ITU:n Py1812-referenssistä core/p1812.js:n testaamiseen.

Ajo VM:llä:
    PYTHONPATH=~/Py1812/src python3 core/tests/gen_vectors.py > core/tests/vectors.json

Vektorit ovat funktiokohtaisia satunnaissyötteitä. Tarkoitus on löytää
poikkeamat yksittäisistä funktioista, ei vain lopputuloksesta — P.1812:n
virheet ovat hiljaisia ja kompensoituvat helposti keskenään.
"""

import json
import sys

import numpy as np

from Py1812 import P1812

rng = np.random.default_rng(20260725)
cases = {}


def profile(n, dmax):
    """Kasvava etäisyysprofiili (km) ja korkeusprofiili (m)."""
    d = np.sort(rng.uniform(0, dmax, n - 2))
    d = np.concatenate(([0.0], d, [dmax]))
    # loivasti aaltoileva maasto + kohinaa
    h = (120 + 90 * np.sin(d / dmax * rng.uniform(1, 6) * np.pi)
         + rng.normal(0, 12, n))
    return d, h


# ── inv_cum_norm ────────────────────────────────────────────────
cases["inv_cum_norm"] = [
    {"x": float(x), "out": float(P1812.inv_cum_norm(x))}
    for x in list(rng.uniform(0, 1, 60)) + [1e-9, 0.5, 1 - 1e-9, 0.0, 1.0]
]

# ── earth_rad_eff ───────────────────────────────────────────────
cases["earth_rad_eff"] = [
    {"DN": float(dn), "out": [float(v) for v in P1812.earth_rad_eff(dn)]}
    for dn in rng.uniform(10, 90, 30)
]

# ── find_intervals ──────────────────────────────────────────────
fi = []
for _ in range(30):
    s = (rng.uniform(0, 1, int(rng.integers(3, 25))) > 0.55).astype(int)
    k1, k2 = P1812.find_intervals(s)
    fi.append({"series": [int(v) for v in s],
               "k1": [int(v) for v in np.atleast_1d(k1)] if len(np.atleast_1d(k1)) else [],
               "k2": [int(v) for v in np.atleast_1d(k2)] if len(np.atleast_1d(k2)) else []})
cases["find_intervals"] = fi

# ── dl_se_ft_inner / dl_se_ft ───────────────────────────────────
inner, seft = [], []
for _ in range(40):
    f = float(rng.uniform(0.03, 6.0))
    d = float(rng.uniform(1, 300))
    hte = float(rng.uniform(1, 300))
    hre = float(rng.uniform(1, 300))
    adft = float(rng.uniform(4000, 20000))
    epsr, sigma = float(rng.choice([22.0, 80.0])), float(rng.choice([0.003, 5.0]))
    inner.append({"epsr": epsr, "sigma": sigma, "d": d, "hte": hte, "hre": hre,
                  "adft": adft, "f": f,
                  "out": [float(v) for v in
                          P1812.dl_se_ft_inner(epsr, sigma, d, hte, hre, adft, f)]})
    omega = float(rng.uniform(0, 1))
    seft.append({"d": d, "hte": hte, "hre": hre, "adft": adft, "f": f, "omega": omega,
                 "out": [float(v) for v in
                         P1812.dl_se_ft(d, hte, hre, adft, f, omega)]})
cases["dl_se_ft_inner"] = inner
cases["dl_se_ft"] = seft

# ── dl_se ───────────────────────────────────────────────────────
se = []
for _ in range(60):
    # sekä LoS (d < dlos) että NLoS haarat: vaihdellaan etäisyyttä laajasti
    f = float(rng.uniform(0.03, 6.0))
    d = float(rng.uniform(0.3, 400))
    hte = float(rng.uniform(1, 400))
    hre = float(rng.uniform(1, 400))
    ap = float(rng.uniform(6000, 20000))
    omega = float(rng.uniform(0, 1))
    se.append({"d": d, "hte": hte, "hre": hre, "ap": ap, "f": f, "omega": omega,
               "out": [float(v) for v in P1812.dl_se(d, hte, hre, ap, f, omega)]})
cases["dl_se"] = se

# ── dl_bull / dl_bull_att4 ──────────────────────────────────────
bull, att4 = [], []
for _ in range(60):
    n = int(rng.integers(8, 120))
    dmax = float(rng.uniform(1, 300))
    d, h = profile(n, dmax)
    hts = float(h[0] + rng.uniform(2, 120))
    hrs = float(h[-1] + rng.uniform(1, 120))
    ap = float(rng.uniform(6000, 20000))
    f = float(rng.uniform(0.03, 6.0))
    bull.append({"d": [float(v) for v in d], "g": [float(v) for v in h],
                 "hts": hts, "hrs": hrs, "ap": ap, "f": f,
                 "out": float(P1812.dl_bull(d, h, hts, hrs, ap, f))})
    att4.append({"dtot": dmax, "hte": float(rng.uniform(1, 300)),
                 "hre": float(rng.uniform(1, 300)), "ap": ap, "f": f})
for c in att4:
    c["out"] = float(P1812.dl_bull_att4(c["dtot"], c["hte"], c["hre"], c["ap"], c["f"]))
cases["dl_bull"] = bull
cases["dl_bull_att4"] = att4

# ── dl_delta_bull / dl_p ────────────────────────────────────────
delta, dlp = [], []
for _ in range(60):
    n = int(rng.integers(8, 100))
    dmax = float(rng.uniform(1, 250))
    d, h = profile(n, dmax)
    R = rng.uniform(0, 25, n)            # edustava latvuskorkeus
    g = h + R
    hts = float(h[0] + rng.uniform(2, 120))
    hrs = float(h[-1] + rng.uniform(1, 120))
    # hstd/hsrd ovat tasoitetun maanpinnan korkeudet paatepisteissa. Mallissa
    # smooth_earth_heights takaa etta hts-hstd > 0; pakotetaan sama tassa,
    # muuten syntyy fysikaalisesti mahdottomia tapauksia (sqrt(negatiivinen)).
    hstd = float(h[0] - rng.uniform(0, 40))
    hsrd = float(h[-1] - rng.uniform(0, 40))
    ap = float(rng.uniform(6000, 20000))
    f = float(rng.uniform(0.03, 6.0))
    omega = float(rng.uniform(0, 1))
    flag4 = int(rng.integers(0, 2))
    Ld, Lbulla, Lbulls, Ldsph = P1812.dl_delta_bull(
        d, g, hts, hrs, hstd, hsrd, ap, f, omega, flag4)
    delta.append({"d": [float(v) for v in d], "g": [float(v) for v in g],
                  "hts": hts, "hrs": hrs, "hstd": hstd, "hsrd": hsrd,
                  "ap": ap, "f": f, "omega": omega, "flag4": flag4,
                  "Ld": [float(v) for v in Ld], "Lbulla": float(Lbulla),
                  "Lbulls": float(Lbulls), "Ldsph": [float(v) for v in Ldsph]})

    p = float(rng.choice([1.0, 5.0, 10.0, 20.0, 50.0]))
    b0 = float(rng.uniform(0.5, 60.0))
    DN = float(rng.uniform(20, 70))
    Ldp, Ldb, Ld50, La, Ls, Lsph = P1812.dl_p(
        d, g, hts, hrs, hstd, hsrd, f, omega, p, b0, DN, flag4)
    dlp.append({"d": [float(v) for v in d], "g": [float(v) for v in g],
                "hts": hts, "hrs": hrs, "hstd": hstd, "hsrd": hsrd,
                "f": f, "omega": omega, "p": p, "b0": b0, "DN": DN, "flag4": flag4,
                "Ldp": [float(v) for v in np.atleast_1d(Ldp)],
                "Ldb": [float(v) for v in np.atleast_1d(Ldb)],
                "Ld50": [float(v) for v in np.atleast_1d(Ld50)]})
cases["dl_delta_bull"] = delta
cases["dl_p"] = dlp

# ── great_circle_path ───────────────────────────────────────────
gc = []
for _ in range(40):
    lam_t = float(rng.uniform(-180, 180))
    lam_r = float(rng.uniform(-180, 180))
    phi_t = float(rng.uniform(-85, 85))
    phi_r = float(rng.uniform(-85, 85))
    Re = 6371.0
    dpnt = float(rng.uniform(0, 3000))
    out = P1812.great_circle_path(lam_r, lam_t, phi_r, phi_t, Re, dpnt)
    gc.append({"Phire": lam_r, "Phite": lam_t, "Phirn": phi_r, "Phitn": phi_t,
               "Re": Re, "dpnt": dpnt, "out": [float(v) for v in out]})
cases["great_circle_path"] = gc

# ── beta0 / stdDev ──────────────────────────────────────────────
cases["beta0"] = [
    {"phi": float(p_), "dtm": float(dtm), "dlm": float(dlm),
     "out": float(P1812.beta0(p_, dtm, dlm))}
    for p_, dtm, dlm in zip(rng.uniform(-89, 89, 40),
                            rng.uniform(0, 500, 40),
                            rng.uniform(0, 500, 40))
]
cases["stdDev"] = [
    {"f": float(f_), "h": float(h_), "R": float(r_), "wa": float(w_),
     "out": float(P1812.stdDev(f_, h_, r_, w_))}
    for f_, h_, r_, w_ in zip(rng.uniform(0.03, 6, 40),
                              rng.uniform(0, 40, 40),
                              rng.uniform(0, 30, 40),
                              rng.uniform(1, 1000, 40))
]

# ── path_fraction / longest_cont_dist ───────────────────────────
pf, lcd = [], []
for _ in range(40):
    n = int(rng.integers(4, 60))
    dmax = float(rng.uniform(1, 300))
    d = np.sort(rng.uniform(0, dmax, n - 2))
    d = np.concatenate(([0.0], d, [dmax]))
    zone = rng.choice([1, 3, 4], size=n)
    zr = int(rng.choice([1, 3, 4]))
    pf.append({"d": [float(v) for v in d], "zone": [int(v) for v in zone],
               "zone_r": zr, "out": float(P1812.path_fraction(d, zone, zr))})
    zr2 = int(rng.choice([1, 3, 4, 34]))
    lcd.append({"d": [float(v) for v in d], "zone": [int(v) for v in zone],
                "zone_r": zr2, "out": float(P1812.longest_cont_dist(d, zone, zr2))})
cases["path_fraction"] = pf
cases["longest_cont_dist"] = lcd

# ── pl_los ──────────────────────────────────────────────────────
cases["pl_los"] = []
for _ in range(40):
    d_ = float(rng.uniform(0.25, 300))
    hts = float(rng.uniform(5, 400))
    hrs = float(rng.uniform(2, 400))
    f_ = float(rng.uniform(0.03, 6))
    p_ = float(rng.uniform(1, 50))
    b0_ = float(rng.uniform(0.5, 60))
    dlt = float(rng.uniform(0.1, d_ / 2))
    dlr = float(rng.uniform(0.1, d_ / 2))
    out = P1812.pl_los(d_, hts, hrs, f_, p_, b0_, dlt, dlr)
    cases["pl_los"].append({"d": d_, "hts": hts, "hrs": hrs, "f": f_, "p": p_,
                            "b0": b0_, "dlt": dlt, "dlr": dlr,
                            "out": [float(v) for v in out]})

# ── smooth_earth_heights ────────────────────────────────────────
seh = []
SEH_KEYS = ["hst_n", "hsr_n", "hst", "hsr", "hstd", "hsrd", "hte", "hre", "hm",
            "dlt", "dlr", "theta_t", "theta_r", "theta_tot", "pathtype"]
while len(seh) < 60:
    n = int(rng.integers(5, 120))
    dmax = float(rng.uniform(1, 300))
    d, h = profile(n, dmax)
    R = rng.uniform(0, 25, n)
    htg = float(rng.uniform(1, 120))
    hrg = float(rng.uniform(1, 60))
    ae = float(rng.uniform(6000, 20000))
    f_ = float(rng.uniform(0.03, 6))
    try:
        out = P1812.smooth_earth_heights(d, h.copy(), R, htg, hrg, ae, f_)
    except ValueError:
        continue   # lt > lr: tyhja alue yhtalossa (95), ohitetaan
    rec = {"d": [float(v) for v in d], "h": [float(v) for v in h],
           "R": [float(v) for v in R], "htg": htg, "hrg": hrg, "ae": ae, "f": f_}
    for k, v in zip(SEH_KEYS, out):
        rec[k] = float(v)
    seh.append(rec)
cases["smooth_earth_heights"] = seh

# ── tl_tropo / tl_anomalous ─────────────────────────────────────
cases["tl_tropo"] = []
for _ in range(40):
    dtot = float(rng.uniform(1, 1000))
    theta = float(rng.uniform(0, 200))
    f_ = float(rng.uniform(0.03, 6))
    p_ = float(rng.uniform(1, 50))
    N0 = float(rng.uniform(280, 400))
    cases["tl_tropo"].append({"dtot": dtot, "theta": theta, "f": f_, "p": p_, "N0": N0,
                              "out": float(P1812.tl_tropo(dtot, theta, f_, p_, N0))})

ano = []
for _ in range(60):
    dtot = float(rng.uniform(5, 600))
    dlt = float(rng.uniform(0.5, dtot / 3))
    dlr = float(rng.uniform(0.5, dtot / 3))
    dct = float(rng.choice([0.0, 2.0, 4.0, 500.0]))
    dcr = float(rng.choice([0.0, 3.0, 500.0]))
    dlm = float(rng.uniform(0, dtot))
    hts = float(rng.uniform(5, 400))
    hrs = float(rng.uniform(2, 400))
    hte = float(rng.uniform(1, 200))
    hre = float(rng.uniform(1, 200))
    hm = float(rng.uniform(0, 80))
    theta_t = float(rng.uniform(-20, 100))
    theta_r = float(rng.uniform(-20, 100))
    f_ = float(rng.uniform(0.03, 6))
    p_ = float(rng.uniform(1, 50))
    omega = float(rng.uniform(0, 1))
    ae = float(rng.uniform(6000, 20000))
    b0_ = float(rng.uniform(0.5, 60))
    ano.append({"dtot": dtot, "dlt": dlt, "dlr": dlr, "dct": dct, "dcr": dcr,
                "dlm": dlm, "hts": hts, "hrs": hrs, "hte": hte, "hre": hre, "hm": hm,
                "theta_t": theta_t, "theta_r": theta_r, "f": f_, "p": p_,
                "omega": omega, "ae": ae, "b0": b0_,
                "out": float(P1812.tl_anomalous(
                    dtot, dlt, dlr, dct, dcr, dlm, hts, hrs, hte, hre, hm,
                    theta_t, theta_r, f_, p_, omega, ae, b0_))})
cases["tl_anomalous"] = ano

# ── bt_loss (paastä paahan) ─────────────────────────────────────
bl = []
while len(bl) < 80:
    n = int(rng.integers(6, 150))
    dmax = float(rng.uniform(1, 400))
    d, h = profile(n, dmax)
    R = np.round(rng.uniform(0, 25, n), 3)
    zone = rng.choice([1, 3, 4], size=n, p=[0.15, 0.15, 0.70])
    htg = float(rng.uniform(1, 200))
    hrg = float(rng.uniform(1, 60))
    pol = int(rng.choice([1, 2]))
    f_ = float(rng.uniform(0.03, 6))
    p_ = float(rng.uniform(1, 50))
    phi_t = float(rng.uniform(-80, 80))
    phi_r = float(phi_t + rng.uniform(-3, 3))
    lam_t = float(rng.uniform(-179, 179))
    lam_r = float(lam_t + rng.uniform(-3, 3))
    kw = dict(pL=float(rng.uniform(1, 99)), sigmaL=float(rng.uniform(0, 8)),
              Ptx=float(rng.uniform(0.001, 10)), Gtx=float(rng.uniform(-3, 20)),
              Grx=float(rng.uniform(-3, 20)), DN=float(rng.uniform(20, 70)),
              N0=float(rng.uniform(280, 400)),
              dct=float(rng.choice([0.0, 3.0, 500.0])),
              dcr=float(rng.choice([0.0, 4.0, 500.0])),
              flag4=int(rng.integers(0, 2)))
    try:
        Lb, Ep = P1812.bt_loss(f_, p_, d, h.copy(), R, zone, htg, hrg, pol,
                               phi_t, phi_r, lam_t, lam_r, **kw)
    except (ValueError, IndexError):
        continue
    if not (np.isfinite(Lb) and np.isfinite(Ep)):
        continue
    bl.append({"f": f_, "p": p_, "d": [float(v) for v in d],
               "h": [float(v) for v in h], "R": [float(v) for v in R],
               "zone": [int(v) for v in zone], "htg": htg, "hrg": hrg, "pol": pol,
               "phi_t": phi_t, "phi_r": phi_r, "lam_t": lam_t, "lam_r": lam_r,
               "opt": kw, "Lb": float(Lb), "Ep": float(Ep)})
cases["bt_loss"] = bl

# allow_nan=False: NaN ei ole kelvollista JSONia, ja sen ilmestyminen
# tarkoittaa etta syotealue on epafysikaalinen — halutaan virhe, ei hiljaista
# viallista vektoritiedostoa.
json.dump(cases, sys.stdout, allow_nan=False)
