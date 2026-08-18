"use strict";
/* ═══════════════════════════════════════════════════════════════
   radio-core.js — jaettu etenemisydin ja datakerros

   Käyttäjät: kuuluvuus.html (Meshtastic/LoRa) ja puheradio.html
   (2 m / 70 cm FM). Tässä tiedostossa EI ole DOM-riippuvuuksia
   canvas-elementin luontia (Terrain.load) lukuun ottamatta —
   kaikki UI on sivuissa.

   Malli:  L = vapaa tila (Friis)
             + terävän särmän diffraktio, Deygout-pääsärmä (ITU-R P.526)
             + metsävaimennus (P.833-tyylinen, saturoituva,
               MVMI-data tai vakioarvot, vuodenaikakerroin)
             + varjostusvara sigma × z(paikkavarmuus)
   Maan kaarevuus hoidetaan tangenttitaso­muunnoksella y = h − d²/(2kR).

   Tämä EI ole ITU-R P.1812. Se on seuraava askel: sama profiilin­-
   poiminta, eri ydinfunktio. Katso computeRadial().
   ═══════════════════════════════════════════════════════════════ */

const DEG = Math.PI/180, RE = 6371000;

/* ── Signaalirampi ───────────────────────────────────────────── */
const RAMP = [
  {t:0.00, c:[44,62,143]},
  {t:0.28, c:[31,122,140]},
  {t:0.52, c:[63,170,90]},
  {t:0.76, c:[229,192,75]},
  {t:1.00, c:[232,98,44]}
];
function rampColor(t){
  t = t<0?0:t>1?1:t;
  for(let i=0;i<RAMP.length-1;i++){
    const a=RAMP[i], b=RAMP[i+1];
    if(t<=b.t){
      const f=(t-a.t)/(b.t-a.t);
      return [a.c[0]+(b.c[0]-a.c[0])*f, a.c[1]+(b.c[1]-a.c[1])*f, a.c[2]+(b.c[2]-a.c[2])*f];
    }
  }
  return RAMP[RAMP.length-1].c;
}

/* Koko ohjelmiston yhteinen RSSI-väriasteikko (dBm), kuuluvuus.html:n
   peittokartalle ja havainnot.html:n mittausdatalle. VAKIO riippumatta
   modeemin herkkyysrajasta ($sens) — se ohjaa erikseen minkä pikselin
   ALI ei ole peittoa lainkaan (läpinäkyvyys), mikä on eri asia kuin
   värin merkitys. Näin sama väri tarkoittaa aina samaa dBm-tasoa,
   ajettiinpa mikä tahansa modeemipreset tai verrattiinpa mallia
   mittaukseen. havainnot.html ei lataa tätä tiedostoa (pidetään kevyenä)
   vaan pitää oman kirjaimellisen kopionsa näistä kahdesta luvusta — jos
   niitä muutetaan täällä, muuta samat havainnot.html:ään.
   puheradio.html käyttää TARKOITUKSELLA eri asteikkoa (linkkimarginaali
   dB, ei absoluuttinen RSSI) — se on jo oma vakionsa (MARG_TOP=30,
   cutoff=0), ei tätä. */
const RSSI_LO = -131, RSSI_HI = -60;

/* ── Mercator ─────────────────────────────────────────────────── */
const merc = lat => Math.log(Math.tan(Math.PI/4 + lat*DEG/2));
const invMerc = y => (2*Math.atan(Math.exp(y)) - Math.PI/2)/DEG;

/* ═══ Ruutuvälimuisti ══════════════════════════════════════════
   Yksi ruutu dekoodataan kerran omaksi 256×256-taulukokseen ja
   säilötään globaaliin välimuistiin. Asemat ja peräkkäiset ajot
   jakavat samat ruudut, joten toinen asema samalla alueella ei
   lataa mitään uudestaan. */
const TILE_CACHE = new Map();     // avain -> {h,cov} | null (puuttuu)
const TILE_CACHE_MAX = 700;       // ~180 MB katto (700 × 256 kB)
let _scv=null, _sctx=null;

function _scratch(){
  if(!_scv){
    _scv=document.createElement('canvas');
    _scv.width=_scv.height=256;
    _sctx=_scv.getContext('2d',{willReadFrequently:true});
  }
  return _sctx;
}

function _decodeTile(kind, px, enc){
  const n=65536;
  if(kind==='forest'){
    // R = latvuston keskipituus (m), G = latvuspeittävyys (%).
    const h=new Float32Array(n), cov=new Float32Array(n);
    for(let i=0;i<n;i++){
      const j=i*4;
      h[i]=Math.min(60,px[j]);
      cov[i]=Math.min(1,px[j+1]/100);
    }
    return {h,cov};
  }
  const h=new Float32Array(n);
  for(let i=0;i<n;i++){
    const j=i*4;
    const v=Terrain.decode(enc,px[j],px[j+1],px[j+2]);
    h[i]=(v<-500||v>9000)?0:v;
  }
  return {h,cov:null};
}

function _loadTile(kind, z, x, y, tpl, enc){
  const key=kind+'|'+z+'/'+x+'/'+y;
  if(TILE_CACHE.has(key)) return Promise.resolve(TILE_CACHE.get(key));
  return new Promise(res=>{
    const img=new Image();
    img.crossOrigin='anonymous';
    let settled=false;
    const finish=v=>{
      if(settled) return;
      settled=true; clearTimeout(timer);
      if(TILE_CACHE.size>=TILE_CACHE_MAX) TILE_CACHE.delete(TILE_CACHE.keys().next().value);
      TILE_CACHE.set(key,v);
      res(v);
    };
    const timer=setTimeout(()=>{ img.src=''; finish(null); },12000);
    img.onload=()=>{
      try{
        const ctx=_scratch();
        ctx.clearRect(0,0,256,256);
        ctx.drawImage(img,0,0,256,256);
        finish(_decodeTile(kind, ctx.getImageData(0,0,256,256).data, enc));
      }catch(e){ finish(null); }   // esim. CORS-saastunut canvas
    };
    img.onerror=()=>finish(null);
    img.src=tpl.replace('{z}',z).replace('{x}',x).replace('{y}',y);
  });
}

/* ═══ Maastolähde ══════════════════════════════════════════════ */

// Tasojen välinen sekoitusvyöhyke (osuus tason ulkosäteestä), jotta
// tarkkuusporras ei näy renkaana kartalla.
const LOD_BLEND = 0.25;

class Terrain{
  // kind: 'dem' (oletus) tai 'forest'. Forest-ruudut ovat
  // pipeline/terrarium.encode_forest-muotoa, ja MVMI:n 16 m
  // lähderesoluution takia niitä on vain zoomiin 12 asti.
  //
  // Maasto poimitaan suoraan ruuduista etäisyysporrastetulla
  // tarkkuudella (clipmap): aseman lähellä natiivi zoom, kauempana
  // niin karkea kuin mallin oma erotuskyky sallii. Tarkkuus EI siis
  // riipu laskentasäteestä — vain siitä, mitä malli pystyy
  // hyödyntämään kullakin etäisyydellä.
  constructor(kind){
    this.kind=kind||'dem';
    this.ok=false; this.mode=''; this.miss=0; this.tiles=0;
    this.levels=[]; this.forest=null;
  }

  static decode(mode,r,g,b){
    return mode==='mapbox' ? -10000 + (r*65536 + g*256 + b)*0.1
                           : (r*256 + g + b/256) - 32768;
  }

  async load(cx, cy, rangeM, cfg, onProg){
    const dLat = rangeM/111320;
    const dLon = rangeM/(111320*Math.cos(cx*DEG));
    const N=cx+dLat, S=cx-dLat, W=cy-dLon, E=cy+dLon;

    if(cfg.tsrc==='synth'){ return this.synth(N,S,W,E,cx); }

    this.lat0=cx; this.lon0=cy;
    this.mLat=111320; this.mLon=111320*Math.cos(cx*DEG);

    const zNat = this.kind==='forest' ? 12 : 14;
    const gres0 = 156543.03392*Math.cos(cx*DEG);       // m/px zoomilla 0
    const gres  = z => gres0/Math.pow(2,z);

    // Mallin erotuskyky etäisyydellä d:
    //   säteiden välimatka  d·2π/nAz   (napa-rasterin kulmaerotuskyky)
    //   profiilin askel     range/nR   (etäisyyserotuskyky)
    // Kumpaakin hienompi maasto ei näy tuloksessa, joten tavoite on
    // puolet pienemmästä (Nyquist).
    const stepAlong = cfg.range/cfg.nR;
    // Karkein tarvittava taso: hienoin, joka vielä riittää kaukokentässä.
    let zFar=zNat;
    while(zFar>6 && gres(zFar-1) <= stepAlong/2) zFar--;
    // Tason z ulkosäde: siihen asti kulmaerotuskyky vaatii tätä tarkkuutta.
    const rOuter = z => gres(z)*cfg.nAz/Math.PI;

    const specs=[];
    for(let z=zNat; z>=zFar; z--){
      const prev = specs.length ? specs[specs.length-1] : null;
      const R = (z===zFar) ? rangeM : Math.min(rangeM, rOuter(z));
      const rIn = prev ? prev.R*(1-LOD_BLEND) : 0;
      if(prev && rIn>=rangeM) break;          // edellinen taso kattoi jo kaiken
      specs.push({z, R, rIn});
      if(R>=rangeM) break;                    // kaikki katettu
    }

    const tpl = this.kind==='forest'
      ? cfg.furl
      : cfg.tsrc==='custom'
        ? cfg.turl
        : 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
    const enc = cfg.tsrc==='custom' ? cfg.tenc : 'terrarium';

    // Ruutuluettelo tasoittain. Uloin taso karkenee tarvittaessa, jos
    // kokonaismäärä uhkaa karata — lähikentän tarkkuudesta ei tingitä.
    const MAX_TILES=260;
    let jobs=[];
    for(;;){
      jobs=[];
      for(const sp of specs){
        for(const t of this._tilesFor(sp.z, sp.rIn, sp.R)) jobs.push([sp,t[0],t[1]]);
      }
      const outer=specs[specs.length-1];
      if(jobs.length<=MAX_TILES || specs.length<2 || outer.z<=6) break;
      outer.z--;                              // karkeampi uloin rengas
    }

    const total=jobs.length;
    this.tiles=total; this.miss=0;
    this.levels=specs.map(sp=>({
      z:sp.z, R:sp.R, s:256*Math.pow(2,sp.z),
      map:new Map(), _tx:-1,_ty:-1,_t:undefined
    }));
    const lvlOf=new Map(specs.map((sp,i)=>[sp,this.levels[i]]));

    let done=0;
    const q=jobs.slice();
    const worker=async()=>{
      while(q.length){
        const [sp,tx,ty]=q.shift();
        const t=await _loadTile(this.kind, sp.z, tx, ty, tpl, enc);
        if(t) lvlOf.get(sp).map.set(tx+'/'+ty, t);
        else this.miss++;
        done++; onProg && onProg(done/total);
      }
    };
    await Promise.all(Array.from({length:Math.min(8,q.length)},worker));

    // Forest-tilassa ei synteettistä varamaastoa: jos dataa ei saada,
    // palataan liukusäätimiin (ok=false) eikä keksitä metsää.
    if(total===0 || this.miss>=total){
      if(this.kind==='forest'){ this.ok=false; return this; }
      return this.synth(N,S,W,E,cx);
    }

    this.zFine=this.levels[0].z;
    this.zCoarse=this.levels[this.levels.length-1].z;
    this.z=this.zFine;                        // yhteensopivuus vanhaan
    this.resFine=gres(this.zFine);
    this.ok=true; this.mode='tiles';
    return this;
  }

  // Renkaan [rIn, rOut] peittävät ruudut zoomilla z.
  _tilesFor(z, rIn, rOut){
    const s=Math.pow(2,z);
    const dLat=rOut/this.mLat, dLon=rOut/this.mLon;
    const N=this.lat0+dLat, S=this.lat0-dLat, W=this.lon0-dLon, E=this.lon0+dLon;
    const x0=Math.floor((W+180)/360*s), x1=Math.floor((E+180)/360*s);
    const y0=Math.floor((0.5-merc(N)/(2*Math.PI))*s);
    const y1=Math.floor((0.5-merc(S)/(2*Math.PI))*s);
    const out=[];
    for(let ty=y0;ty<=y1;ty++){
      const latT=invMerc((0.5-ty/s)*2*Math.PI), latB=invMerc((0.5-(ty+1)/s)*2*Math.PI);
      const cLat=(latT+latB)/2, hH=(latT-latB)*this.mLat/2;
      for(let tx=x0;tx<=x1;tx++){
        const lonL=tx/s*360-180, lonR=(tx+1)/s*360-180;
        const cLon=(lonL+lonR)/2, hW=(lonR-lonL)*this.mLon/2;
        const dx=(cLon-this.lon0)*this.mLon, dy=(cLat-this.lat0)*this.mLat;
        const dc=Math.hypot(dx,dy), diag=Math.hypot(hW,hH);
        if(dc-diag > rOut) continue;          // kokonaan renkaan ulkopuolella
        if(dc+diag < rIn)  continue;          // kokonaan reiän sisällä
        out.push([tx,ty]);
      }
    }
    return out;
  }

  synth(N,S,W,E,cx){
    // Deterministinen arvokohina — vain käyttöliittymän demoamiseen.
    const w=1024,h=1024;
    this.w=w; this.hgt=h; this.mode='synth'; this.ok=true;
    this.bbox={N,S,W,E};
    const H=new Float32Array(w*h);
    const hash=(i,j)=>{ let n=(i*374761393 + j*668265263)|0;
      n=(n^(n>>13))*1274126177|0; return ((n^(n>>16))>>>0)/4294967295; };
    const vn=(x,y)=>{ const i=Math.floor(x),j=Math.floor(y),fx=x-i,fy=y-j;
      const u=fx*fx*(3-2*fx), v=fy*fy*(3-2*fy);
      return hash(i,j)*(1-u)*(1-v)+hash(i+1,j)*u*(1-v)+hash(i,j+1)*(1-u)*v+hash(i+1,j+1)*u*v; };
    for(let j=0;j<h;j++) for(let i=0;i<w;i++){
      let a=0,f=1/90,amp=1;
      for(let o=0;o<5;o++){ a+=vn(i*f+11.3,j*f+7.7)*amp; amp*=0.5; f*=2.05; }
      H[j*w+i]=Math.pow(a/1.94,1.7)*240;
    }
    this.h=H;
    return this;
  }

  sample(lat,lon){ return this._get(lat,lon,0); }
  // Latvuspeittävyys 0..1 (vain forest-tila).
  sampleCov(lat,lon){ return this._get(lat,lon,1); }

  _get(lat,lon,which){
    if(!this.ok) return 0;
    if(this.mode==='synth') return which ? 0 : this._synthSample(lat,lon);
    const L=this.levels, last=L.length-1;
    let i=0;
    if(last>0){
      const dy=(lat-this.lat0)*this.mLat, dx=(lon-this.lon0)*this.mLon;
      const d=Math.sqrt(dx*dx+dy*dy);
      while(i<last && d>L[i].R) i++;
      let v=this._lvl(L[i],lat,lon,which);
      const bs=L[i].R*(1-LOD_BLEND);
      if(i<last && d>bs && v===v){
        // sekoitus karkeampaan tasoon, jottei porras näy renkaana
        const t=Math.min(1,(d-bs)/(L[i].R-bs));
        const v2=this._lvl(L[i+1],lat,lon,which);
        if(v2===v2) v=v*(1-t)+v2*t;
      }
      while(v!==v && i<last){ i++; v=this._lvl(L[i],lat,lon,which); }
      return v===v ? v : 0;
    }
    const v=this._lvl(L[0],lat,lon,which);
    return v===v ? v : 0;
  }

  _lvl(lv,lat,lon,which){
    const px=(lon+180)/360*lv.s;
    const py=(0.5 - merc(lat)/(2*Math.PI))*lv.s;
    const ix=Math.floor(px), iy=Math.floor(py);
    const fx=px-ix, fy=py-iy;
    const a=this._px(lv,ix,iy,which),     b=this._px(lv,ix+1,iy,which);
    const c=this._px(lv,ix,iy+1,which),   d=this._px(lv,ix+1,iy+1,which);
    // Yksikin puuttuva naapuri -> NaN, jolloin _get siirtyy karkeampaan.
    return a*(1-fx)*(1-fy)+b*fx*(1-fy)+c*(1-fx)*fy+d*fx*fy;
  }

  _px(lv,ix,iy,which){
    const tx=ix>>8, ty=iy>>8;
    let t;
    if(tx===lv._tx && ty===lv._ty) t=lv._t;    // säteet kulkevat jatkuvasti,
    else{                                       // joten yhden ruudun muisti
      t=lv.map.get(tx+'/'+ty);                  // kattaa valtaosan hauista
      lv._tx=tx; lv._ty=ty; lv._t=t;
    }
    if(!t) return NaN;
    const o=((iy&255)<<8)|(ix&255);
    return which ? (t.cov?t.cov[o]:0) : t.h[o];
  }

  _synthSample(lat,lon){
    const b=this.bbox;
    let px=(lon-b.W)/(b.E-b.W)*(this.w-1);
    let py=(b.N-lat)/(b.N-b.S)*(this.hgt-1);
    if(px<0)px=0; if(py<0)py=0;
    if(px>this.w-1.001)px=this.w-1.001;
    if(py>this.hgt-1.001)py=this.hgt-1.001;
    const i=px|0, j=py|0, fx=px-i, fy=py-j, W=this.w;
    const a=this.h[j*W+i], b2=this.h[j*W+i+1], c=this.h[(j+1)*W+i], d=this.h[(j+1)*W+i+1];
    return a*(1-fx)*(1-fy)+b2*fx*(1-fy)+c*(1-fx)*fy+d*fx*fy;
  }
}

/* ═══ Eteneminen ══════════════════════════════════════════════ */

// Terävän särmän diffraktio, ITU-R P.526 approksimaatio
function knife(v){
  if(v<=-0.78) return 0;
  const u=v-0.1;
  return 6.9 + 20*Math.log10(Math.sqrt(u*u+1)+u);
}

/**
 * Laskee yhden säteen linkkibudjetin jokaiseen etäisyysaskeleeseen.
 * Palauttaa Float32Arrayn RSSI-arvoja (dBm). Jos cfg:n budjettikentät
 * (ptx, gtx, lcab, grx) ovat nollia, tulos on -(L + varjostusvara),
 * josta kutsuja voi johtaa molempien suuntien budjetit (puheradio).
 */
function computeRadial(az, site, cfg, terrain, out, prof){
  const n=cfg.nR, step=cfg.range/n;
  const cosA=Math.cos(az*DEG), sinA=Math.sin(az*DEG);
  const mPerLat=111320, mPerLon=111320*Math.cos(site.lat*DEG);
  const k2R = 2*cfg.k*RE;
  const lam = 299.792458/cfg.freq;   // m

  // Puustolähde: MVMI-datakerros jos ladattu, muuten liukusäätimet
  // vakioarvoina. Molemmat kulkevat samaa polkua näytetaulukoiden kautta.
  const F = terrain.forest || null;
  const y=cfg.bufY, D=cfg.bufD, CH=cfg.bufC, CV=cfg.bufF;
  for(let i=0;i<=n;i++){
    const d=i*step;
    const lat=site.lat + d*cosA/mPerLat;
    const lon=site.lon + d*sinA/mPerLon;
    D[i]=d;
    y[i]=terrain.sample(lat,lon) - d*d/k2R;   // tangenttitaso, k-korjattu
    if(F){ CH[i]=F.sample(lat,lon); CV[i]=F.sampleCov(lat,lon); }
    else { CH[i]=cfg.cheight;       CV[i]=cfg.ccover; }
  }

  const txA = y[0] + site.h;
  const eirp = cfg.ptx + cfg.gtx - cfg.lcab + cfg.grx;
  const gam = cfg.cgamma * cfg.sfac;   // vuodenaikakerroin mukana
  const fade = cfg.sigma * cfg.z;

  for(let m=1;m<=n;m++){
    const d=D[m];
    const rxA=y[m]+cfg.hrx;
    const slope=(rxA-txA)/d;

    let vmax=-1e9, vIdx=-1, vegLen=0;
    for(let i=1;i<m;i++){
      const line = txA + slope*D[i];
      const d1=D[i], d2=d-D[i];
      const hob = y[i]-line;
      const v = hob*Math.sqrt(2*d/(lam*d1*d2));
      if(v>vmax){ vmax=v; vIdx=i; }
      // Latvustomatka peittävyydellä painotettuna: näyte lasketaan mukaan
      // kun sädeviiva kulkee latvuston sisällä (maa < viiva < maa+latvusto).
      if(CH[i]>0 && y[i]+CH[i] > line) vegLen += step*CV[i];
    }
    const Ldiff = (vIdx<0)?0:knife(vmax);
    // ITU-R P.833 -henkinen saturoituva metsätermi: gamma (dB/m) x
    // peittävyyspainotettu latvustomatka, katto 28 dB (kulman yli
    // diffraktoituva komponentti rajoittaa kokonaisvaimennusta).
    const Lveg  = Math.min(28, gam*vegLen);
    const Lfs   = 32.44 + 20*Math.log10(cfg.freq) + 20*Math.log10(Math.max(d,1)/1000);
    out[m-1] = eirp - Lfs - Ldiff - Lveg - fade;

    if(prof && m===n){ prof.Ldiff=Ldiff; prof.Lveg=Lveg; prof.Lfs=Lfs; prof.vmax=vmax; prof.vIdx=vIdx; }
  }
}

/* ═══ ITU-R P.1812-8 -ydin ════════════════════════════════════
   Sama säteen linkkibudjetti kuin computeRadial, mutta diffraktio,
   sironta, kanavoituminen ja paikkavaihtelu tulevat P.1812-8:sta
   (core/p1812.js). Deygout jää nopeaksi esikatseluksi.

   Kaksi eroa profiilin poiminnassa, jotka on helppo tehdä väärin:
   1) P.1812 hoitaa maan kaarevuuden itse efektiivisellä maan säteellä,
      joten sille annetaan RAA'AT merenpinnasta lasketut korkeudet —
      ei computeRadialin tangenttitasokorjattua y[]:tä.
   2) Latvusto menee erillisenä R-profiilina, ei dB/m-terminä. P.1812
      lisää sen itse diffraktioprofiiliin (päätepisteitä lukuun ottamatta). */

const P1812_MIN_KM = 0.25;   // suosituksen alaraja reitin pituudelle

function computeRadialP1812(az, site, cfg, terrain, out, stats) {
  const n = cfg.nR, step = cfg.range / n;
  const cosA = Math.cos(az * DEG), sinA = Math.sin(az * DEG);
  const mPerLat = 111320, mPerLon = 111320 * Math.cos(site.lat * DEG);
  const fGHz = cfg.freq / 1000;
  const F = terrain.forest || null;

  const dkm = cfg.bufDk, hh = cfg.bufH, RR = cfg.bufR, zz = cfg.bufZ;
  const las = cfg.bufLa, los = cfg.bufLo;
  for (let i = 0; i <= n; i++) {
    const d = i * step;
    const lat = site.lat + d * cosA / mPerLat;
    const lon = site.lon + d * sinA / mPerLon;
    las[i] = lat; los[i] = lon;
    dkm[i] = d / 1000;
    hh[i] = terrain.sample(lat, lon);          // raaka amsl, EI kaarevuuskorjausta
    RR[i] = F ? F.sample(lat, lon) : cfg.cheight;
    // TODO: vesistöt ja meri. Ilman maanpeiteaineistoa kaikki on sisämaata (4).
    zz[i] = 4;
  }

  const eirp = cfg.ptx + cfg.gtx - cfg.lcab + cfg.grx;
  const htg = Math.max(1, site.h);             // P.1812 vaatii >= 1 m
  const hrg = Math.max(1, cfg.hrx);
  const opt = {
    pL: cfg.pL, Ptx: 1.0, Gtx: 0, Grx: 0,
    DN: cfg.DN, N0: cfg.N0, flag4: 0
  };

  for (let m = 1; m <= n; m++) {
    const dtot = dkm[m];
    // Alle 5 pisteen profiili tai alle 0,25 km reitti on suosituksen
    // ulkopuolella — käytetään vapaan tilan vaimennusta.
    if (m < 5 || dtot < P1812_MIN_KM) {
      const Lbfs = 92.4 + 20 * Math.log10(fGHz) + 20 * Math.log10(Math.max(dtot, 1e-4));
      out[m - 1] = eirp - Lbfs;
      continue;
    }
    try {
      opt.sigmaL = P1812.stdDev(fGHz, hrg, RR[m], cfg.wa);
      const r = P1812.bt_loss(
        fGHz, cfg.pTime,
        dkm.subarray(0, m + 1), hh.subarray(0, m + 1),
        RR.subarray(0, m + 1), zz.subarray(0, m + 1),
        htg, hrg, cfg.pol,
        site.lat, las[m], site.lon, los[m], opt);
      out[m - 1] = eirp - r.Lb;
    } catch (e) {
      // Yksittäinen kelvoton reitti ei saa kaataa koko ajoa.
      if (stats) { stats.errors++; stats.lastError = e.message; }
      const Lbfs = 92.4 + 20 * Math.log10(fGHz) + 20 * Math.log10(Math.max(dtot, 1e-4));
      out[m - 1] = eirp - Lbfs;
    }
  }
}

/* Kevyt 1-2-1-tasoitus napa-rasterille atsimuutissa (kiertyvä) ja
   etäisyydessä. 720 sädettä x ~115 m askel on karttapikseliä harvempi
   näytteistys, ja ilman tasoitusta näytekohina (mm. maaston aliasointi
   lähellä estorajaa) piirtyy sädeviuhkoina peittokarttaan. Suodatus on
   alle mallin erotuskyvyn, joten se ei hävitä oikeaa informaatiota. */
function smoothPolar(p, c){
  const A=c.nAz, R=c.nR, t=new Float32Array(p.length);
  for(let a=0;a<A;a++){
    const am=((a-1)+A)%A, ap=(a+1)%A;
    for(let r=0;r<R;r++)
      t[a*R+r]=0.25*p[am*R+r]+0.5*p[a*R+r]+0.25*p[ap*R+r];
  }
  for(let a=0;a<A;a++){
    const o=a*R;
    for(let r=0;r<R;r++){
      const rm=r>0?r-1:0, rp=r<R-1?r+1:R-1;
      p[o+r]=0.25*t[o+rm]+0.5*t[o+r]+0.25*t[o+rp];
    }
  }
}

/* ═══ Profiilinauha ═══════════════════════════════════════════
   Jaettu piirtofunktio: molemmilla sivuilla on sama #pcanvas ja
   sama profiilirakenne. P = {h,y,D,n,txA,rxA,slope,bd,lam,vIdx,c,
   best,CH,cvm}. */
let _lastProf=null;
function drawProfile(P){
  _lastProf=P;
  const cv=document.getElementById('pcanvas'), dpr=window.devicePixelRatio||1;
  const W=cv.clientWidth, H=cv.clientHeight;
  cv.width=W*dpr; cv.height=H*dpr;
  const g=cv.getContext('2d'); g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,W,H);

  const pad={l:8,r:8,t:12,b:18};
  const {h,y,D,n,txA,rxA,slope,bd,lam,vIdx,c,best,CH}=P;

  let lo=Infinity,hi=-Infinity,chMax=0;
  for(let i=0;i<=n;i++){
    const t=y[i]; if(t<lo)lo=t;
    if(t+CH[i]>hi)hi=t+CH[i];
    if(CH[i]>chMax)chMax=CH[i];
  }
  hi=Math.max(hi,txA,rxA)+8; lo-=6;
  const X=d=>pad.l+(d/bd)*(W-pad.l-pad.r);
  const Y=v=>H-pad.b-((v-lo)/(hi-lo))*(H-pad.t-pad.b);

  // vaakaviivat
  g.strokeStyle='rgba(30,65,85,.55)'; g.lineWidth=1;
  for(let f=0;f<=1;f+=0.25){ const yy=Math.round(Y(lo+f*(hi-lo)))+.5; g.beginPath(); g.moveTo(0,yy); g.lineTo(W,yy); g.stroke(); }

  // Latvusto näytteittäin: sävy seuraa latvuspeittävyyttä, joten harva
  // mäntykangas ja tiheä kuusikko erottuvat toisistaan. Tämä on juuri se
  // MVMI-informaatio, joka menisi hukkaan yhdellä tasaisella täytöllä.
  if(chMax>0){
    for(let i=0;i<n;i++){
      if(CH[i]<=0 && CH[i+1]<=0) continue;
      const cvm=(P.CV?(P.CV[i]+P.CV[i+1])/2:P.cvm);
      const x0=X(D[i]), x1=X(D[i+1])+0.7;   // pieni limitys peittää saumat
      g.beginPath();
      g.moveTo(x0,Y(y[i]));
      g.lineTo(x0,Y(y[i]+CH[i]));
      g.lineTo(x1,Y(y[i+1]+CH[i+1]));
      g.lineTo(x1,Y(y[i+1]));
      g.closePath();
      g.fillStyle='rgba(63,170,90,'+(0.14+0.5*cvm).toFixed(3)+')';
      g.fill();
    }
    g.beginPath();
    for(let i=0;i<=n;i++) g.lineTo(X(D[i]),Y(y[i]+CH[i]));
    g.strokeStyle='rgba(110,210,135,.8)'; g.lineWidth=1.3; g.stroke();
  }

  // Fresnel 1
  g.beginPath();
  for(let i=0;i<=n;i++){
    const d1=Math.max(D[i],1), d2=Math.max(bd-D[i],1);
    const F=Math.sqrt(lam*d1*d2/bd);
    g.lineTo(X(D[i]),Y(txA+slope*D[i]+F));
  }
  for(let i=n;i>=0;i--){
    const d1=Math.max(D[i],1), d2=Math.max(bd-D[i],1);
    const F=Math.sqrt(lam*d1*d2/bd);
    g.lineTo(X(D[i]),Y(txA+slope*D[i]-F));
  }
  g.closePath();
  g.fillStyle='rgba(224,33,138,.13)'; g.fill();
  g.strokeStyle='rgba(224,33,138,.45)'; g.lineWidth=1; g.stroke();

  // maasto
  g.beginPath(); g.moveTo(X(0),H-pad.b);
  for(let i=0;i<=n;i++) g.lineTo(X(D[i]),Y(y[i]));
  g.lineTo(X(bd),H-pad.b); g.closePath();
  g.fillStyle='#16323f'; g.fill();
  g.beginPath();
  for(let i=0;i<=n;i++) g.lineTo(X(D[i]),Y(y[i]));
  g.strokeStyle='#8ba4b1'; g.lineWidth=1.2; g.stroke();

  // suora säde
  g.beginPath(); g.moveTo(X(0),Y(txA)); g.lineTo(X(bd),Y(rxA));
  g.strokeStyle='#e0218a'; g.lineWidth=1.4; g.setLineDash([5,4]); g.stroke(); g.setLineDash([]);

  // maston varret
  g.strokeStyle='rgba(236,228,210,.7)'; g.lineWidth=1.5;
  g.beginPath(); g.moveTo(X(0),Y(y[0])); g.lineTo(X(0),Y(txA)); g.stroke();
  g.beginPath(); g.moveTo(X(bd),Y(y[n])); g.lineTo(X(bd),Y(rxA)); g.stroke();
  g.fillStyle='#e0218a';
  g.beginPath(); g.arc(X(0),Y(txA),3.4,0,7); g.fill();
  g.fillStyle='#ece4d2';
  g.beginPath(); g.arc(X(bd),Y(rxA),3,0,7); g.fill();

  // määräävä särmä
  if(vIdx>0){
    const xx=X(D[vIdx]);
    g.strokeStyle='rgba(229,192,75,.8)'; g.setLineDash([2,3]); g.lineWidth=1;
    g.beginPath(); g.moveTo(xx,pad.t-4); g.lineTo(xx,Y(y[vIdx])); g.stroke(); g.setLineDash([]);
    g.fillStyle='#e5c04b'; g.font='500 9px "IBM Plex Mono",monospace';
    const lbl=Math.round(h[vIdx])+' m';
    const tw=g.measureText(lbl).width;
    g.fillText(lbl, Math.min(W-pad.r-tw, Math.max(pad.l, xx-tw/2)), pad.t+2);
  }

  // korkeusasteikko (korkeassa ikkunassa on tilaa)
  g.fillStyle='#5d7683'; g.font='400 9px "IBM Plex Mono",monospace';
  for(let f=0.25;f<=1;f+=0.25){
    const v=lo+f*(hi-lo);
    g.fillText(Math.round(v)+' m', pad.l+2, Y(v)-3);
  }

  // asteikot
  g.fillText(best.name, pad.l, H-5);
  const rt=(bd/1000).toFixed(1)+' km';
  g.fillText(rt, W-pad.r-g.measureText(rt).width, H-5);
}
window.addEventListener('resize',()=>{
  const p=document.getElementById('profile');
  if(_lastProf && p && p.classList.contains('on')) drawProfile(_lastProf);
});

/* Napa-rasterin siirto Mercator-rasteriin käänteisellä bilineaarisella
   poiminnalla (atsimuutti, etäisyys). Max-yhdistely tukee monta asemaa. */
function splat(polar, site, c, ras, RW, RH, W, E, yT, yB, frac){
  const azLim=frac*360;
  const mLat=111320, mLon=111320*Math.cos(site.lat*DEG);
  const step=c.range/c.nR;
  for(let j=0;j<RH;j++){
    const lat=invMerc(yT + (j+0.5)/RH*(yB-yT));
    const dy=(lat-site.lat)*mLat;
    for(let i=0;i<RW;i++){
      const lon=W + (i+0.5)/RW*(E-W);
      const dx=(lon-site.lon)*mLon;
      const d=Math.sqrt(dx*dx+dy*dy);
      if(d<step*0.5 || d>c.range) continue;
      let az=Math.atan2(dx,dy)/DEG; if(az<0) az+=360;
      if(az>azLim) continue;
      // bilineaarinen (atsimuutti, etäisyys)
      const fa=az/360*c.nAz, fr=d/step-1;
      const a0=Math.floor(fa)%c.nAz, a1=(a0+1)%c.nAz, ta=fa-Math.floor(fa);
      const r0=Math.max(0,Math.min(c.nR-1,Math.floor(fr))), r1=Math.min(c.nR-1,r0+1), tr=fr-r0;
      const v =
        polar[a0*c.nR+r0]*(1-ta)*(1-tr) + polar[a1*c.nR+r0]*ta*(1-tr) +
        polar[a0*c.nR+r1]*(1-ta)*tr     + polar[a1*c.nR+r1]*ta*tr;
      const k=j*RW+i;
      if(v>ras[k]) ras[k]=v;
    }
  }
}
