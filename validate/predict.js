/* Laske ennustettu vastaanottotaso havaituille linkeille P.1812-8:lla.

   Ajo:
     node validate/predict.js validate/profiilit.json \
          --dn 45 --n0 325 --out validate/ennusteet.json

   MIKSI pL=50 JA sigmaL=0:
   Mittaus on yksi realisaatio yhdestä paikasta. P.1812:n paikkavaihtelutermi
   siirtäisi ennustetta jakauman häntään, jolloin vertaisimme yksittäistä
   näytettä esim. 90 %:n varmuustasoon — ja saisimme systemaattisen
   poikkeaman joka kertoo vain valitusta varmuustasosta. Ennustetaan siis
   MEDIAANI, ja jäännösten hajonta on juuri se paikkavaihtelu, jonka
   haluamme mitata. Samasta syystä aikaosuus p = 50 %.

   Käyttää core/p1812.js:ää — samaa koodia jonka ITU:n omat 63
   validointiprofiilia hyväksyvät. */
'use strict';

const fs = require('fs');
const path = require('path');
const P = require('../core/p1812.js');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : def;
}

const inPath = process.argv[2];
const outPath = arg('out');
const DN = arg('dn') !== undefined ? parseFloat(arg('dn')) : undefined;
const N0 = arg('n0') !== undefined ? parseFloat(arg('n0')) : undefined;
/* Kalibrointikerroin: R_eff = rScale · R_MVMI. MVMI antaa puuston
   KESKIPITUUDEN, kun P.1812 haluaa "edustavan latvuskorkeuden" — nämä eivät
   ole sama asia, ja suhde riippuu mm. latvuspeittävyydestä. Tämä on se
   kerroin jota kalibroidaan mittauksilla; mallia itseään ei kosketa. */
const R_SCALE = arg('r-scale') !== undefined ? parseFloat(arg('r-scale')) : 1.0;

if (!inPath || !outPath) {
  console.error('Käyttö: node validate/predict.js <profiilit.json> --dn <ΔN> --n0 <N₀> --out <ulos.json>');
  process.exit(2);
}
if (!isFinite(DN) || !isFinite(N0)) {
  console.error('ΔN ja N₀ on annettava (ITU:n kartoista DN50 / N050 alueen kohdalta).');
  console.error('Niitä ei ole oletusarvoina, koska ITU:n karttoja ei jaeta tämän mukana.');
  process.exit(2);
}

const profs = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const out = [];
let failed = 0;
const failReasons = {};

for (const p of profs) {
  const fGHz = p.freq_mhz / 1000;
  // P.1812 vaatii antennikorkeudeksi vähintään 1 m.
  const htg = Math.max(1, p.htg), hrg = Math.max(1, p.hrg);
  const R = R_SCALE === 1.0 ? p.R : p.R.map(v => v * R_SCALE);
  let rec;
  try {
    rec = P.bt_loss(fGHz, 50, p.d, p.h, R, p.zone, htg, hrg, p.pol,
      p.tx_lat, p.rx_lat, p.tx_lon, p.rx_lon,
      { pL: 50, sigmaL: 0, Ptx: 1, Gtx: 0, Grx: 0, DN: DN, N0: N0, flag4: 0 });
  } catch (e) {
    failed++;
    failReasons[e.message] = (failReasons[e.message] || 0) + 1;
    continue;
  }
  // Vastaanottoteho = EIRP − perusvaimennus + vastaanottopään vahvistus
  const eirp = p.tx_power_dbm + p.tx_gain_dbi - p.tx_cable_db;
  const pred = eirp - rec.Lb + p.rx_gain_dbi - p.rx_cable_db;

  out.push({
    index: p.index, time: p.time, tx: p.tx, rx: p.rx,
    dist_m: p.dist_m, freq_mhz: p.freq_mhz,
    Lb: rec.Lb, Ld: rec.Ld, pathtype: rec.pathtype,
    rssi_pred: pred, rssi_meas: p.rssi, snr_meas: p.snr,
    residual: p.rssi - pred          // mitattu − ennustettu
  });
}

fs.writeFileSync(outPath, JSON.stringify(out));
console.error(`Ennusteita: ${out.length} / ${profs.length}  ->  ${outPath}`
  + (R_SCALE !== 1.0 ? `  (R-kerroin ${R_SCALE})` : ''));
if (failed) {
  console.error(`  epäonnistui: ${failed}`);
  for (const [msg, n] of Object.entries(failReasons)) console.error(`    ${n}× ${msg}`);
}
