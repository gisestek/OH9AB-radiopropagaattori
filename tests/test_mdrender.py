"""Testit markdown-renderöijälle.

Painopiste HTML-suojauksessa: ohjeissa on paljon tekstiä muotoa <osoite>
ja <tunnus>, jotka lukijan on tarkoitus korvata omilla arvoillaan. Jos ne
menisivät läpi suojaamattomina, selain nielaisisi ne tuntemattomina
tageina ja ohjeesta katoaisi juuri se kohta joka piti täyttää.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mdrender  # noqa: E402


# ── HTML-suojaus ──────────────────────────────────────────────

def test_kulmasulkeet_sailyvat_nakyvissa():
    h = mdrender.render_body("Palvelin: <osoite> ja tunnus <tunnus>")
    assert "&lt;osoite&gt;" in h
    assert "<osoite>" not in h


def test_kulmasulkeet_koodissa():
    h = mdrender.render_body("Aseta `<meta charset>` sivulle")
    assert "<code>&lt;meta charset&gt;</code>" in h


def test_kulmasulkeet_koodilohkossa():
    h = mdrender.render_body("```\nmeshtastic --set mqtt.address <osoite>\n```")
    assert "&lt;osoite&gt;" in h
    assert "<osoite>" not in h


def test_ampersand_suojataan():
    assert "&amp;" in mdrender.render_body("Simo & Kemi")


def test_html_injektio_ei_mene_lapi():
    h = mdrender.render_body("<script>alert(1)</script>")
    assert "<script>" not in h
    assert "&lt;script&gt;" in h


# ── rivinsisäinen muotoilu ────────────────────────────────────

def test_lihavointi_ja_kursiivi():
    h = mdrender.render_body("Tämä on **tärkeä** ja *tämä* kursiivi")
    assert "<strong>tärkeä</strong>" in h
    assert "<em>tämä</em>" in h


def test_koodin_sisalla_ei_muotoilla():
    h = mdrender.render_body("Komento `--set **ei-lihava**` tässä")
    assert "<strong>" not in h
    assert "**ei-lihava**" in h


def test_linkki():
    h = mdrender.render_body("Katso [ohje](docs/keraysohje.md) tästä")
    assert '<a href="docs/keraysohje.md">ohje</a>' in h


def test_ulkoinen_linkki_avautuu_uuteen_valilehteen():
    h = mdrender.render_body("[ITU](https://www.itu.int/)")
    assert 'target="_blank"' in h and 'rel="noopener"' in h


def test_javascript_linkki_estetaan():
    h = mdrender.render_body("[klikkaa](javascript:alert(1))")
    assert "<a " not in h
    assert "javascript:" in h  # jää näkyviin tekstinä, ei linkkinä


# ── lohkotason rakenteet ──────────────────────────────────────

def test_otsikot():
    h = mdrender.render_body("# Ykkönen\n\n## Kakkonen\n\n### Kolmonen")
    assert "<h1>Ykkönen</h1>" in h
    assert "<h2>Kakkonen</h2>" in h
    assert "<h3>Kolmonen</h3>" in h


def test_luettelo():
    h = mdrender.render_body("- eka\n- toka\n- kolmas")
    assert h.count("<li>") == 3 and "<ul>" in h


def test_numeroitu_luettelo():
    h = mdrender.render_body("1. eka\n2. toka")
    assert "<ol>" in h and h.count("<li>") == 2


def test_taulukko():
    md = "| Tieto | Esimerkki |\n|---|---|\n| Korkeus | 8 m |\n| Teho | 27 dBm |"
    h = mdrender.render_body(md)
    assert "<th>Tieto</th>" in h
    assert "<td>8 m</td>" in h
    assert h.count("<tr>") == 3
    # leveä taulukko vierii omassa laatikossaan eikä venytä sivua
    assert 'class="tablewrap"' in h


def test_koodilohko_sailyttaa_rivinvaihdot():
    h = mdrender.render_body("```bash\neka\ntoka\n```")
    assert "<pre" in h and "eka\ntoka" in h
    assert 'class="lang-bash"' in h


def test_lainaus():
    h = mdrender.render_body("> Varoitus tässä")
    assert "<blockquote>" in h and "Varoitus tässä" in h


def test_vaakaviiva():
    assert "<hr>" in mdrender.render_body("teksti\n\n---\n\nlisää")


def test_kappaleet_erottuvat():
    h = mdrender.render_body("Eka kappale.\n\nToka kappale.")
    assert h.count("<p>") == 2


# ── kokonainen sivu ───────────────────────────────────────────

def test_sivussa_merkisto_ja_otsikko():
    page = mdrender.render_page("# Keräysohje\n\nTekstiä ääkkösillä: äöå")
    assert '<meta charset="utf-8">' in page
    assert "<title>Keräysohje</title>" in page
    assert "äöå" in page
    assert 'href="/doc.css"' in page


# ── oikeat projektin ohjeet ───────────────────────────────────

REAL_DOCS = ["docs/keraysohje.md", "validate/README.md", "collect/README.md",
             "core/tests/README.md", "README.md"]


@pytest.mark.parametrize("rel", REAL_DOCS)
def test_oikeat_ohjeet_renderoityvat(rel):
    p = ROOT / rel
    if not p.exists():
        pytest.skip("%s puuttuu" % rel)
    md = p.read_text(encoding="utf-8")
    page = mdrender.render_page(md)
    assert "<h1>" in page or "<h2>" in page
    # ääkkösten pitää säilyä koskemattomina
    for ch in "äöå":
        if ch in md:
            assert ch in page
    # raakaa markdownia ei saa jäädä näkyviin
    assert "\n## " not in mdrender.render_body(md)


def test_keraysohjeen_avainkohdat_sailyvat():
    p = ROOT / "docs" / "keraysohje.md"
    if not p.exists():
        pytest.skip("keraysohje puuttuu")
    h = mdrender.render_body(p.read_text(encoding="utf-8"))
    # täytettävät paikat eivät saa kadota HTML-tageina
    assert "&lt;osoite&gt;" in h
    assert "&lt;tunnus&gt;" in h
    # kriittinen komento pitää näkyä
    assert "position_precision" in h
