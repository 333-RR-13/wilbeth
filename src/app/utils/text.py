"""Sichere Freitext-Darstellung fuer Nutzer-gepflegte Felder, die Azubis
ausgeliefert werden (aktuell: Department.info_text/info_link, siehe
app/routers/share.py -- Abteilungs-Detailseite).

linkify() wird NIE mit rohem HTML-Markup aufgerufen -- der Eingabetext ist
reiner Freitext aus einem <textarea>. Sicherheitsregel (siehe Projektauftrag):
ERST escapen, DANN Links einsetzen -- so kann ein Angreifer ueber den
Freitext niemals aktives Markup einschleusen (auch nicht ueber eine
"URL", die HTML/JS enthaelt), weil zu dem Zeitpunkt, an dem URLs gesucht
werden, bereits alle spitzen Klammern/Anfuehrungszeichen unschaedlich
gemacht sind.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from markupsafe import Markup, escape

# Nur http(s)-URLs werden erkannt -- alles andere (javascript:, data:, ...)
# bleibt reiner (escapter) Text. '<' beendet den Match immer, echte Leerzeichen
# ebenfalls (auch das escapte "&nbsp;" enthaelt kein rohes Leerzeichen mehr).
_URL_RE = re.compile(r"https?://[^\s<]+")

# Satzzeichen, die typischerweise NICHT mehr zur URL gehoeren, wenn sie am
# Ende eines automatisch erkannten Links stehen (z. B. "...siehe https://x.de.").
# BEWUSST OHNE ';': Da erst escaped und dann verlinkt wird, endet ein Match
# haeufig auf einer HTML-Entity ("&#34;", "&amp;"). Ein gestripptes Semikolon
# wuerde die Entity zerstoeren ("&#34") -- ungefaehrlich, aber unsauber.
# URLs, die tatsaechlich auf ein Semikolon enden, sind der seltenere Fall.
_TRAILING_PUNCTUATION = ".,:!?)'\""


def _make_link(match: "re.Match[str]") -> str:
    url = match.group(0)
    trailing = ""
    while url and url[-1] in _TRAILING_PUNCTUATION:
        trailing = url[-1] + trailing
        url = url[:-1]
    if not url:
        return match.group(0)
    return f'<a href="{url}" rel="noopener noreferrer" target="_blank">{url}</a>{trailing}'


def linkify(text: str | None) -> Markup:
    """Wandelt Freitext SICHER in HTML-Markup um: Absaetze (Leerzeile
    trennt), Zeilenumbrueche innerhalb eines Absatzes als <br>, enthaltene
    http(s)-URLs werden zu klickbaren Links (rel="noopener noreferrer",
    target="_blank"). Alles andere wird escaped und bleibt reiner Text.

    Reihenfolge ist sicherheitsrelevant: ERST wird der komplette Text
    escaped (markupsafe.escape -- neutralisiert <script>, Anfuehrungszeichen
    etc.), ERST DANACH werden auf dem bereits escapten String URLs gesucht
    und durch <a>-Tags ersetzt. Ein Text wie "<script>alert(1)</script>"
    kann so niemals aktives Markup werden, und "javascript:alert(1)" wird
    nie verlinkt (nur http/https matcht _URL_RE).

    Rueckgabe ist ein markupsafe.Markup-Objekt -- Jinja2 escaped es beim
    Rendern NICHT erneut (kein zusaetzliches |safe im Template noetig).
    Leer/None -> leeres Markup.
    """
    if not text:
        return Markup("")
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return Markup("")

    escaped = str(escape(normalized))
    linked = _URL_RE.sub(_make_link, escaped)

    paragraphs = [p for p in re.split(r"\n{2,}", linked) if p.strip()]
    html = "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)
    return Markup(html)


def is_safe_http_url(url: str | None) -> bool:
    """True nur fuer nicht-leere http(s)-URLs mit Host.

    Genutzt beim Speichern von Department.info_link (siehe
    app/routers/departments.py, app/routers/ausbilder.py) -- ein leerer
    String ist dort ein erlaubter Sonderfall ("kein Link") und wird vom
    Aufrufer VOR dieser Pruefung abgefangen, nicht hier als "sicher"
    durchgewunken.
    """
    if not url:
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)
