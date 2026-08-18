# Meshtastic/VHF/UHF-kuuluvuusmallinnus Suomeen

Avoimen datan työkalu LoRa (868 MHz), 2 m ja 70 cm -verkkojen kuuluvuuden
ennustamiseen. Erottava tekijä: MML:n 2 m korkeusmalli ja Luken
puustoaineisto (MVMI) — metsävaimennus mallinnetaan, ei arvata.

Vaihe 1 kattaa vain OSI-kerroksen 1: yhden lähettimen radioaallon
eteneminen maastossa. Ks. [CLAUDE.md](CLAUDE.md) koko suunnitelma.

## Rakenne

- `pipeline/` — datankäsittely: MML-korkeusmalli ja Luke MVMI sisään,
  Terrarium-koodatut XYZ-PNG-ruudut ulos.
- `core/` — etenemismalli kirjastona (tulossa).
- `web/` — selainkäyttöliittymä (tulossa; nykyinen prototyyppi on
  [kuuluvuus.html](kuuluvuus.html)).

## Datankäsittelyputki

Vaatimukset: Python 3.9+, GDAL (Python-sidokset), numpy, Pillow.

```
pip install -r requirements.txt
```

Käyttö (esimerkki yhdellä MML:n karttalehdellä):

```
# 1) Karttalehdet virtuaalirasteriksi (ei kopioi dataa)
python pipeline/build_tiles.py vrt --input "data/dem/*.tif" --out data/dem.vrt

# 2) Korkeusruudut, Terrarium-koodaus
python pipeline/build_tiles.py tiles --input data/dem.vrt --out tiles/dem --zoom 9-14

# 3) Puustoruudut (MVMI: keskipituus dm -> m kertoimella 0.1)
python pipeline/build_tiles.py tiles --mode forest \
    --input data/mvmi_keskipituus.vrt --input-cover data/mvmi_latvus.vrt \
    --height-scale 0.1 --out tiles/forest --zoom 9-14
```

Testialueen voi rajata lisäämällä `--bounds minlon,minlat,maxlon,maxlat`.

Ruutuformaatit:

- **Korkeus**: Terrarium, `h = (R·256 + G + B/256) − 32768` m.
  Nodata/meri koodataan arvoksi 0 m.
- **Puusto**: R = keskipituus (m), G = latvuspeittävyys (%), B = varattu.

**Korkeusjärjestelmä on N2000** (MML:n korkeusmalli). Putki muuntaa vain
tasokoordinaatit (EPSG:3067 → EPSG:3857); korkeusarvoihin ei kosketa,
ja tämä on varmistettu testillä.

## Testit

```
pytest
```

GDAL:ia vaativat päästä päähän -testit ohitetaan automaattisesti, jos
GDAL puuttuu; koodauksen ja ruutumatematiikan testit ajautuvat aina.

## Data ja lisenssit

- Maanmittauslaitos, korkeusmalli 2 m (CC BY 4.0) — Paituli / MML:n
  tiedostopalvelu.
- Luonnonvarakeskus, monilähteinen valtakunnan metsien inventointi
  MVMI (CC BY 4.0): puuston keskipituus, latvuspeittävyys, 16 m ruudukko.

Attribuutio kuuluu näkyviin myös käyttöliittymään.
