# Meshtastic-mittausdatan keruu — ohje

Kiitos että lähdet mukaan. Tämä ohje kertoo, miten saat solmusi lähettämään
kuuluvuushavaintoja OH9AB:n keruupalvelimelle.

**Mistä on kyse.** Rakennamme kuuluvuusennustetta, joka käyttää
Maanmittauslaitoksen 2 metrin korkeusmallia ja Luken metsäaineistoa.
Malli (ITU-R P.1812-8) on valmis ja testattu, mutta sitä ei ole vielä
kertaakaan verrattu todellisuuteen. Siihen tarvitaan mittauksia: kun solmusi
kuulee toisen solmun, se tietää signaalin voimakkuuden (RSSI) ja molempien
sijainnit. Juuri sitä vertaamme ennusteeseen.

**Yksi solmu ei riitä.** Mitä useampi kerääjä ja mitä erilaisempia
maastoja, sitä paremmin saamme selville *missä* malli pettää.

---

## 1. Lue tämä ensin: mitä jaat

Kun kytket MQTT-lähetyksen päälle, solmusi lähettää palvelimelle:

- **oman sijaintisi** ja niiden solmujen sijainnit, jotka se kuulee
- kuulemiensa pakettien signaalinvoimakkuudet
- solmutunnukset ja aikaleimat
- kanavalla kulkevien viestien sisällöt, jos ne ovat kanavalla jota lähetät

Käytännössä siis **kotisi tai autosi sijainti päätyy palvelimelle** ja
tallentuu lokiin. Palvelin on OH9AB:n hallinnassa, ei julkinen, ja vaatii
tunnuksen. Dataa käytetään vain mallin validointiin.

Jos et halua jakaa tarkkaa kotisijaintia, hyviä vaihtoehtoja:

- käytä erillistä solmua sovitussa paikassa (mökki, mastopaikka, työpaikka)
- osallistu vain liikkuvalla solmulla (auto), jolloin kotiosoite ei paljastu
- kysy meiltä, jos haluat että tietyt solmut jätetään aineistosta pois

**Älä lähetä sellaista kanavaa, jolla käydään yksityisiä keskusteluja.**
Tee mieluiten oma kanava tätä varten tai käytä julkista LongFast-kanavaa.

Voit lopettaa milloin tahansa (kohta 7).

---

## 2. Mitä tarvitset

- Meshtastic-solmu, jossa on **GPS** (ilman sijaintia data ei kelpaa)
- Solmulle **internet-yhteys**: joko WiFi/Ethernet suoraan, tai puhelimen
  kautta (`mqtt.proxy_to_client_enabled`)
- Meshtastic-sovellus puhelimessa **tai** `meshtastic`-komentorivityökalu
- Meiltä saamasi **tunnus, salasana ja topic-juuri**

Pyydä tunnukset OH9AB:lta. Saat viestin, jossa on:

```
Palvelin:    <osoite>
Portti:      1883
Käyttäjä:    <tunnus>
Salasana:    <salasana>
Topic-juuri: oh9ab/<tunnus>
```

---

## 3. Asetukset

### Vaihtoehto A: komentoriviltä (nopein)

Kytke solmu USB:llä tietokoneeseen ja aja nämä. Korvaa kulmasulut omillasi.

```bash
meshtastic --set mqtt.address <osoite>
meshtastic --set mqtt.username <tunnus>
meshtastic --set mqtt.password <salasana>
meshtastic --set mqtt.root oh9ab/<tunnus>
meshtastic --set mqtt.enabled true
meshtastic --set mqtt.json_enabled true
meshtastic --set mqtt.encryption_enabled false
meshtastic --ch-index 0 --ch-set uplink_enabled true
meshtastic --ch-index 0 --ch-set position_precision 32
```

Jos solmullasi ei ole omaa verkkoyhteyttä vaan se käyttää puhelinta:

```bash
meshtastic --set mqtt.proxy_to_client_enabled true
```

### Vaihtoehto B: puhelinsovelluksesta

Valikkojen nimet vaihtelevat hieman versioittain, mutta polku on:

1. **Asetukset → Radioasetukset → MQTT** (Module Configuration → MQTT)
   - MQTT käyttöön: **päälle**
   - Palvelinosoite, käyttäjätunnus, salasana: saamasi arvot
   - Root topic: `oh9ab/<tunnus>`
   - **JSON output: päälle** ← tämä on pakollinen
   - **Encryption: pois** (JSON ei toimi salattuna)
   - Jos solmulla ei ole omaa nettiä: **Proxy to client: päälle**
2. **Asetukset → Kanavat → (kanava jota käytät)**
   - **Uplink: päälle**
   - **Position precision: Full / Tarkka (32)** ← katso kohta 5

Solmu käynnistyy uudelleen asetusten jälkeen.

---

## 4. Kerro solmusi tiedot

**Tämä on yhtä tärkeää kuin itse data.** Lokeista ei näy antennin korkeus,
lähetysteho eikä antennin tyyppi — ja ilman niitä mittausta ei voi verrata
ennusteeseen. Väärä antennikorkeus tekee havainnosta pahimmillaan
harhaanjohtavan.

Lähetä meille jokaisesta solmustasi:

| Tieto | Esimerkki | Huom |
|---|---|---|
| Solmutunnus | `!a1b2c3d4` | näkyy sovelluksesta |
| Nimi/kutsu | OH9XYZ koti | vapaamuotoinen |
| **Antennin korkeus maanpinnasta** | 8 m | **metreinä maanpinnasta**, ei merenpinnasta |
| Antennityyppi ja vahvistus | vertikaali, 2 dBi | arvio riittää |
| Lähetysteho | 27 dBm | EU_868 tyypillisesti 27 dBm |
| Kaapelihäviö | 1 dB | jos antenni on kaukana radiosta |
| Kiinteä vai liikkuva | kiinteä | auto = liikkuva |

Antennin korkeus **maanpinnasta**: jos antenni on 8 metrin mastossa
maanpinnalla, se on 8 m. Jos se on omakotitalon katolla 6 metrissä ja
mastoa on 3 m, se on 9 m. Maanpinnan korkeus merenpinnasta luetaan
korkeusmallista, joten sinun ei tarvitse tietää sitä.

Karkeakin arvio on paljon parempi kuin ei mitään — mutta jos arvaat,
kerro että arvasit.

---

## 5. Tarkista että data on käyttökelpoista

Kerro meille kun olet kytkenyt lähetyksen päälle, niin ajamme
tarkistuksen. Se kertoo heti, tuleeko solmustasi käyttökelpoista dataa.

Yleisin ongelma on **sumennettu sijainti**. Meshtasticissa on
yksityisyysasetus, joka pyöristää koordinaatit — oletuksena jopa noin
1,5 kilometrin tarkkuuteen. Sillä data on validoinnin kannalta arvotonta,
koska maastoprofiili poimittaisiin väärästä paikasta, eikä sitä huomaisi
mistään muusta kuin oudoista tuloksista.

Korjaus:

```bash
meshtastic --ch-index 0 --ch-set position_precision 32
```

Tarkistus kertoo myös, kuinka moni kuulemasi paketti tuli **suoraan** eikä
releen kautta. Vain suorat kelpaavat: releen kautta tulleen paketin RSSI
kuvaa releen ja sinun väliäsi, ei alkuperäisen lähettäjän. Tämä on normaalia
— usein valtaosa paketeista on releiltä — mutta se kannattaa tietää, jotta
ei ihmettele miksi "tuhannesta paketista jäi sata".

---

## 6. Millainen data on arvokkainta

Kaikki data auttaa, mutta nämä auttavat eniten:

**Liikkuva solmu autossa on kullanarvoinen.** Se näytteistää kymmeniä
maastotyyppejä ja etäisyyksiä yhden ajomatkan aikana. Yksi päivä ajelua
tuottaa enemmän käyttökelpoista aineistoa kuin kuukausi kahden kiinteän
solmun välillä, koska kiinteä pari mittaa aina samaa yhtä reittiä.

**Rajatapaukset ovat arvokkaampia kuin varmat yhteydet.** Linkki joka
toimii juuri ja juuri, tai katkeilee, kertoo mallista enemmän kuin
näköyhteys naapurimastoon. Jos huomaat paikan jossa yhteys yllättäen
toimii tai yllättäen ei toimi, mainitse se.

**Metsä ja maastonmuodot.** Projektin koko idea on, että metsä mallinnetaan.
Mittaukset tiheän kuusikon takaa tai vaaran varjosta ovat juuri niitä
joilla malli joko todistaa itsensä tai ei.

**Pitkä keräysjakso.** Sama linkki eri vuodenaikoina kertoo lumen ja
lehtien vaikutuksen — sitä ei saa mistään muualta.

**Kerro jos jotain muuttuu.** Antennin vaihto, maston korotus, solmun
siirto: kaikki muuttavat tulkintaa. Vanha data ei mene hukkaan, mutta
meidän pitää tietää milloin muutos tapahtui.

---

## 7. Lopettaminen

Voit lopettaa milloin tahansa:

```bash
meshtastic --set mqtt.enabled false
```

tai sovelluksesta MQTT pois päältä. Kerro meille, niin suljemme tunnuksesi.
Jos haluat että jo kerätty datasi poistetaan, sano — poistamme sen.

---

## Kysymyksiä

**Kuluttaako tämä paljon dataa?** Ei. Meshtastic-paketit ovat pieniä,
tyypillisesti muutamia megatavuja kuukaudessa.

**Näkyykö dataani muille?** Ei. Palvelin ei ole julkinen, jokaisella on oma
tunnus, ja jokainen näkee vain oman topic-juurensa.

**Voinko lähettää samaan aikaan julkiselle MQTT-palvelimelle?** Meshtastic
tukee vain yhtä MQTT-palvelinta kerrallaan. Joudut valitsemaan.

**Vaikuttaako tämä mesh-verkon toimintaan?** MQTT-lähetys ei muuta
radiotoimintaa. Solmusi toimii verkossa täsmälleen kuten ennenkin.

**Entä jos solmullani ei ole GPS:ää?** Sijainnin voi asettaa käsin kiinteälle
solmulle (`meshtastic --setlat / --setlon`). Kiinteälle asemalle se on
täysin riittävä — itse asiassa tarkempi kuin GPS.
