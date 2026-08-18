# core/tests — P.1812-8 -portin testaus

Kaksi tasoa, molemmat vaativat ITU:n referenssitoteutuksen
[Py1812](https://github.com/eeveetza/Py1812) (kloonaa esim. `~/Py1812`).

## 1. Funktiokohtaiset satunnaisvektorit

Vertaa jokaista portattua funktiota erikseen referenssiin. Tämä löytää
poikkeamat, jotka päästä päähän -testissä kompensoituisivat keskenään —
P.1812:n virheet ovat hiljaisia.

```bash
PYTHONPATH=~/Py1812/src python3 core/tests/gen_vectors.py > core/tests/vectors.json
node core/tests/run_tests.js
```

## 2. ITU:n viralliset validointiprofiilit

Projektin ehdoton hyväksymistesti: sama aineisto ja sama toleranssi (1e-8)
kuin ITU:n omassa `validateP1812.py`:ssä.

```bash
cd ~/Py1812/tests
PYTHONPATH=~/Py1812/src python3 ~/oh9ab/core/tests/itu_vectors.py \
    > ~/oh9ab/core/tests/itu_vectors.json
cd ~/oh9ab && node core/tests/run_itu_tests.js
```

## Huomioita

**Vektoritiedostoja ei committoida.** `itu_vectors.json` sisältää ITU-R SG3:n
mittausprofiileja, joiden levitysoikeutta emme ole selvittäneet; `vectors.json`
on joka tapauksessa generoitavissa. Molemmat ovat `.gitignore`ssa.

**ITU:n digitaalikartat.** Py1812 lataa käynnistyessään `P1812.npz`:n, joka
rakennetaan ITU:n kartoista `DN50.TXT` ja `N050.TXT`. Ne ovat ITU:n
"integral digital products", joita **ei saa levittää eteenpäin ilman ITU:n
kirjallista lupaa** — ei siis repoon eikä selainsovelluksen mukana. Karttoja
luetaan vain jos `DN`/`N0` jätetään antamatta, ja tässä portissa ne on
**pakko** antaa eksplisiittisesti reitin keskipisteen arvoina. Testiajoa
varten `~/Py1812/src/Py1812/P1812.npz` voi olla NaN-täytteinen tynkä.

**Generaattorin syötealueet** on pidettävä fysikaalisina (esim. `hts − hstd > 0`),
muuten referenssi tuottaa NaN:eja. `json.dump(..., allow_nan=False)` pysäyttää
ajon, jos niitä silti syntyy.
