# collect — MQTT-keruupalvelin (ylläpito)

Ystäville tarkoitettu ohje on [docs/keraysohje.md](../docs/keraysohje.md).
Tämä on palvelinpuolen puoli.

## Pystytys

```bash
sudo collect/setup_server.sh
```

Luo mosquitto-asetukset, ACL-pohjan, `kerays`-tunnuksen (jolla oma
kerääjä lukee kaiken) ja systemd-palvelun `oh9ab-collector`.
Ajon voi toistaa turvallisesti — olemassa olevia tunnuksia ja ACL:ää ei
ylikirjoiteta.

## Kerääjän lisääminen

```bash
sudo collect/add_collector.sh oh9xyz
```

(Oletusosoite on `propagation.rupsu.fi`. `OH9AB_MQTT_HOST=<muu>` ohittaa
sen, jos osoite joskus vaihtuu.)

Tulostaa tunnuksen, salasanan ja valmiit `meshtastic --set` -komennot
ystävälle lähetettäväksi. **Salasana näkyy vain kerran** — uuden voi luoda
ajamalla saman komennon uudelleen.

Jokainen kerääjä saa oman topic-juurensa `oh9ab/<nimi>` ja ACL-säännön,
joka sallii kirjoittamisen vain sinne. Näin näemme kenen solmusta havainto
tuli, ja yhden tunnuksen vuoto ei anna mahdollisuutta sotkea muiden dataa.

Kerääjän sulkeminen:

```bash
sudo mosquitto_passwd -D /etc/mosquitto/oh9ab.passwd oh9xyz
sudo systemctl reload mosquitto
```

## Älä "korjaa" salasanatiedoston omistajuutta

`mosquitto_passwd` varoittaa näin:

> Warning: File /etc/mosquitto/oh9ab.passwd owner is not root.
> Future versions will refuse to load this file.

**Älä noudata tuota neuvoa tässä ympäristössä.** Ubuntun paketoinnissa
mosquitto ajaa `mosquitto`-käyttäjänä alusta asti eikä pudota oikeuksia
rootista, joten root-omisteinen tiedosto tekee brokerista
käynnistymiskelvottoman:

```
Error: Unable to open pwfile "/etc/mosquitto/oh9ab.passwd".
mosquitto.service: Main process exited, code=exited, status=13/n/a
```

Oikeat oikeudet tässä paketoinnissa ovat `mosquitto:mosquitto` ja `0600`,
mitä `setup_server.sh` asettaa. Varoitus jää näkyviin — se on tiedossa.
Jos mosquitto joskus oikeasti kieltäytyy lataamasta tiedostoa, ratkaisu on
muuttaa systemd-yksikköä käynnistymään rootina, ei tiedoston omistajuutta.

## Näkyvyys internetiin

Ratkaistu: `propagation.rupsu.fi:1883` on porttiohjattu VM:n
(`10.10.10.153:1883`, yksityinen lähiverkko-osoite) mosquittoon.
Web-käyttöliittymä (portti 8123) kulkee saman domainin kautta reverse
proxyn takaa HTTPS:nä (`https://propagation.rupsu.fi/`) — MQTT sen sijaan
kulkee **suoraan porttiohjattuna, ei proxyn läpi**, koska mosquitto ei ole
HTTP:tä eikä reverse proxy (todennäköisesti nginx/caddy) proxyta raakaa
TCP:tä ilman erillistä stream-määrittelyä.

Tämä tarkoittaa: **MQTT-liikenne on edelleen salaamatonta**, vaikka
web-käyttöliittymä onkin HTTPS:n takana. Tunnistus on päällä
(käyttäjä/salasana), mutta ne kulkevat verkossa selväkielisenä, kuten
myös itse mittausdata (sijainnit, RSSI). Tämä on hyväksyttävää
harrastekäytössä kerääjäkohtaisilla salasanoilla (add_collector.sh
generoi 24 merkkiä), mutta on syytä tietää.

Jos halutaan salattu MQTT-yhteys myöhemmin: `mqtt.tls_enabled true`
solmuissa + portti 8883 + varmenne mosquittoon. Koska reverse proxy on jo
pystyssä domainille, sillä on todennäköisesti jo Let's Encrypt -varmenne
jota voisi käyttää myös mosquittolle (samat avaimet, eri portti) — ei siis
tarvitsisi erillistä varmennetta. Ei tehty vielä.

## Seuranta

```bash
# Palvelun tila ja viimeisimmät rivit
systemctl status oh9ab-collector
journalctl -u oh9ab-collector -n 50

# Kuka on yhdistänyt (mosquitto kirjaa yhteydet syslogiin)
journalctl -u mosquitto -n 50

# Aineiston kunto — tämä on tärkein
python3 collect/status.py logs/*.ndjson
```

`status.py` kertoo kerääjittäin ja solmuittain, montako viestiä on tullut,
**onko sijaintitarkkuus sumennettu** (yleisin ongelma, tekee datasta
arvottoman) ja montako käyttökelpoista havaintoa aineistosta irtoaa.

## "Ystävän data ei näy — miksi?"

```bash
python3 collect/mqtt_debug.py            # kaikki kerääjät, 60 s
python3 collect/mqtt_debug.py oh8efi     # vain yksi, epäilyttävä kerääjä
python3 collect/mqtt_debug.py oh8efi --seconds 180
```

Tämä automatisoi debug-päättelyn, joka muuten pitäisi tehdä käsin
`journalctl`- ja `mosquitto_sub`-komennoilla joka kerta uudestaan. Käyttää
valmiiksi olemassa olevaa `kerays`-tunnusta (lukuoikeus koko `oh9ab/#`-
puuhun), joten **ACL:ää ei tarvitse koskea**. Antaa yhden konkreettisen
johtopäätöksen per kerääjä:

- **ei yhteyttä mosquittoon** → tunnus/salasana/verkko väärin solmulla
- **yhdistää toistuvasti muttei julkaise mitään** → puhelimen sovellus tai
  verkkoyhteys epävakaa (esim. akunsäästö sulkee sovelluksen taustalla)
- **protobuf-paketteja näkyy mutta JSON ei koskaan** → EI enää ongelma:
  `collect/collector.py` purkaa protobufin suoraan (`mesh_decode.py`),
  JSONia ei tarvita. Todettu syy (2026-07-27, oh8efi & oh9fkj): **nRF52-
  pohjaiset laitteet (esim. RAK4631) eivät tue JSON-ulostuloa lainkaan** —
  laiteohjelmiston muistirajoitus, julkaisevat aina vain protobufia
  asetuksista riippumatta. ESP32-pohjaisella laitteella sama oire voi
  silti johtua siitä ettei JSON-kytkin ole oikeasti aktivoitunut — kokeile
  silloin kytkeä pois/päälle ja käynnistää solmu uudelleen.
- **JSONia näkyy** → toimii, kärsivällisyyttä (tiheys riippuu solmun
  lähetysvälistä, joka voi olla 15–60 min)

**Todettu oikea vika (oh9fkj, 2026-07-26): topic-juuren kirjainkoko.**
Solmun MQTT-asetuksissa "Palvelimen osoite (root topic)" oli kirjoitettu
`OH9AB/oh9fkj` — isolla alkukirjaimella. MQTT-topicit ovat
**kirjainkokoriippuvaisia**, joten se ei täsmännyt ACL:n eikä kenenkään
kuuntelijan odottamaan pieneen `oh9ab/oh9fkj`-poluun: yhteys toimi
täydellisesti (tunnus/salasana oikein), mutta yksikään paketti ei koskaan
päätynyt minnekään mistä sitä olisi voinut nähdä. Korjaus: kirjoita
kenttä täsmälleen niin kuin `add_collector.sh` sen tulosti, pienillä
kirjaimilla. `mqtt_debug.py` muistuttaa tästä nyt automaattisesti kun
kerääjä yhdistää muttei julkaise mitään.

**Muista: jokainen kerääjätunnus näkee MQTT Explorerissa vain oman
juurensa** (`oh9ab/<nimi>/#`), koska ACL rajaa sen niin. Jos joku
kerääjätunnus näyttää Explorerissa ettei mitään tule, tarkista ensin ettet
ole vahingossa kirjautunut väärällä (esim. toisen kerääjän) tunnuksella —
käytä `kerays`-tunnusta nähdäksesi kaiken kerralla.

**Jos epäilet väärää topic-juurta** (solmu julkaisisi jonnekin muualle
kuin `oh9ab/<nimi>/#`-puuhun), `mqtt_debug.py` ei näytä sitä, koska
`kerays` on rajattu `oh9ab/#`:iin. Silloin ainoa keino on tilapäisesti
laajentaa `kerays`:n ACL koko brokeriin:

```bash
sudo cp /etc/mosquitto/oh9ab.acl /etc/mosquitto/oh9ab.acl.bak
sudo python3 -c "
p = '/etc/mosquitto/oh9ab.acl'
t = open(p).read().replace('user kerays\ntopic read oh9ab/#', 'user kerays\ntopic read #')
open(p, 'w').write(t)"
sudo systemctl reload mosquitto
# ... kuuntele mosquitto_sub -h localhost -u kerays -P "$(cat /etc/mosquitto/kerays.secret)" -t '#' -F '%t'
# palauta heti kun tiedät:
sudo cp /etc/mosquitto/oh9ab.acl.bak /etc/mosquitto/oh9ab.acl
sudo rm /etc/mosquitto/oh9ab.acl.bak
sudo systemctl reload mosquitto
```

## Protobuf-topicin purku (ei enää riipu JSON-kytkimestä)

`collector.py` lukee JSON-mirrorin (`.../2/json/...`) lisäksi myös
protobuf-perustopicin (`.../2/e/...`) `mesh_decode.py`:llä. Tämä lisättiin
2026-07-26, koska osa solmuista (oh8efi, oh9fkj) ei koskaan julkaissut
JSON-kopiota vaikka protobuf tuli luotettavasti — protobuf-topic lähtee
aina kun kanavalla on uplink_enabled, riippumatta erillisestä
JSON-kytkimestä. Molemmat polut tuottavat saman kenttämuodon, joten
`validate/parse_logs.py` ei tarvitse muutoksia.

Tukee toistaiseksi vain kanavan oletus-PSK:ta ("AQ=="/EdgeFastLow, tämän
verkon nykyinen asetus). Ks. `mesh_decode.py`:n moduulidokumentti ja
`collect/pb/README.md` (protobuf-skeemojen alkuperä ja
uudelleengenerointi).

## Havaintokartta (havainnot.html) ja sen automaattipäivitys

`havainnot.html` (repon juuressa) näyttää kerätyt RSSI-havainnot kartalla
solmukohtaisina kerroksina. Ei linkitetty index.html:stä tarkoituksella —
tarkoitettu kerääjille itselleen, ei julkiseksi.

`collect/update_havainnot.sh` yhdistää kaikki `logs/*.ndjson`-tiedostot ja
ajaa `validate/parse_logs.py`:n uudelleen, kirjoittaen tuloksen atomisesti
(`mv` samalla tiedostojärjestelmällä) `validate/havainnot.csv`:hen, jotta
sivu ei koskaan lue puolittain kirjoitettua tiedostoa. Cronissa (`crontab -l`
käyttäjällä `claude`) 15 minuutin välein:

```
*/15 * * * * /home/claude/oh9ab/collect/update_havainnot.sh >> /home/claude/oh9ab/logs/update_havainnot.log 2>&1
```

Lokia kannattaa silloin tällöin siivota (`update_havainnot.log` kasvaa
rajattomasti) — ei automatisoitu, koska kasvunopeus on tässä mittakaavassa
merkityksetön.

## Lokien käyttö validointiin

Lokit ovat suoraan validointiputken syötettä:

```bash
python3 validate/parse_logs.py logs/2026-07-26.ndjson --out validate/havainnot.csv
```

Useampi päivä kerralla: yhdistä ensin.

```bash
cat logs/*.ndjson > /tmp/kaikki.ndjson
python3 validate/parse_logs.py /tmp/kaikki.ndjson --out validate/havainnot.csv
```

Jatko: [validate/README.md](../validate/README.md).

## Mitä lokiin lisätään

Kerääjä lisää jokaiseen viestiin kaksi kenttää, joita alkuperäisessä ei ole:

- `_rx_time` — palvelimen kello viestin saapuessa. Meshtastic-solmun oma
  `timestamp` tulee sen omasta kellosta, joka voi olla tunteja pielessä
  ilman GPS-kiinnitystä. Palvelimen kelloon voi luottaa.
- `_collector` — kerääjän nimi topicista, eli kenen solmu tämän lähetti.

Jäsennin sivuuttaa ylimääräiset kentät, joten lokit kelpaavat sellaisenaan.

## Tietosuoja

Lokit sisältävät ihmisten sijainteja. Ne ovat `.gitignore`ssa eivätkä kuulu
julkiseen repoon. Jos kerääjä pyytää datansa poistoa, se on poistettava —
tämä on luvattu ohjeessa. Solmun tunnuksella suodattaminen:

```bash
grep -v '"from": 2852126721' logs/paiva.ndjson > /tmp/siivottu && \
    mv /tmp/siivottu logs/paiva.ndjson
```
