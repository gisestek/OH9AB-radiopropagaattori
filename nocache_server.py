#!/usr/bin/env python3
"""Kuten `python3 -m http.server`, mutta ilman selainvälimuistia ja
oikealla merkistöilmoituksella.

Kaksi eroa vakiopalvelimeen:

1.  **Ei välimuistia.** Prototyyppi muuttuu usein, ja tavallinen http.server
    antaa selaimen cachettaa .js/.html-tiedostot ETagin/Last-Modifiedin
    perusteella, jolloin muutokset eivät näy ilman manuaalista
    cache-bustausta.

2.  **charset=utf-8 kaikkiin tekstityyppeihin.** Python ilmoittaa .md- ja
    .js-tiedostoille tyypin ilman merkistöä (esim. pelkkä `text/markdown`),
    jolloin selain arvaa merkistön — yleensä windows-1252 — ja ääkköset
    menevät rikki. HTML-sivuilla ongelmaa ei näy, koska niissä on oma
    <meta charset>, mutta .md-ohjeissa ei ole mitään mistä arvata.

Tuotannossa tätä ei käytettäisi, mutta tälle prototyypille kehitys- ja
lukumukavuus voittaa.
"""
import http.server
import io
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdrender  # noqa: E402

# Tyypit joihin merkistö kuuluu. text/* kattaa .md, .txt, .css ja .html;
# JS, JSON ja SVG ilmoitetaan erikseen, koska niiden tyyppi ei ala text/.
TEXTUAL_EXTRA = {
    "application/javascript",
    "application/x-javascript",
    "application/json",
    "image/svg+xml",
}


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def guess_type(self, path):
        ctype = super().guess_type(path)
        base = ctype.split(";", 1)[0].strip()
        if "charset=" not in ctype and (base.startswith("text/")
                                        or base in TEXTUAL_EXTRA):
            return ctype + "; charset=utf-8"
        return ctype

    def send_head(self):
        """Renderöi .md-tiedostot luettavaksi HTML:ksi.

        Ohjeet on tarkoitus jakaa linkkinä eteenpäin, ja raaka markdown on
        selaimessa hankalaa luettavaa. ?raw=1 antaa alkuperäisen tiedoston."""
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.lower().endswith(".md"):
            qs = urllib.parse.parse_qs(parsed.query)
            if "raw" not in qs:
                return self._send_markdown(parsed.path)
        return super().send_head()

    def _send_markdown(self, urlpath):
        fspath = self.translate_path(urlpath)
        try:
            with open(fspath, encoding="utf-8", errors="replace") as f:
                md = f.read()
        except OSError:
            self.send_error(404, "File not found")
            return None

        page = mdrender.render_page(md).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        return io.BytesIO(page)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    http.server.ThreadingHTTPServer(("0.0.0.0", port), NoCacheHandler).serve_forever()
