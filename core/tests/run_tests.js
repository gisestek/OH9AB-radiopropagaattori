/* Vertaa core/p1812.js:ää ITU:n Py1812-referenssin tuottamiin vektoreihin.
   Ajo:  node core/tests/run_tests.js
   Vektorit tuotetaan gen_vectors.py:llä (vaatii Py1812:n). */
'use strict';

const fs = require('fs');
const path = require('path');
const P = require('../p1812.js');

const vecPath = path.join(__dirname, 'vectors.json');
if (!fs.existsSync(vecPath)) {
  console.error('vectors.json puuttuu — aja ensin gen_vectors.py (ks. core/tests/README).');
  process.exit(2);
}
const V = JSON.parse(fs.readFileSync(vecPath, 'utf8'));

// Suhteellinen toleranssi; P.1812:n arvot ovat desibelejä ja kilometrejä,
// joten 1e-9 on käytännössä liukulukupyöristys.
const TOL = 1e-9;
let pass = 0, fail = 0;
const failures = [];

function close(a, b) {
  if (!isFinite(a) || !isFinite(b)) return Object.is(a, b) || (isNaN(a) && isNaN(b));
  const scale = Math.max(1, Math.abs(a), Math.abs(b));
  return Math.abs(a - b) <= TOL * scale;
}

function check(name, i, label, got, want) {
  const g = Array.isArray(got) ? got : [got];
  const w = Array.isArray(want) ? want : [want];
  let ok = g.length === w.length;
  if (ok) for (let k = 0; k < g.length; k++) if (!close(g[k], w[k])) { ok = false; break; }
  if (ok) pass++;
  else {
    fail++;
    if (failures.length < 12) {
      failures.push(`${name}[${i}] ${label}: sai ${JSON.stringify(g)} odotettiin ${JSON.stringify(w)}`);
    }
  }
}

// ── skalaari- ja apufunktiot ──────────────────────────────────
V.inv_cum_norm.forEach((c, i) => check('inv_cum_norm', i, '', P.inv_cum_norm(c.x), c.out));
V.earth_rad_eff.forEach((c, i) => check('earth_rad_eff', i, '', P.earth_rad_eff(c.DN), c.out));
V.find_intervals.forEach((c, i) => {
  const r = P.find_intervals(c.series);
  check('find_intervals', i, 'k1', r[0], c.k1);
  check('find_intervals', i, 'k2', r[1], c.k2);
});

// ── pallomaisen maan diffraktio ───────────────────────────────
V.dl_se_ft_inner.forEach((c, i) =>
  check('dl_se_ft_inner', i, '',
    P.dl_se_ft_inner(c.epsr, c.sigma, c.d, c.hte, c.hre, c.adft, c.f), c.out));
V.dl_se_ft.forEach((c, i) =>
  check('dl_se_ft', i, '', P.dl_se_ft(c.d, c.hte, c.hre, c.adft, c.f, c.omega), c.out));
V.dl_se.forEach((c, i) =>
  check('dl_se', i, '', P.dl_se(c.d, c.hte, c.hre, c.ap, c.f, c.omega), c.out));

// ── Bullington ────────────────────────────────────────────────
V.dl_bull.forEach((c, i) =>
  check('dl_bull', i, '', P.dl_bull(c.d, c.g, c.hts, c.hrs, c.ap, c.f), c.out));
V.dl_bull_att4.forEach((c, i) =>
  check('dl_bull_att4', i, '', P.dl_bull_att4(c.dtot, c.hte, c.hre, c.ap, c.f), c.out));

// ── delta-Bullington ja ajan p% osuus ─────────────────────────
V.dl_delta_bull.forEach((c, i) => {
  const r = P.dl_delta_bull(c.d, c.g, c.hts, c.hrs, c.hstd, c.hsrd, c.ap, c.f, c.omega, c.flag4);
  check('dl_delta_bull', i, 'Ld', r.Ld, c.Ld);
  check('dl_delta_bull', i, 'Lbulla', r.Lbulla, c.Lbulla);
  check('dl_delta_bull', i, 'Lbulls', r.Lbulls, c.Lbulls);
  check('dl_delta_bull', i, 'Ldsph', r.Ldsph, c.Ldsph);
});
V.dl_p.forEach((c, i) => {
  const r = P.dl_p(c.d, c.g, c.hts, c.hrs, c.hstd, c.hsrd, c.f, c.omega, c.p, c.b0, c.DN, c.flag4);
  check('dl_p', i, 'Ldp', r.Ldp, c.Ldp);
  check('dl_p', i, 'Ldb', r.Ldb, c.Ldb);
  check('dl_p', i, 'Ld50', r.Ld50, c.Ld50);
});

// ── isoympyräreitti, beta0, hajonta, vyöhykeosuudet, LoS ──────
V.great_circle_path.forEach((c, i) =>
  check('great_circle_path', i, '',
    P.great_circle_path(c.Phire, c.Phite, c.Phirn, c.Phitn, c.Re, c.dpnt), c.out));
V.beta0.forEach((c, i) => check('beta0', i, '', P.beta0(c.phi, c.dtm, c.dlm), c.out));
V.stdDev.forEach((c, i) => check('stdDev', i, '', P.stdDev(c.f, c.h, c.R, c.wa), c.out));
V.path_fraction.forEach((c, i) =>
  check('path_fraction', i, '', P.path_fraction(c.d, c.zone, c.zone_r), c.out));
V.longest_cont_dist.forEach((c, i) =>
  check('longest_cont_dist', i, '', P.longest_cont_dist(c.d, c.zone, c.zone_r), c.out));
V.pl_los.forEach((c, i) =>
  check('pl_los', i, '', P.pl_los(c.d, c.hts, c.hrs, c.f, c.p, c.b0, c.dlt, c.dlr), c.out));

// ── tasoitettu maanpinta ja horisontit ────────────────────────
const SEH_KEYS = ['hst_n', 'hsr_n', 'hst', 'hsr', 'hstd', 'hsrd', 'hte', 'hre', 'hm',
  'dlt', 'dlr', 'theta_t', 'theta_r', 'theta_tot', 'pathtype'];
V.smooth_earth_heights.forEach((c, i) => {
  const r = P.smooth_earth_heights(c.d, c.h, c.R, c.htg, c.hrg, c.ae, c.f);
  SEH_KEYS.forEach(k => check('smooth_earth_heights', i, k, r[k], c[k]));
});

// ── sironta ja kanavoituminen ─────────────────────────────────
V.tl_tropo.forEach((c, i) =>
  check('tl_tropo', i, '', P.tl_tropo(c.dtot, c.theta, c.f, c.p, c.N0), c.out));
V.tl_anomalous.forEach((c, i) =>
  check('tl_anomalous', i, '', P.tl_anomalous(c.dtot, c.dlt, c.dlr, c.dct, c.dcr,
    c.dlm, c.hts, c.hrs, c.hte, c.hre, c.hm, c.theta_t, c.theta_r, c.f, c.p,
    c.omega, c.ae, c.b0), c.out));

// ── päästä päähän: bt_loss ────────────────────────────────────
V.bt_loss.forEach((c, i) => {
  const r = P.bt_loss(c.f, c.p, c.d, c.h, c.R, c.zone, c.htg, c.hrg, c.pol,
    c.phi_t, c.phi_r, c.lam_t, c.lam_r, c.opt);
  check('bt_loss', i, 'Lb', r.Lb, c.Lb);
  check('bt_loss', i, 'Ep', r.Ep, c.Ep);
});

console.log(`\n${pass} / ${pass + fail} vertailua täsmää (toleranssi ${TOL}).`);
if (fail) {
  console.log('\nEnsimmäiset poikkeamat:');
  failures.forEach(f => console.log('  ' + f));
  process.exit(1);
}
console.log('Kaikki läpi.');
