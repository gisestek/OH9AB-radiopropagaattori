# validate — mallin validointi Meshtastic-mittauksilla

Vertaa P.1812-8-ennustetta oikeisiin RSSI-mittauksiin ja kalibroi
latvuskorkeuden tulkinta. Putki on neljä vaihetta, jokainen erillinen
komento, jotta välituloksia voi tarkastella.

## 0. Kerää lokit

**Tämä on jo automatisoitu, ei tarvitse tehdä käsin.**
`collect/collector.py` pyörii systemd-palveluna (`oh9ab-collector`) ja
kirjoittaa jatkuvasti `logs/YYYY-MM-DD.ndjson`, sekä JSON- että
protobuf-topiceista (`collect/mesh_decode.py` purkaa jälkimmäisen —
tarpeen mm. nRF52-pohjaisille laitteille kuten RAK4631, jotka eivät tue
JSON-ulostuloa lainkaan). `collect/update_havainnot.sh` ajaa vaiheen 1
(alla) valmiiksi cronista 15 min välein, joten `validate/havainnot.csv`
on jo ajan tasalla — voit hypätä suoraan vaiheeseen 2 tai 3.

Manuaalinen kertakeräys on silti hyödyllinen, jos haluat mitata jotain
MUUTA kuin mitä kerays-kerääjät kattavat (esim. eri broker, tai
tarkkarajainen aikaikkuna omalta ajolta):

```bash
mosquitto_sub -h <broker> -u kerays -P "$(cat /etc/mosquitto/kerays.secret)" \
    -t 'oh9ab/+/2/json/#' -v > loki.ndjson
```

(Huom: oma topic-juuremme on `oh9ab/...`, ei Meshtasticin oletus
`msh/...`.) `-v` tulostaa `topic {json}` -rivejä; jäsennin sietää sen.
Myös pelkkä JSON-taulukko käy. Tämä tapa saa mukaan vain JSON-topicit —
jos tarvitset myös protobufia (esim. juuri nRF52-solmuilta), käytä
`oh9ab/#`-kuviota ja `collect/mesh_decode.py`:tä, tai käytä suoraan
`collect/collector.py`:n valmiiksi tuottamaa lokia.

Mitä pidempi keräysjakso, sitä parempi. Liikkuva solmu (auto) tuottaa
paljon arvokkaampaa aineistoa kuin kiinteät, koska se näytteistää monta
maastotyyppiä ja etäisyyttä.

## 1. Jäsennä havainnot

**Myös tämä on automatisoitu** (`collect/update_havainnot.sh`, ks. yllä) —
`validate/havainnot.csv` on jo olemassa ja ajan tasalla. Aja käsin vain
jos yhdistät oman erilliskeräyksen (`loki.ndjson` yllä) tai haluat
suodattaa eri parametreilla:

```bash
python3 validate/parse_logs.py loki.ndjson --out validate/havainnot.csv
```

Komento tulostaa **erittelyn siitä mitä hylättiin ja miksi**. Lue se —
useimmiten valtaosa paketeista hylätään perustellusti.

Tärkein suodatin: **vain suorat vastaanotot kelpaavat** (0 hyppyä). Releen
kautta tulleen paketin RSSI kuvaa releen ja gatewayn välistä linkkiä, ei
sitä linkkiä jonka koordinaateista päättelisi. Jos hyppymäärää ei voi
todeta lokista, paketti hylätään — epävarmaa ei oteta mukaan.

Lopuksi tulostuu lista solmuista, joille pitää täyttää tiedot seuraavassa
vaiheessa.

## 2. Täytä solmutiedot

```bash
cp validate/nodes.example.json validate/nodes.json
```

**Aja tarkistus aina käsin muokkauksen jälkeen:**

```bash
python3 validate/check_nodes.py validate/nodes.json
```

Tiedosto ei ole minkään lomakkeen takana, joten tämä nappaa yleisimmät
käsinmuokkausvirheet ennen kuin ne pilaavat tuloksen huomaamatta: JSON-
syntaksivirheet (rivi- ja sarakenumerolla), kirjoitusvirheet kenttien
nimissä, duplikaattiavaimet, ja sen yleisimmän virheen — Meshtasticin
raaka `latitudeI`/`longitudeI` liitettynä suoraan `lat`/`lon`-kenttiin
ilman 1e-7-kerrointa. Onnistuessaan se listaa myös kaikki käytössä olevat
kiinteät sijainnit, joten näet yhdellä silmäyksellä mikä on voimassa.

Näitä tietoja ei ole lokeissa, ja ne vaikuttavat tulokseen suoraan:

| Kenttä | Merkitys |
|---|---|
| `antenna_height_m` | **Antennin korkeus MAANPINNASTA.** Tärkein yksittäinen parametri. Älä käytä merenpinnan korkeutta — maanpinta luetaan korkeusmallista. |
| `tx_power_dbm` | Lähetysteho. EU_868: 27 dBm alikaistalla 869,4–869,65 MHz, muuten 14 dBm. |
| `antenna_gain_dbi` | Antennivahvistus. Kumiankka ~0, kunnon vertikaali 2–6. |
| `cable_loss_db` | Kaapelihäviö. |
| `lat`, `lon` | **Valinnainen.** Kiinteän aseman tarkka sijainti, jos se on tiedossa vaikka verkossa se näkyisikin sumennettuna tai puuttuisi kokonaan. Ks. alla. |

Solmun GPS-korkeutta ei käytetä: se on usein puuttuva tai kymmeniä metrejä
pielessä, kun taas maanpinta tiedetään korkeusmallista senttimetreissä.

### Kiinteän aseman tarkka sijainti (`lat`/`lon`)

Jos tiedät kiinteän aseman todellisen sijainnin, kirjoita se `nodes.json`:iin:

```json
"!11111111": {
  "name": "OH9RAB",
  "antenna_height_m": 5.0,
  "lat": 66.6087,
  "lon": 25.8403
}
```

Tämä **ohittaa verkon oman position-paketin täysin** kyseiseltä solmulta —
ei vain silloin kun se on sumennettu, vaan myös silloin kun solmu ei
lähetä position-pakettia MQTT:hen lainkaan (esim. GPS pois päältä
kiinteältä asemalta, joka muuten vain tuhlaisi kaistaa toistamalla samaa
sijaintia). Ilman tätä molemmat tapaukset hylkäisivät solmun havainnot
kokonaan.

**Käytä vain oikeasti kiinteille asemille.** Liikkuvaan solmuun (auto)
lisätty `lat`/`lon` pinnaisi kaikki sen havainnot yhteen väärään
pisteeseen — se olisi pahempi virhe kuin sumennus, koska se ei näkyisi
mistään varoituksesta.

**Aja parse_logs.py uudestaan `--nodes`-lipulla** sen jälkeen kun olet
täyttänyt `nodes.json`:

```bash
python3 validate/parse_logs.py loki.ndjson \
    --nodes validate/nodes.json --out validate/havainnot.csv
```

Tämä on tärkeää: ilman lippua ensimmäinen ajo saattoi jo hylätä havaintoja
"liian lyhyt matka" -syyllä, jos verkon (sumennettu) sijainti sattui
näyttämään kahta solmua todellista lähempänä toisiaan. `--nodes`-lippu
korjaa sijainnin ennen etäisyyssuodatusta, ei vain sen jälkeen.

Ulostulon sarakkeet `tx_fixed`/`rx_fixed` (1/0) kertovat rivi riviltä,
käytettiinkö kiinteää sijaintia — ohitus ei siis jää piiloon datassa.
`collect/status.py` hyväksyy saman `--nodes`-lipun ja lakkaa varoittamasta
niistä solmuista, joille kiinteä sijainti on jo annettu.

## 3. Poimi maastoprofiilit

```bash
python3 validate/extract_profiles.py validate/havainnot.csv \
    --dem data/kemijoki_dem.vrt \
    --forest data/kemijoki_kp.vrt \
    --nodes validate/nodes.json \
    --out validate/profiilit.json --step 30
```

Korkeudet luetaan suoraan MML:n 2 m korkeusmallista ja latvuskorkeus
MVMI:stä — ei selaimen ruuduista, joissa on peittokartan tarpeisiin tehtyä
keskiarvoistusta.

## 4. Ennusta ja vertaa

```bash
node validate/predict.js validate/profiilit.json \
    --dn 45 --n0 325 --out validate/ennusteet.json

python3 validate/compare.py validate/ennusteet.json \
    --scatter validate/sirontakuvio.csv
```

`--dn` ja `--n0` luetaan ITU:n kartoista DN50 ja N050 alueen kohdalta;
niitä ei ole oletusarvoina eikä paketoitu mukaan, ks. `core/tests/README.md`.

Ennuste lasketaan **mediaanina** (pL = 50 %, sigmaL = 0, p = 50 %). Syy:
mittaus on yksi realisaatio yhdestä paikasta. Jos ennustettaisiin esim.
90 %:n varmuustasoa, saisimme systemaattisen poikkeaman joka kertoo vain
valitusta varmuustasosta. Jäännösten **hajonta on juuri se paikkavaihtelu**,
jonka haluamme mitata.

### Tulosten luku

- **Poikkeama** (bias) on systemaattinen virhe. Se pitää saada lähelle
  nollaa kalibroimalla.
- **Hajonta** on satunnaisvaihtelu. Jos se on luokkaa 6–10 dB, malli
  käyttäytyy odotetusti. Selvästi suurempi hajonta viittaa aineistoon —
  väärät antennikorkeudet, vanhat sijainnit, väärä lähetysteho — ei malliin.
- Erittely etäisyysluokittain ja reittityypeittäin (näköyhteys/esteinen)
  kertoo *missä* malli pettää, mikä on hyödyllisempää kuin yksi kokonaisluku.

### LoRa-RSSI:n korjaus

Kun SNR < 0, LoRa-vastaanotin raportoi RSSI:ksi kohinatason eikä signaalin
tehoa. Todellinen signaaliteho on tällöin likimain `RSSI + SNR`. Tämä koskee
juuri heikkoja linkkejä, joista mallin tarkkuus ratkeaa.

Korjaus on **oletuksena pois päältä**, koska se riippuu radiopiiristä ja
firmwaren raportointitavasta. Kytke päälle `--snr-correct` vasta kun tiedät
kumpaa lukua solmusi raportoivat. Aja mielellään molemmilla ja vertaa.

## 5. Kalibroi

```bash
python3 validate/compare.py --calibrate validate/profiilit.json \
    --dn 45 --n0 325 --r-range 0.5 2.0 --r-steps 16
```

Kalibroitava suure on **R_eff = k · R_MVMI**: miten MVMI:n puuston
keskipituus tulkitaan P.1812:n "edustavaksi latvuskorkeudeksi". Nämä eivät
ole sama asia — suhde riippuu mm. latvuspeittävyydestä ja siitä, kulkeeko
säde latvuston läpi vai yli.

**Mallia ei säädetä, vain tätä kerrointa.** Jos pienin RMSE osuu haarukan
reunaan (esim. 0,5 tai 2,0), älä laajenna haarukkaa vaan epäile aineistoa:
todennäköisimmin antennikorkeudet tai lähetystehot ovat väärin. Kerroin ei
saa korvata virheellistä metatietoa.

## Testit

```bash
python3 -m pytest validate/tests -q
```

Sisältää päästä päähän -testin, joka ajaa koko putken synteettisellä lokilla
oikeaa maastoaineistoa vasten. Se validoi putken, **ei mallia** — mitatut
RSSI:t ovat siinä keksittyjä. Ohittuu jos GDAL, node tai VRT puuttuu.

## Tiedossa olevat rajoitukset

- **Radioilmastovyöhyke on aina sisämaa (4).** Meri ja rannikko vaatisivat
  maanpeiteaineiston. Perämeren rannalla ennuste aliarvioi kantaman.
- **Ei rakennuksia.** Latvuskorkeus tulee metsäaineistosta.
- **Antennisuuntakuvioita ei mallinneta** — vahvistus on skalaari.
