"""Pieni markdown → HTML -muunnin ilman ulkoisia riippuvuuksia.

Kattaa sen mitä tämän projektin ohjeissa käytetään: otsikot, lihavointi,
kursiivi, koodi (rivinsisäinen ja aidattu), linkit, listat, taulukot,
lainaukset ja vaakaviivat. Ei yritä olla täydellinen markdown-toteutus.

TÄRKEIN YKSITYISKOHTA on HTML-suojaus. Ohjeissa on paljon tekstiä muotoa
`<osoite>`, `<tunnus>` ja `<meta charset>`. Ilman suojausta selain nielaisisi
ne tuntemattomina HTML-tageina ja ohjeesta katoaisi juuri se kohta, jonka
lukijan pitäisi korvata omalla arvollaan. Siksi kaikki teksti escapetaan
ennen muotoilusääntöjä, ja koodilohkot jätetään muotoilun ulkopuolelle.
"""

import html
import re

# Sallitut linkkiprotokollat. Estää javascript:-tyyppiset URLit, vaikka
# tässä renderöidäänkin vain omia ohjeita.
_SAFE_LINK = re.compile(r'^(?:https?:|mailto:|[^:]*$|#)', re.I)


def _esc(s):
    return html.escape(s, quote=True)


def _link(m):
    text, url = m.group(1), m.group(2)
    raw = html.unescape(url)
    if not _SAFE_LINK.match(raw):
        return _esc("[%s](%s)" % (text, url))
    ext = ' target="_blank" rel="noopener"' if raw.lower().startswith("http") else ""
    return '<a href="%s"%s>%s</a>' % (url, ext, text)


def inline(text):
    """Rivinsisäinen muotoilu. Teksti escapetaan tässä, ei ennen."""
    out = []
    # Koodinpätkät irrotetaan ensin: niiden sisällä ei muotoilla mitään.
    for part in re.split(r'(`[^`]+`)', text):
        if len(part) >= 2 and part.startswith('`') and part.endswith('`'):
            out.append('<code>' + _esc(part[1:-1]) + '</code>')
            continue
        s = _esc(part)
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'(?<![\*\w])\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', s)
        s = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', _link, s)
        out.append(s)
    return ''.join(out)


def _is_table_sep(line):
    return bool(re.match(r'^\s*\|?[\s:|-]+\|[\s:|-]*$', line)) and '-' in line


def _cells(line):
    line = line.strip()
    if line.startswith('|'):
        line = line[1:]
    if line.endswith('|'):
        line = line[:-1]
    return [c.strip() for c in line.split('|')]


def render_body(md):
    """Markdown → HTML-runko (ilman <html>-kuorta)."""
    lines = md.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]

        # aidattu koodilohko
        m = re.match(r'^\s*```+\s*(\S*)', line)
        if m:
            lang = m.group(1)
            i += 1
            buf = []
            while i < n and not re.match(r'^\s*```+\s*$', lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1   # ohita päättävä aitaus
            cls = ' class="lang-%s"' % _esc(lang) if lang else ''
            out.append('<pre%s><code>%s</code></pre>'
                       % (cls, _esc('\n'.join(buf))))
            continue

        if not line.strip():
            i += 1
            continue

        # vaakaviiva
        if re.match(r'^\s*([-*_])\s*(\1\s*){2,}$', line):
            out.append('<hr>')
            i += 1
            continue

        # otsikko
        m = re.match(r'^\s*(#{1,6})\s+(.*?)\s*#*\s*$', line)
        if m:
            lvl = len(m.group(1))
            out.append('<h%d>%s</h%d>' % (lvl, inline(m.group(2)), lvl))
            i += 1
            continue

        # taulukko: vähintään otsikkorivi + erotinrivi
        if '|' in line and i + 1 < n and _is_table_sep(lines[i + 1]):
            head = _cells(line)
            i += 2
            rows = []
            while i < n and '|' in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            t = ['<div class="tablewrap"><table><thead><tr>']
            t += ['<th>%s</th>' % inline(c) for c in head]
            t.append('</tr></thead><tbody>')
            for r in rows:
                t.append('<tr>' + ''.join('<td>%s</td>' % inline(c) for c in r) + '</tr>')
            t.append('</tbody></table></div>')
            out.append(''.join(t))
            continue

        # lainaus
        if re.match(r'^\s*>\s?', line):
            buf = []
            while i < n and re.match(r'^\s*>\s?', lines[i]):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i]))
                i += 1
            out.append('<blockquote>%s</blockquote>' % render_body('\n'.join(buf)))
            continue

        # listat (yksitasoiset riittävät näihin ohjeisiin)
        m_ul = re.match(r'^\s*[-*+]\s+(.*)$', line)
        m_ol = re.match(r'^\s*\d+[.)]\s+(.*)$', line)
        if m_ul or m_ol:
            tag = 'ul' if m_ul else 'ol'
            pat = r'^\s*[-*+]\s+(.*)$' if m_ul else r'^\s*\d+[.)]\s+(.*)$'
            items = []
            while i < n:
                m2 = re.match(pat, lines[i])
                if m2:
                    items.append([m2.group(1)])
                    i += 1
                    # jatkorivit: sisennetty tai tavallinen teksti listan sisällä
                    while (i < n and lines[i].strip()
                           and not re.match(r'^\s*([-*+]|\d+[.)])\s+', lines[i])
                           and not re.match(r'^\s*#', lines[i])
                           and not re.match(r'^\s*```', lines[i])):
                        items[-1].append(lines[i].strip())
                        i += 1
                elif not lines[i].strip():
                    break
                else:
                    break
            out.append('<%s>%s</%s>' % (
                tag, ''.join('<li>%s</li>' % inline(' '.join(it)) for it in items), tag))
            continue

        # kappale
        buf = []
        while (i < n and lines[i].strip()
               and not re.match(r'^\s*(#|>|```|[-*+]\s|\d+[.)]\s)', lines[i])
               and not re.match(r'^\s*([-*_])\s*(\1\s*){2,}$', lines[i])):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append('<p>%s</p>' % inline(' '.join(buf)))
        else:
            i += 1

    return '\n'.join(out)


def render_page(md, title=None, css_href="/doc.css", home_href="/index.html"):
    """Kokonainen sivu, samalla merikarttatyylillä kuin muu työkalu."""
    body = render_body(md)
    if not title:
        m = re.search(r'^\s*#\s+(.+?)\s*$', md, re.M)
        title = m.group(1) if m else "Ohje"
    return (
        '<!DOCTYPE html>\n<html lang="fi">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>%s</title>\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700'
        '&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500'
        '&display=swap" rel="stylesheet">\n'
        '<link rel="stylesheet" href="%s">\n'
        '</head>\n<body>\n<div class="doc">\n'
        '<nav class="docnav"><a href="%s">← OH9AB-työkalut</a></nav>\n'
        '%s\n</div>\n</body>\n</html>\n'
        % (_esc(title), _esc(css_href), _esc(home_href), body))
