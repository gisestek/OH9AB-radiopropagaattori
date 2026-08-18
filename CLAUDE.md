# Meshtastic-kuuluvuusmallinnus — projektin saateprompti

> Liitä tämä Claude Coden ensimmäiseksi viestiksi, tai tallenna repon juureen
> nimellä `CLAUDE.md`, jolloin se latautuu kontekstiksi joka istunnossa.

---

## Konteksti

Rakennan avoimen lähdekoodin työkalun Meshtastic-verkkojen (LoRa, 868 MHz), 2m ja 70cm VHF/UHF -verkkojen
kuuluvuuden ennustamiseen Suomessa. **Tässä vaiheessa rajaus on tiukasti
OSI-kerros 1**: yhden lähettimen radioaaltojen eteneminen maastossa. Ei
protokollaa, ei reititystä, ei törmäyksiä — ne tulevat myöhemmin.

Olemassa olevat työkalut (Meshtastic Site Planner) käyttävät SRTM:ää 30–90 m
tarkkuudella eivätkä huomioi puustoa lainkaan. Suomessa on saatavilla
2 metrin korkeusmalli ja valtakunnallinen puustoaineisto. Se on tämän
projektin koko olemassaolon syy: metsä on usein suurempi
vaimennuksen lähde kuin maasto, eikä sitä mallinneta missään. 

## Lähtötilanne

Repossa on selainprototyyppi `kuuluvuus.html` (yksi tiedosto, Leaflet + vanilla
JS). Se on **käyttöliittymän ja algoritmin runko, ei tuotantokoodi**. Se osaa jo:

- 720 sädettä (0,5°), maastoprofiilin poiminta jokaiselle
- Maan kaarevuus tangenttitasomuunnoksella: `y = h − d²/(2kR)`, k säädettävä
- Deygout-pääsärmän diffraktio, ITU-R P.526 -approksimaatio `J(v)`
- Vapaan tilan vaimennus + saturoituva metsätermi (liukusäätimillä, ei datalla)
- Varjostusvara `σ·z` → kartta näyttää paikkavarmuuden, ei mediaania
- Napa-rasteri → Mercator-rasteri bilineaarisesti, monta asemaa max-yhdistelyllä
- Maastoprofiilinäkymä: Fresnel-vyöhyke, latvustovyö, määräävä särmä

Korkeusdata tulee Terrarium-ruutuina AWS:stä. Puusto on kolme liukusäädintä.
Molemmat pitää korvata oikealla suomalaisella datalla.

## Tavoitetila, vaihe 1

Kolme erillistä komponenttia:

1. **`pipeline/`** — datankäsittely. MML:n korkeusmalli ja Luken MVMI
   sisään, Terrarium-koodatut PNG-ruudut ulos, jotta selain voi lukea ne.
2. **`core/`** — etenemismalli kirjastona, testattavissa ilman selainta.
   Sama koodi ajettavissa Node/Pythonissa ja selaimessa.
3. **`web/`** — nykyinen prototyyppi puretttuna moduuleiksi, käyttäen `core/`:a.

## Tehtävät järjestyksessä

### 1. Datankäsittelyputki
- Lataa MML:n korkeusmalli 2 m (Paituli, `paituli.csc.fi`, tai MML:n
  tiedostopalvelu). Lisenssi CC BY 4.0.
- Yhdistä lehdet `gdalbuildvrt`-virtuaalirasteriksi — älä mosaikoi
  fyysisesti, aineisto on satoja gigatavuja.
- Uudelleenprojisoi EPSG:3067 → EPSG:3857 ja tuota XYZ-ruudut zoom-tasoille
  9–14. Käytä Terrarium-koodausta: `h = (R·256 + G + B/256) − 32768`.
  `rio-rgbify` osaa tämän, mutta tarkista tarkkuus — 1/256 m riittää hyvin.
- Sama putki Luken MVMI:lle: puuston keskipituus ja latvuspeittävyys,
  16 m ruudukko. Nämä voi pakata samaan PNG:hen eri kanaviin
  (esim. R = korkeus metreinä, G = peittävyys prosentteina).
- CLI: `python pipeline/build_tiles.py --input <vrt> --out tiles/ --zoom 9-14`
- **Korkeusjärjestelmä on N2000, ei ellipsoidikorkeus.** Dokumentoi tämä
  ja varmista ettei GDAL tee hiljaista muunnosta.

### 2. Etenemismalli omaksi moduulikseen
- Irrota `computeRadial()` prototyypistä puhtaaksi funktioksi ilman
  DOM-riippuvuuksia.
- Vaihda diffraktioydin **ITU-R P.1812-7**:ään. ITU julkaisee
  referenssitoteutuksen (MATLAB ja C++) ilmaiseksi — käytä sitä, älä
  kirjoita itse. Malli on satoja rivejä ehtolauseita ja virheet ovat hiljaisia.
  Pidä nykyinen Deygout vaihtoehtona nopeaan esikatseluun.
- Kirjoita yksikkötestit ITU:n omilla validointiaineistoilla
  (P.1812 tulee mukana testivektoreineen). **Tämä on ehdoton.**
- Metsävaimennus omaksi funktiokseen, syötteenä MVMI-profiili:
  ITU-R P.833 -tyylinen saturoituva malli, kerroin kalibroitavissa.

### 3. Suorituskyky
- Nykyinen ratkaisu on O(n²) sädettä kohti. Profiloi ensin, optimoi vasta
  sitten — 30 km ja 260 näytettä on todennäköisesti jo riittävän nopea.
- Jos ei ole: siirrä ydin WebAssemblyyn (Rust) tai vektoroi.
- Ruutujen haku pitää olla välimuistitettu ja peruutettavissa.

### 4. Validointi
- Työkalu joka lukee Meshtastic-lokit (MQTT-uplink tai `--json`-vienti)
  ja poimii RSSI/SNR + molempien päiden koordinaatit.
- Sirontakuvio mitattu vs. mallinnettu, RMSE ja systemaattinen poikkeama.
- Metsäkertoimen kalibrointiskripti, joka minimoi jäännöksen mittausjoukossa.
- **Älä säädä mallia, säädä kalibrointikerrointa.**

## Tekniset reunaehdot

- Koordinaatistot: laskenta WGS84/Mercatorissa, lähtödata EPSG:3067.
  Tee muunnokset yhdessä paikassa ja testaa ne.
- Selainpuoli ilman raskasta kehystä. Nykyinen vanilla JS + Leaflet toimii.
- Ei API-avaimia vaativia palveluita oletuksena. Kaiken pitää toimia
  pelkällä avoimella datalla.
- Lisenssi MIT tai Apache-2.0, mutta huomioi datan lisenssiehdot
  (MML ja Luke: CC BY 4.0 → attribuutio näkyviin käyttöliittymään).

## Miten haluan sinun työskentelevän

- Kysy ennen kuin teet isoja arkkitehtuurivalintoja puolestani.
- Yksi tehtävä kerrallaan, testit mukana. Älä generoi koko repoa yhdellä
  kertaa.
- Kun kirjoitat fysiikkaa, merkitse kommenttiin mistä suosituksesta ja
  mistä kaavasta on kyse. Tämä koodi pitää pystyä tarkistamaan
  alkuperäistä dokumenttia vasten.
- Jos malli antaa epäuskottavan tuloksen, sano se. Kaunis kartta joka on
  10 dB pielessä on huonompi kuin ruma kartta joka on oikein.
- Jätä arkkitehtuuriin optio rakennuksien ja kaupunkiympäristön, vesistöjen ja jääpeitteen huomioimiseen

## Ei vielä

Nämä ovat myöhempiä vaiheita, älä aloita niistä ilman pyyntöä:

- Kerros 2: CSMA, törmäykset, capture-efekti, hop limit, roolit
- Verkkosimulaatio (integraatio Meshtasticatoriin)


---

**Ensimmäinen konkreettinen pyyntö:** perusta repon rakenne ja tee
datankäsittelyputken luuranko — CLI-argumentit, GDAL-kutsut ja Terrarium-
koodaus — pienellä testialueella, jotta voin ajaa sen yhdelle karttalehdelle
ennen kuin lataan mitään isoa.
