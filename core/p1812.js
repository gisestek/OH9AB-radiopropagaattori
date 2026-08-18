/* ═══════════════════════════════════════════════════════════════
   ITU-R P.1812-8 — porttaus ITU:n referenssitoteutuksesta

   Lähde:  Recommendation ITU-R P.1812-8 (09/2025)
           "A path-specific propagation prediction method for
            point-to-area terrestrial services in the VHF and UHF bands"
   Referenssi: https://github.com/eeveetza/Py1812  (Ivica Stevanović, OFCOM)

   Tämä on TARKOITUKSELLA rivi riviltä uskollinen käännös referenssistä,
   ei uudelleentulkinta. Yhtälönumerot kommenteissa viittaavat
   suositukseen, jotta koodi voidaan tarkistaa alkuperäistä dokumenttia
   vasten. Älä "siisti" logiikkaa — poikkeamat ovat hiljaisia.

   Testattu ITU:n omia validointiprofiileja ja Py1812:n funktiokohtaisia
   vektoreita vasten, ks. core/tests/.

   Toimii sekä Nodessa (module.exports) että selaimessa (window.P1812).
   ═══════════════════════════════════════════════════════════════ */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.P1812 = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const log10 = x => Math.log(x) / Math.LN10;

  /* ── Attachment 2 to Annex 1: käänteinen kumulatiivinen normaali ── */

  function T(y) { return Math.sqrt(-2.0 * Math.log(y)); }            // (97a)

  function C(z) {                                                    // (97b)
    const C0 = 2.515516698, C1 = 0.802853, C2 = 0.010328;
    const D1 = 1.432788, D2 = 0.189269, D3 = 0.001308;
    const t = T(z);
    return (((C2 * t + C1) * t) + C0) / (((D3 * t + D2) * t + D1) * t + 1);
  }

  function inv_cum_norm(x) {
    if (x < 0.000001) x = 0.000001;
    if (x > 0.999999) x = 0.999999;
    if (x <= 0.5) return T(x) - C(x);                                // (96a)
    return -(T(1 - x) - C(1 - x));                                   // (96b)
  }

  /* ── §4.3: efektiivinen maan säde ─────────────────────────────── */

  function earth_rad_eff(DN) {
    const k50 = 157 / (157 - DN);                                    // (6)
    const ae = 6371 * k50;                                           // (7a)
    const kbeta = 3;
    const ab = 6371 * kbeta;                                         // (7b)
    return [ae, ab];
  }

  /* Kaikki peräkkäiset ykkösjaksot: palauttaa alku- ja loppuindeksit
     (loppu mukaan lukien), kuten referenssin find_intervals. */
  function find_intervals(series) {
    const k1 = [], k2 = [], n = series.length;
    let any = false;
    for (let i = 0; i < n; i++) if (series[i]) { any = true; break; }
    if (!any) return [k1, k2];
    for (let i = 0; i < n; i++) {
      const prev = i === 0 ? 0 : (series[i - 1] ? 1 : 0);
      const cur = series[i] ? 1 : 0;
      if (cur - prev === 1) k1.push(i);
    }
    for (let i = 0; i < n; i++) {
      const cur = series[i] ? 1 : 0;
      const next = i === n - 1 ? 0 : (series[i + 1] ? 1 : 0);
      if (next - cur === -1) k2.push(i);
    }
    return [k1, k2];
  }

  /* ── §4.3.3: pallomaisen maan diffraktion ensimmäinen termi ───── */

  // Palauttaa [horisontaali, vertikaali] — polarisaatiot lasketaan rinnan.
  function dl_se_ft_inner(epsr, sigma, d, hte, hre, adft, f) {
    const K = new Array(2);
    K[0] = 0.036 * Math.pow(adft * f, -1.0 / 3.0)
         * Math.pow(Math.pow(epsr - 1, 2) + Math.pow(18 * sigma / f, 2.0), -1.0 / 4.0); // (29a)
    K[1] = K[0] * Math.pow(Math.pow(epsr, 2) + Math.pow(18 * sigma / f, 2), 1.0 / 2.0); // (29b)

    const beta_dft = new Array(2), X = new Array(2), Yt = new Array(2), Yr = new Array(2);
    for (let i = 0; i < 2; i++) {
      const k2 = K[i] * K[i], k4 = k2 * k2;
      beta_dft[i] = (1 + 1.6 * k2 + 0.67 * k4) / (1 + 4.5 * k2 + 1.53 * k4);           // (30)
      X[i] = 21.88 * beta_dft[i] * Math.pow(f / (adft * adft), 1.0 / 3.0) * d;         // (31)
      Yt[i] = 0.9575 * beta_dft[i] * Math.pow(f * f / adft, 1 / 3) * hte;              // (32a)
      Yr[i] = 0.9575 * beta_dft[i] * Math.pow(f * f / adft, 1 / 3) * hre;              // (32b)
    }

    const Fx = new Array(2), GYt = new Array(2), GYr = new Array(2), Ldft = new Array(2);
    for (let i = 0; i < 2; i++) {
      if (X[i] >= 1.6) Fx[i] = 11 + 10 * log10(X[i]) - 17.6 * X[i];
      else Fx[i] = -20 * log10(X[i]) - 5.6488 * Math.pow(X[i], 1.425);                 // (33)

      const Bt = beta_dft[i] * Yt[i];                                                  // (35)
      const Br = beta_dft[i] * Yr[i];                                                  // (35)

      if (Bt > 2) GYt[i] = 17.6 * Math.pow(Bt - 1.1, 0.5) - 5 * log10(Bt - 1.1) - 8;
      else GYt[i] = 20 * log10(Bt + 0.1 * Bt * Bt * Bt);
      if (Br > 2) GYr[i] = 17.6 * Math.pow(Br - 1.1, 0.5) - 5 * log10(Br - 1.1) - 8;
      else GYr[i] = 20 * log10(Br + 0.1 * Br * Br * Br);

      const lim = 2 + 20 * log10(K[i]);
      if (GYr[i] < lim) GYr[i] = lim;
      if (GYt[i] < lim) GYt[i] = lim;

      Ldft[i] = -Fx[i] - GYt[i] - GYr[i];                                              // (36)
    }
    return Ldft;
  }

  function dl_se_ft(d, hte, hre, adft, f, omega) {
    const Ldft_land = dl_se_ft_inner(22, 0.003, d, hte, hre, adft, f);
    const Ldft_sea = dl_se_ft_inner(80, 5, d, hte, hre, adft, f);
    return [                                                                            // (28)
      omega * Ldft_sea[0] + (1 - omega) * Ldft_land[0],
      omega * Ldft_sea[1] + (1 - omega) * Ldft_land[1]
    ];
  }

  /* ── §4.3.2: pallomaisen maan diffraktiohäviö ─────────────────── */

  function dl_se(d, hte, hre, ap, f, omega) {
    const lam = 0.2998 / f;   // valonnopeus kuten ITU-R P.2001
    const dlos = Math.sqrt(2.0 * ap) * (Math.sqrt(0.001 * hte) + Math.sqrt(0.001 * hre)); // (22)

    if (d >= dlos) return dl_se_ft(d, hte, hre, ap, f, omega);

    const c = (hte - hre) / (hte + hre);                                                 // (24d)
    const m = 250 * d * d / (ap * (hte + hre));                                          // (24e)
    const b = 2 * Math.sqrt((m + 1.0) / (3.0 * m))
      * Math.cos(Math.PI / 3 + 1.0 / 3.0
        * Math.acos(3 * c / 2.0 * Math.sqrt(3.0 * m / Math.pow(m + 1.0, 3))));           // (24c)
    const dse1 = d / 2.0 * (1.0 + b);                                                    // (24a)
    const dse2 = d - dse1;                                                               // (24b)
    let hse = (hte - 500 * dse1 * dse1 / ap) * dse2 + (hre - 500 * dse2 * dse2 / ap) * dse1;
    hse = hse / d;                                                                       // (23)

    const hreq = 17.456 * Math.sqrt(dse1 * dse2 * lam / d);                              // (25)
    if (hse > hreq) return [0, 0];

    const aem = 500 * Math.pow(d / (Math.sqrt(hte) + Math.sqrt(hre)), 2);                // (26)
    const Ldft = dl_se_ft(d, hte, hre, aem, f, omega);
    if (Ldft[0] < 0.0) Ldft[0] = 0.0;
    if (Ldft[1] < 0.0) Ldft[1] = 0.0;
    return [(1 - hse / hreq) * Ldft[0], (1 - hse / hreq) * Ldft[1]];                     // (27)
  }

  /* ── §4.3.1: Bullingtonin diffraktio todellisella profiililla ─── */

  function dl_bull(d, g, hts, hrs, ap, f) {
    const Ce = 1.0 / ap;
    const lam = 0.2998 / f;
    const n = d.length;
    const dtot = d[n - 1] - d[0];

    // Suurin kaltevuus lähettimestä välipisteeseen
    let Stim = -Infinity;
    for (let i = 1; i < n - 1; i++) {
      const di = d[i];
      const s = (g[i] + 500 * Ce * di * (dtot - di) - hts) / di;                         // (13)
      if (s > Stim) Stim = s;
    }
    const Str = (hrs - hts) / dtot;                                                      // (14)

    let Luc = 0;
    if (Stim < Str) {
      // Tapaus 1: näköyhteysreitti
      let numax = -Infinity;
      for (let i = 1; i < n - 1; i++) {
        const di = d[i];
        const v = (g[i] + 500 * Ce * di * (dtot - di) - (hts * (dtot - di) + hrs * di) / dtot)
          * Math.sqrt(0.002 * dtot / (lam * di * (dtot - di)));                          // (15)
        if (v > numax) numax = v;
      }
      if (numax > -0.78) {
        Luc = 6.9 + 20 * log10(Math.sqrt(Math.pow(numax - 0.1, 2) + 1) + numax - 0.1);   // (12),(16)
      }
    } else {
      // Tapaus 2: horisontin takainen reitti
      let Srim = -Infinity;
      for (let i = 1; i < n - 1; i++) {
        const di = d[i];
        const s = (g[i] + 500 * Ce * di * (dtot - di) - hrs) / (dtot - di);              // (17)
        if (s > Srim) Srim = s;
      }
      const dbp = (hrs - hts + Srim * dtot) / (Stim + Srim);                             // (18)
      const nub = (hts + Stim * dbp - (hts * (dtot - dbp) + hrs * dbp) / dtot)
        * Math.sqrt(0.002 * dtot / (lam * dbp * (dtot - dbp)));                          // (20)
      if (nub > -0.78) {
        Luc = 6.9 + 20 * log10(Math.sqrt(Math.pow(nub - 0.1, 2) + 1) + nub - 0.1);       // (12),(20)
      }
    }
    return Luc + (1 - Math.exp(-Luc / 6.0)) * (10 + 0.02 * dtot);                        // (21)
  }

  /* ── Attachment 4 to Annex 1: Lbulls ilman profiilianalyysiä ──── */

  function dl_bull_att4(dtot, hte, hre, ap, f) {
    const Ce = 1.0 / ap;
    const lam = 0.2998 / f;
    const dlos = Math.sqrt(2.0 * ap) * (Math.sqrt(0.001 * hte) + Math.sqrt(0.001 * hre)); // (22)

    let Lus = 0;
    if (dtot < dlos) {
      const c = (hte - hre) / (hte + hre);                                               // (24d)
      const m = 250 * dtot * dtot / (ap * (hte + hre));                                  // (24e)
      const b = 2 * Math.sqrt((m + 1.0) / (3.0 * m))
        * Math.cos(Math.PI / 3.0 + 1.0 / 3.0
          * Math.acos(3.0 * c / 2.0 * Math.sqrt(3.0 * m / Math.pow(m + 1.0, 3))));       // (24c)
      const dse1 = dtot / 2.0 * (1.0 + b);                                               // (24a)
      const dse2 = dtot - dse1;                                                          // (24b)
      let hse = (hte - 500 * dse1 * dse1 / ap) * dse2 + (hre - 500 * dse2 * dse2 / ap) * dse1;
      hse = hse / dtot;                                                                  // (23)
      const numax = -hse * Math.sqrt(0.002 * dtot / (lam * dse1 * (dtot - dse1)));       // (105)
      if (numax > -0.78) {
        Lus = 6.9 + 20 * log10(Math.sqrt(Math.pow(numax - 0.1, 2) + 1) + numax - 0.1);   // (12),(106)
      }
    } else {
      const Stm = 500 * Ce * dtot - 2 * Math.sqrt(500.0 * Ce * hte);                     // (107)
      const Srm = 500 * Ce * dtot - 2 * Math.sqrt(500.0 * Ce * hre);                     // (108)
      const ds = (hre - hte + Srm * dtot) / (Stm + Srm);                                 // (109)
      let nus = hte + Stm * ds - (hte * (dtot - ds) + hre * ds) / dtot;
      nus = nus * Math.sqrt(0.002 * dtot / (lam * ds * (dtot - ds)));                    // (110)
      if (nus > -0.78) {
        Lus = 6.9 + 20 * log10(Math.sqrt(Math.pow(nus - 0.1, 2) + 1) + nus - 0.1);       // (12),(111)
      }
    }
    return Lus + (1 - Math.exp(-Lus / 6.0)) * (10 + 0.02 * dtot);                        // (112)
  }

  /* ── §4.3.4: delta-Bullington ─────────────────────────────────── */

  function dl_delta_bull(d, g, hts, hrs, hstd, hsrd, ap, f, omega, flag4) {
    const Lbulla = dl_bull(d, g, hts, hrs, ap, f);

    const hts1 = hts - hstd;                                                             // (37a)
    const hrs1 = hrs - hsrd;                                                             // (37b)
    const h1 = new Array(g.length).fill(0);
    const dtot = d[d.length - 1] - d[0];

    let Lbulls;
    if (flag4 === 1) Lbulls = dl_bull_att4(dtot, hts1, hrs1, ap, f);
    else Lbulls = dl_bull(d, h1, hts1, hrs1, ap, f);

    const hte = hts1;                                                                    // (38a)
    const hre = hrs1;                                                                    // (38b)
    const Ldsph = dl_se(dtot, hte, hre, ap, f, omega);

    const Ld = [
      Lbulla + Math.max(Ldsph[0] - Lbulls, 0),                                           // (39)
      Lbulla + Math.max(Ldsph[1] - Lbulls, 0)                                            // (39)
    ];
    return { Ld: Ld, Lbulla: Lbulla, Lbulls: Lbulls, Ldsph: Ldsph };
  }

  /* ── §4.3.5: diffraktiohäviö ajan p% osuudelle ────────────────── */

  function dl_p(d, g, hts, hrs, hstd, hsrd, f, omega, p, b0, DN, flag4) {
    const er = earth_rad_eff(DN);
    const ae = er[0], ab = er[1];

    let r50 = dl_delta_bull(d, g, hts, hrs, hstd, hsrd, ae, f, omega, flag4);
    const Ld50 = r50.Ld;

    if (p === 50) {
      const rb = dl_delta_bull(d, g, hts, hrs, hstd, hsrd, ab, f, omega, flag4);
      return { Ldp: Ld50, Ldb: rb.Ld, Ld50: Ld50,
               Lbulla50: rb.Lbulla, Lbulls50: rb.Lbulls, Ldsph50: rb.Ldsph };
    }

    // p < 50
    const rb = dl_delta_bull(d, g, hts, hrs, hstd, hsrd, ab, f, omega, flag4);
    const Ldb = rb.Ld;
    let Fi = 1;
    if (p > b0) Fi = inv_cum_norm(p / 100) / inv_cum_norm(b0 / 100);                     // (40a)
    const Ldp = [
      Ld50[0] + Fi * (Ldb[0] - Ld50[0]),                                                 // (41)
      Ld50[1] + Fi * (Ldb[1] - Ld50[1])
    ];
    return { Ldp: Ldp, Ldb: Ldb, Ld50: Ld50,
             Lbulla50: rb.Lbulla, Lbulls50: rb.Lbulls, Ldsph50: rb.Ldsph };
  }

  /* ── Attachment H: isoympyräreitti ────────────────────────────── */

  const sind = x => Math.sin(x * Math.PI / 180);
  const cosd = x => Math.cos(x * Math.PI / 180);
  const asind = x => Math.asin(x) * 180 / Math.PI;
  const atan2d = (y, x) => Math.atan2(y, x) * 180 / Math.PI;

  function great_circle_path(Phire, Phite, Phirn, Phitn, Re, dpnt) {
    const Dlon = Phire - Phite;                                                        // (H.2.1)
    const r = sind(Phitn) * sind(Phirn) + cosd(Phitn) * cosd(Phirn) * cosd(Dlon);      // (H.2.2)
    const Phid = Math.acos(r);                                                         // (H.2.3)
    const dgc = Phid * Re;                                                             // (H.2.4)
    const x1 = sind(Phirn) - r * sind(Phitn);                                          // (H.2.5a)
    const y1 = cosd(Phitn) * cosd(Phirn) * sind(Dlon);                                 // (H.2.5b)
    let Bt2r;
    if (Math.abs(x1) < 1e-9 && Math.abs(y1) < 1e-9) Bt2r = Phire;
    else Bt2r = atan2d(y1, x1);                                                        // (H.2.6)

    const Phipnt = dpnt / Re;                                                          // (H.3.1)
    const s = sind(Phitn) * Math.cos(Phipnt) + cosd(Phitn) * Math.sin(Phipnt) * cosd(Bt2r); // (H.3.2)
    const Phipntn = asind(s);                                                          // (H.3.3)
    const x2 = Math.cos(Phipnt) - s * sind(Phitn);                                     // (H.3.4a)
    const y2 = cosd(Phitn) * Math.sin(Phipnt) * sind(Bt2r);                            // (H.3.4b)
    let Phipnte;
    if (x2 < 1e-9 && y2 < 1e-9) Phipnte = Bt2r;
    else Phipnte = Phite + atan2d(y2, x2);                                             // (H.3.5)
    return [Phipnte, Phipntn, Bt2r, dgc];
  }

  /* ── §2: ilmakehän taipumisilmiön esiintyvyys beta0 ───────────── */

  function beta0(phi, dtm, dlm) {
    const tau = 1 - Math.exp(-(4.12e-4 * Math.pow(dlm, 2.41)));                        // (3)
    let mu1 = Math.pow(Math.pow(10, -dtm / (16 - 6.6 * tau))
      + Math.pow(10, -5 * (0.496 + 0.354 * tau)), 0.2);                                // (2)
    if (mu1 > 1) mu1 = 1;
    if (Math.abs(phi) <= 70) {
      const mu4 = Math.pow(mu1, -0.935 + 0.0176 * Math.abs(phi));                      // (4)
      return Math.pow(10, -0.015 * Math.abs(phi) + 1.67) * mu1 * mu4;                  // (5)
    }
    const mu4 = Math.pow(mu1, 0.3);                                                    // (4)
    return 4.17 * mu1 * mu4;                                                           // (5)
  }

  /* ── §4.8/§4.10: paikkavaihtelun keskihajonta ─────────────────── */

  function stdDev(f, h, R, wa) {
    let sigmaLoc = (0.52 + 0.024 * f) * Math.pow(wa, 0.28);
    let uh;
    if (h < R) uh = 1;
    else if (h >= R + 10) uh = 0;
    else uh = 1 - (h - R) / 10.0;
    return sigmaLoc * uh;
  }

  /* ── Radioilmastovyöhykkeiden osuudet reitistä ────────────────── */

  function path_fraction(d, zone, zone_r) {
    let dm = 0;
    const mask = zone.map(z => (z === zone_r ? 1 : 0));
    const iv = find_intervals(mask);
    const start = iv[0], stop = iv[1];
    for (let i = 0; i < start.length; i++) {
      let delta = 0;
      if (d[stop[i]] < d[d.length - 1]) delta += (d[stop[i] + 1] - d[stop[i]]) / 2.0;
      if (d[start[i]] > 0) delta += (d[start[i]] - d[start[i] - 1]) / 2.0;
      dm += d[stop[i]] - d[start[i]] + delta;
    }
    return dm / (d[d.length - 1] - d[0]);
  }

  function longest_cont_dist(d, zone, zone_r) {
    let dm = 0;
    // 34 = sisämaa + rannikkomaa yhdessä
    const mask = zone_r === 34
      ? zone.map(z => (z === 3 || z === 4 ? 1 : 0))
      : zone.map(z => (z === zone_r ? 1 : 0));
    const iv = find_intervals(mask);
    const start = iv[0], stop = iv[1];
    for (let i = 0; i < start.length; i++) {
      let delta = 0;
      if (d[stop[i]] < d[d.length - 1]) delta += (d[stop[i] + 1] - d[stop[i]]) / 2.0;
      if (d[start[i]] > 0) delta += (d[start[i]] - d[start[i] - 1]) / 2.0;
      dm = Math.max(d[stop[i]] - d[start[i]] + delta, dm);
    }
    return dm;
  }

  /* ── §4.1: näköyhteysreitin perusvaimennus ────────────────────── */

  function pl_los(d, hts, hrs, f, p, b0, dlt, dlr) {
    const dfs2 = d * d + Math.pow((hts - hrs) / 1000.0, 2);                            // (8a)
    const Lbfs = 92.4 + 20.0 * log10(f) + 10.0 * log10(dfs2);                          // (8)
    const Esp = 2.6 * (1 - Math.exp(-0.1 * (dlt + dlr))) * log10(p / 50);              // (9a)
    const Esb = 2.6 * (1 - Math.exp(-0.1 * (dlt + dlr))) * log10(b0 / 50);             // (9b)
    return [Lbfs, Lbfs + Esp, Lbfs + Esb];                                             // (10),(11)
  }

  /* ── Attachment 1 §5.6: tasoitettu maanpinta ja horisontit ────── */

  // Numpyn where(x == max) -vastine: indeksit jotka ovat tarkalleen maksimi.
  function argmaxAll(a) {
    let m = -Infinity;
    for (let i = 0; i < a.length; i++) if (a[i] > m) m = a[i];
    const idx = [];
    for (let i = 0; i < a.length; i++) if (a[i] === m) idx.push(i);
    return { max: m, idx: idx };
  }

  function smooth_earth_heights(d, h, R, htg, hrg, ae, f) {
    const n = d.length;
    const dtot = d[n - 1];

    const hts = h[0] + htg;
    const hrs = h[n - 1] + hrg;
    // Referenssi laskee tässä myös g = h + R (päätepisteet ilman latvustoa),
    // mutta ei palauta sitä — bt_loss muodostaa g:n itse. Jätetty pois.
    const htc = hts, hrc = hrs;

    // §5.6.1 tasoitetun maanpinnan johtaminen
    let v1 = 0, v2 = 0;
    for (let i = 1; i < n; i++) {
      v1 += (d[i] - d[i - 1]) * (h[i] + h[i - 1]);                                     // (85)
      v2 += (d[i] - d[i - 1])
        * (h[i] * (2 * d[i] + d[i - 1]) + h[i - 1] * (d[i] + 2 * d[i - 1]));           // (86)
    }
    let hst = (2 * v1 * dtot - v2) / (dtot * dtot);                                    // (87)
    let hsr = (v2 - v1 * dtot) / (dtot * dtot);                                        // (88)
    const hst_n = hst, hsr_n = hsr;

    // §5.6.2 tasoitetut korkeudet diffraktiomallia varten
    const HH = new Array(n);
    for (let i = 0; i < n; i++) HH[i] = h[i] - (htc * (dtot - d[i]) + hrc * d[i]) / dtot; // (89d)
    let hobs = -Infinity, alpha_obt = -Infinity, alpha_obr = -Infinity;
    for (let i = 1; i < n - 1; i++) {
      if (HH[i] > hobs) hobs = HH[i];                                                  // (89a)
      const at = HH[i] / d[i];
      if (at > alpha_obt) alpha_obt = at;                                              // (89b)
      const ar = HH[i] / (dtot - d[i]);
      if (ar > alpha_obr) alpha_obr = ar;                                              // (89c)
    }
    const gt = alpha_obt / (alpha_obt + alpha_obr);                                    // (90e)
    const gr = alpha_obr / (alpha_obt + alpha_obr);                                    // (90f)

    let hstp, hsrp;
    if (hobs <= 0) { hstp = hst; hsrp = hsr; }                                         // (90a),(90b)
    else { hstp = hst - hobs * gt; hsrp = hsr - hobs * gr; }                           // (90c),(90d)

    const hstd = (hstp >= h[0]) ? h[0] : hstp;                                         // (91a),(91b)
    const hsrd = (hsrp > h[n - 1]) ? h[n - 1] : hsrp;                                  // (91c),(91d)

    // Horisonttikulmat ja -etäisyydet. theta kattaa profiili-indeksit 1..n-2,
    // joten theta-indeksi k vastaa profiili-indeksiä k+1.
    const theta = new Array(n - 2);
    for (let i = 1; i < n - 1; i++) {
      theta[i - 1] = 1000 * Math.atan((h[i] - hts) / (1000 * d[i]) - d[i] / (2 * ae)); // (77)
    }
    const theta_td = 1000 * Math.atan((hrs - hts) / (1000 * dtot) - dtot / (2 * ae));  // (78)
    const theta_rd = 1000 * Math.atan((hts - hrs) / (1000 * dtot) - dtot / (2 * ae));  // (81)

    const amTheta = argmaxAll(theta);
    const theta_max = amTheta.max;                                                     // (76)
    const pathtype = (theta_max > theta_td) ? 2 : 1;                                   // (150)
    const theta_t = Math.max(theta_max, theta_td);                                     // (79)

    let lt, lr, dlt, dlr, theta_r;
    if (pathtype === 2) {
      lt = amTheta.idx[0] + 1;
      dlt = d[lt];                                                                     // (80)
      const theta2 = new Array(n - 2);
      for (let i = 1; i < n - 1; i++) {
        theta2[i - 1] = 1000 * Math.atan(
          (h[i] - hrs) / (1000 * (dtot - d[i])) - (dtot - d[i]) / (2 * ae));           // (82a)
      }
      const am2 = argmaxAll(theta2);
      theta_r = am2.max;
      lr = am2.idx[am2.idx.length - 1] + 1;
      dlr = dtot - d[lr];                                                              // (83)
    } else {
      theta_r = theta_rd;                                                              // (81)
      const lam = 0.2998 / f;   // valonnopeus kuten ITU-R P.2001
      const Ce = 1.0 / ae;
      const nu = new Array(n - 2);
      for (let i = 1; i < n - 1; i++) {
        nu[i - 1] = (h[i] + 500 * Ce * d[i] * (dtot - d[i])
          - (hts * (dtot - d[i]) + hrs * d[i]) / dtot)
          * Math.sqrt(0.002 * dtot / (lam * d[i] * (dtot - d[i])));                    // (81)
      }
      const amNu = argmaxAll(nu);
      lt = amNu.idx[amNu.idx.length - 1] + 1;
      dlt = d[lt];                                                                     // (80)
      dlr = dtot - dlt;                                                                // (83a)
      lr = lt;
    }

    const theta_tot = 1e3 * dtot / ae + theta_t + theta_r;                             // (84)

    // §5.6.3 kanavoitumis-/kerrosheijastusmalli
    hst = Math.min(hst, h[0]);                                                         // (92a)
    hsr = Math.min(hsr, h[n - 1]);                                                     // (92b)
    const m = (hsr - hst) / dtot;                                                      // (93)
    const hte = htg + h[0] - hst;                                                      // (94a)
    const hre = hrg + h[n - 1] - hsr;                                                  // (94b)
    let hm = -Infinity;
    for (let i = lt; i <= lr; i++) {
      const v = h[i] - (hst + m * d[i]);                                               // (95)
      if (v > hm) hm = v;
    }

    return {
      hst_n: hst_n, hsr_n: hsr_n, hst: hst, hsr: hsr, hstd: hstd, hsrd: hsrd,
      hte: hte, hre: hre, hm: hm, dlt: dlt, dlr: dlr,
      theta_t: theta_t, theta_r: theta_r, theta_tot: theta_tot, pathtype: pathtype
    };
  }

  /* ── §4.4: troposfäärisironta ─────────────────────────────────── */

  function tl_tropo(dtot, theta, f, p, N0) {
    const Lf = 25 * log10(f) - 2.5 * Math.pow(log10(f / 2.0), 2);                      // (45)
    return 190.1 + Lf + 20 * log10(dtot) + 0.573 * theta - 0.15 * N0
      - 10.125 * Math.pow(log10(50.0 / p), 0.7);
  }

  /* ── §4.5: kanavoituminen / kerrosheijastus ──────────────────── */

  function tl_anomalous(dtot, dlt, dlr, dct, dcr, dlm, hts, hrs, hte, hre, hm,
                        theta_t, theta_r, f, p, omega, ae, b0) {
    let Alf = 0;
    if (f < 0.5) Alf = 45.375 - 137.0 * f + 92.5 * f * f;                              // (47a)

    const theta_t2 = theta_t - 0.1 * dlt;                                              // (48a)
    const theta_r2 = theta_r - 0.1 * dlr;
    let Ast = 0, Asr = 0;
    if (theta_t2 > 0) {
      Ast = 20 * log10(1 + 0.361 * theta_t2 * Math.sqrt(f * dlt))
          + 0.264 * theta_t2 * Math.pow(f, 1.0 / 3.0);                                 // (48)
    }
    if (theta_r2 > 0) {
      Asr = 20 * log10(1 + 0.361 * theta_r2 * Math.sqrt(f * dlr))
          + 0.264 * theta_r2 * Math.pow(f, 1.0 / 3.0);
    }

    let Act = 0, Acr = 0;
    if (dct <= 5 && dct <= dlt && omega >= 0.75) {
      Act = -3 * Math.exp(-0.25 * dct * dct) * (1 + Math.tanh(0.07 * (50 - hts)));      // (49)
    }
    if (dcr <= 5 && dcr <= dlr && omega >= 0.75) {
      Acr = -3 * Math.exp(-0.25 * dcr * dcr) * (1 + Math.tanh(0.07 * (50 - hrs)));      // (49a)
    }

    const gamma_d = 5e-5 * ae * Math.pow(f, 1.0 / 3.0);                                // (51)

    let theta_t1 = theta_t, theta_r1 = theta_r;
    if (theta_t > 0.1 * dlt) theta_t1 = 0.1 * dlt;                                     // (52a)
    if (theta_r > 0.1 * dlr) theta_r1 = 0.1 * dlr;
    const theta1 = 1e3 * dtot / ae + theta_t1 + theta_r1;                              // (52)

    const dI = Math.min(dtot - dlt - dlr, 40);                                         // (56a)
    let mu3 = 1;
    if (hm > 10) mu3 = Math.exp(-4.6e-5 * (hm - 10) * (43 + 6 * dI));                  // (56)

    const tau = 1 - Math.exp(-(4.12e-4 * Math.pow(dlm, 2.41)));                        // (3)
    const epsilon = 3.5;
    let alpha = -0.6 - epsilon * 1e-9 * Math.pow(dtot, 3.1) * tau;                     // (55a)
    if (alpha < -3.4) alpha = -3.4;

    let mu2 = Math.pow(500 / ae * dtot * dtot
      / Math.pow(Math.sqrt(hte) + Math.sqrt(hre), 2), alpha);                          // (55)
    if (mu2 > 1) mu2 = 1;

    const beta = b0 * mu2 * mu3;                                                       // (54)
    const lb = log10(beta);
    const Gamma = 1.076 / Math.pow(2.0058 - lb, 1.012)
      * Math.exp(-(9.51 - 4.8 * lb + 0.198 * lb * lb) * 1e-6 * Math.pow(dtot, 1.13));  // (53a)
    const Ap = -12 + (1.2 + 3.7e-3 * dtot) * log10(p / beta)
      + 12 * Math.pow(p / beta, Gamma);                                                // (53)
    const Adp = gamma_d * theta1 + Ap;                                                 // (50)

    const Af = 102.45 + 20 * log10(f) + 20 * log10(dlt + dlr)
      + Alf + Ast + Asr + Act + Acr;                                                   // (47)
    return Af + Adp;                                                                   // (46)
  }

  /* ═══ Pääfunktio: perusvaimennus Lb ja kentänvoimakkuus Ep ═════

     f      taajuus (GHz, 0,03–6)
     p      aikaosuus % (1–50)
     d      profiilipisteiden etäisyydet (km, nouseva, d[0] = 0)
     h      profiilipisteiden korkeudet (m merenpinnasta)
     R      edustava latvuskorkeus pisteittäin (m)
     zone   radioilmastovyöhyke: 1 = meri, 3 = rannikkomaa, 4 = sisämaa
     htg    Tx-antennin korkeus maasta (m)
     hrg    Rx-antennin korkeus maasta (m)
     pol    polarisaatio: 1 = horisontaali, 2 = vertikaali
     phi_t/phi_r  leveysasteet, lam_t/lam_r  pituusasteet (astetta)

     opt: pL, sigmaL, Ptx, Gtx, Grx, DN, N0, dct, dcr, flag4

     HUOM DN ja N0: referenssitoteutus hakee ne ITU:n digitaalikartoista
     DN50/N050, joita EI SAA levittää eteenpäin ilman ITU:n lupaa. Tässä
     portissa ne on annettava eksplisiittisesti reitin keskipisteen
     arvoina — karttoja ei paketoida mukaan. */

  function bt_loss(f, p, d, h, R, zone, htg, hrg, pol, phi_t, phi_r, lam_t, lam_r, opt) {
    opt = opt || {};
    const pL = opt.pL !== undefined ? opt.pL : 50.0;
    const sigmaL = opt.sigmaL !== undefined ? opt.sigmaL : 0.0;
    const Ptx = opt.Ptx !== undefined ? opt.Ptx : 1.0;
    const dct0 = opt.dct !== undefined ? opt.dct : 500.0;
    const dcr0 = opt.dcr !== undefined ? opt.dcr : 500.0;
    const flag4 = opt.flag4 !== undefined ? opt.flag4 : 0;
    const Gtx = opt.Gtx !== undefined ? opt.Gtx : 0.0;
    const Grx = opt.Grx !== undefined ? opt.Grx : 0.0;
    const DN = opt.DN, N0 = opt.N0;

    const NN = d.length;
    for (let i = 1; i < NN; i++) {
      if (d[i] < d[i - 1]) throw new Error('Profiilipisteiden d on oltava nousevassa järjestyksessä.');
    }
    if (d[0] > 0.0) throw new Error('Ensimmäisen profiilipisteen d[0] on oltava nolla.');
    if (!(p >= 1 && p <= 50)) throw new Error('Aikaosuuden p on oltava välillä [1, 50] %.');
    if (!(htg >= 1 && htg <= 3000)) throw new Error('Tx-antennin korkeus [1, 3000] m.');
    if (!(hrg >= 1 && hrg <= 3000)) throw new Error('Rx-antennin korkeus [1, 3000] m.');
    if (!(pol === 1 || pol === 2)) throw new Error('Polarisaatio pol: 1 (H) tai 2 (V).');
    if (NN <= 4) throw new Error('Profiilissa on oltava yli 4 pistettä.');
    if (h.length !== NN) throw new Error('d ja h eri pituisia.');
    if (!(pL > 0 && pL < 100)) throw new Error('Paikkaosuuden pL on oltava välillä (0, 100) %.');
    if (!(Ptx > 0)) throw new Error('Lähetystehon on oltava positiivinen.');
    if (dct0 < 0 || dcr0 < 0) throw new Error('Etäisyyksien dct ja dcr on oltava positiivisia.');
    if (sigmaL < 0) throw new Error('Paikkavaihtelun keskihajonnan on oltava positiivinen.');
    if (!(flag4 === 0 || flag4 === 1)) throw new Error('flag4 voi olla 0 tai 1.');
    if (DN === undefined || N0 === undefined) {
      throw new Error('DN ja N0 on annettava — ITU:n digitaalikarttoja ei paketoida mukaan.');
    }

    if (!R || R.length === 0) R = new Array(NN).fill(0);
    else if (R.length !== NN) throw new Error('d ja R eri pituisia.');
    if (!zone || zone.length === 0) zone = new Array(NN).fill(4);
    else if (zone.length !== NN) throw new Error('d ja zone eri pituisia.');
    for (let i = 0; i < NN; i++) {
      if (!(zone[i] === 1 || zone[i] === 3 || zone[i] === 4)) {
        throw new Error('zone saa sisältää vain arvoja 1, 3 tai 4.');
      }
    }

    let dct = dct0, dcr = dcr0;
    if (zone[0] === 1) dct = 0;                    // Tx merellä
    if (zone[NN - 1] === 1) dcr = 0;               // Rx merellä

    const Re = 6371;
    const dpnt = 0.5 * (d[NN - 1] - d[0]);
    const gcp = great_circle_path(lam_r, lam_t, phi_r, phi_t, Re, dpnt);
    const phi_path = gcp[1];

    const dtm = longest_cont_dist(d, zone, 34);
    const dlm = longest_cont_dist(d, zone, 4);
    const b0 = beta0(phi_path, dtm, dlm);
    const er = earth_rad_eff(DN);
    const ae = er[0];
    const omega = path_fraction(d, zone, 1);

    const S = smooth_earth_heights(d, h, R, htg, hrg, ae, f);
    const theta = S.theta_tot;

    const dtot = d[NN - 1] - d[0];
    const hts = h[0] + htg;
    const hrs = h[NN - 1] + hrg;

    // Latvuskorkeus lisätään profiiliin diffraktiota varten, mutta ei
    // päätepisteisiin (antennit ovat latvuston sisällä, ei sen päällä).
    const g = new Array(NN);
    for (let i = 0; i < NN; i++) g[i] = h[i] + R[i];
    g[0] = h[0];
    g[NN - 1] = h[NN - 1];

    const htc = hts, hrc = hrs;

    const THETA = 0.3, KSI = 0.8;
    const Fj = 1.0 - 0.5 * (1.0 + Math.tanh(3.0 * KSI * (theta - THETA) / THETA));      // (57)
    const dsw = 20, kappa = 0.5;
    const Fk = 1.0 - 0.5 * (1.0 + Math.tanh(3.0 * kappa * (dtot - dsw) / dsw));         // (58)

    const los = pl_los(dtot, hts, hrs, f, p, b0, S.dlt, S.dlr);
    const Lbfs = los[0], Lb0p = los[1], Lb0b = los[2];

    const D = dl_p(d, g, htc, hrc, S.hstd, S.hsrd, f, omega, p, b0, DN, flag4);
    const Ldp = D.Ldp, Ld50 = D.Ld50;

    const Lbd50 = [Lbfs + Ld50[0], Lbfs + Ld50[1]];
    const Lbd = [Lb0p + Ldp[0], Lb0p + Ldp[1]];

    let Lminb0p = [Lb0p + (1 - omega) * Ldp[0], Lb0p + (1 - omega) * Ldp[1]];
    if (p >= b0) {
      const Fi = inv_cum_norm(p / 100.0) / inv_cum_norm(b0 / 100.0);
      Lminb0p = [                                                                       // (59)
        Lbd50[0] + (Lb0b + (1 - omega) * Ldp[0] - Lbd50[0]) * Fi,
        Lbd50[1] + (Lb0b + (1 - omega) * Ldp[1] - Lbd50[1]) * Fi
      ];
    }

    const eta = 2.5;
    const Lba = tl_anomalous(dtot, S.dlt, S.dlr, dct, dcr, dlm, hts, hrs,
      S.hte, S.hre, S.hm, S.theta_t, S.theta_r, f, p, omega, ae, b0);
    const Lminbap = eta * Math.log(Math.exp(Lba / eta) + Math.exp(Lb0p / eta));         // (60)

    const Lbda = [Lbd[0], Lbd[1]];
    if (Lminbap <= Lbd[0]) Lbda[0] = Lminbap + (Lbd[0] - Lminbap) * Fk;                 // (61)
    if (Lminbap <= Lbd[1]) Lbda[1] = Lminbap + (Lbd[1] - Lminbap) * Fk;

    const Lbam = [                                                                      // (62)
      Lbda[0] + (Lminb0p[0] - Lbda[0]) * Fj,
      Lbda[1] + (Lminb0p[1] - Lbda[1]) * Fj
    ];

    const Lbs = tl_tropo(dtot, theta, f, p, N0);
    const Lbc_pol = [                                                                   // (63)
      -5 * log10(Math.pow(10, -0.2 * Lbs) + Math.pow(10, -0.2 * Lbam[0])),
      -5 * log10(Math.pow(10, -0.2 * Lbs) + Math.pow(10, -0.2 * Lbam[1]))
    ];
    const Lbc = Lbc_pol[pol - 1];

    let Lloc = 0.0;                                                                     // (67a)
    if (zone[NN - 1] !== 1) Lloc = -inv_cum_norm(pL / 100.0) * sigmaL;

    const Lb = Math.max(Lb0p, Lbc + Lloc);                                              // (69)
    const Ep = 199.36 + 20 * log10(f) - Lb;                                             // (70)
    const EpPtx = Ep + 10 * log10(Ptx) + Gtx + Grx;

    // Ld, pathtype, theta_tot: puhtaasti diagnostisia lisäkenttiä UI:n
    // profiilinäkymälle (esim. "paljonko diffraktio vaikutti tässä pisteessä").
    // Eivät vaikuta Lb/Ep-laskentaan eivätkä validoituun tulokseen.
    return { Lb: Lb, Ep: EpPtx, Ld: Ldp[pol - 1], Lbs: Lbs,
             pathtype: S.pathtype, theta_tot: theta };
  }

  return {
    log10: log10,
    sind: sind, cosd: cosd, asind: asind, atan2d: atan2d,
    bt_loss: bt_loss,
    tl_tropo: tl_tropo,
    tl_anomalous: tl_anomalous,
    great_circle_path: great_circle_path,
    beta0: beta0,
    stdDev: stdDev,
    path_fraction: path_fraction,
    longest_cont_dist: longest_cont_dist,
    pl_los: pl_los,
    smooth_earth_heights: smooth_earth_heights,
    inv_cum_norm: inv_cum_norm,
    earth_rad_eff: earth_rad_eff,
    find_intervals: find_intervals,
    dl_se_ft_inner: dl_se_ft_inner,
    dl_se_ft: dl_se_ft,
    dl_se: dl_se,
    dl_bull: dl_bull,
    dl_bull_att4: dl_bull_att4,
    dl_delta_bull: dl_delta_bull,
    dl_p: dl_p
  };
});
