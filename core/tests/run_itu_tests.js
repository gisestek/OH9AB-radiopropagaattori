/* Aja core/p1812.js ITU:n VIRALLISILLA validointiprofiileilla ja vertaa
   aineiston referenssiarvoon. Tämä on projektin ehdoton hyväksymistesti.

   Ajo:  node core/tests/run_itu_tests.js
   Vektorit: core/tests/itu_vectors.py (ks. sen ohje). */
'use strict';

const fs = require('fs');
const path = require('path');
const P = require('../p1812.js');

const vecPath = path.join(__dirname, 'itu_vectors.json');
if (!fs.existsSync(vecPath)) {
  console.error('itu_vectors.json puuttuu — aja ensin itu_vectors.py.');
  process.exit(2);
}
const V = JSON.parse(fs.readFileSync(vecPath, 'utf8'));

// Sama toleranssi kuin ITU:n omassa validateP1812.py:ssä.
const TOL = 1e-8;
let pass = 0, fail = 0;
const failures = [];

V.forEach(c => {
  let r;
  try {
    r = P.bt_loss(c.f, c.p, c.d, c.h, c.R, c.zone, c.htg, c.hrg, c.pol,
      c.phi_t, c.phi_r, c.lam_t, c.lam_r, c.opt);
  } catch (e) {
    fail++;
    if (failures.length < 10) failures.push(`${c.file}#${c.measID}: poikkeus ${e.message}`);
    return;
  }
  const dev = Math.abs(r.Ep - c.Ep_ref);
  if (dev <= TOL) pass++;
  else {
    fail++;
    if (failures.length < 10) {
      failures.push(`${c.file}#${c.measID}: Ep ${r.Ep.toFixed(9)} vs ref ${c.Ep_ref.toFixed(9)} (poikkeama ${dev.toExponential(3)})`);
    }
  }
});

console.log(`\nITU:n validointiprofiilit: ${pass} / ${pass + fail} testiä läpi ` +
            `(poikkeama < ${TOL} dB kentänvoimakkuudessa).`);
if (fail) {
  console.log('\nPoikkeamat:');
  failures.forEach(f => console.log('  ' + f));
  process.exit(1);
}
