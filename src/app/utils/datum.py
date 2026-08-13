"""Gemeinsamer Datums-Parser fuer Formulareingaben (TEIL 3: deutsches
Datumsformat).

Hintergrund: <input type="date"> zeigt sein Eingabeformat je nach
BROWSER-Sprache (nicht nach lang="de" des Dokuments) -- ein englischer
Browser zeigt MM/DD/YYYY, was schon zu einem echten Datenfehler gefuehrt hat
(1. September wurde als 9. Januar gespeichert). Die nativen Datumsfelder
wurden daher durch ein sichtbares Textfeld im Format TT.MM.JJJJ ersetzt (s.
templates/_partials/datum_feld.html) -- mit einem Kalender-Knopf daneben, der
weiterhin die native Datumsauswahl nutzt.

Serverseitig muessen deshalb BEIDE Formate akzeptiert werden:
  - "TT.MM.JJJJ"  -- das neue Textfeld.
  - "JJJJ-MM-TT"  -- ISO, falls doch ein natives Feld sendet (Fallback ohne
    JS) oder ein alter Link/Test dieses Format weiter nutzt.

parse_datum() ist die EINZIGE Stelle, die diese Fallunterscheidung trifft --
alle Routen mit einem Datumsfeld nutzen sie, statt das Parsen jeweils selbst
nachzubauen. Rein defensiv: liefert bei fehlender/kaputter Eingabe IMMER None
statt eine Exception zu werfen (der Aufrufer entscheidet, wie er das in eine
Fehlermeldung/HTTP 400 uebersetzt) -- nie ein 500er.
"""
import re
from datetime import date

_DE_RE = re.compile(r"^(?P<tag>\d{1,2})\.(?P<monat>\d{1,2})\.(?P<jahr>\d{4})$")
_ISO_RE = re.compile(r"^(?P<jahr>\d{4})-(?P<monat>\d{1,2})-(?P<tag>\d{1,2})$")


def parse_datum(wert: str | None) -> date | None:
    """Parst 'TT.MM.JJJJ' ODER 'JJJJ-MM-TT' zu einem date.

    None bei fehlender/ungueltiger Eingabe -- auch bei kalendarisch
    unmoeglichen Werten wie "32.01.2024" oder "2024-13-01" (date(...) wirft
    dafuer ValueError, das hier abgefangen wird).
    """
    wert = (wert or "").strip()
    if not wert:
        return None
    m = _DE_RE.match(wert) or _ISO_RE.match(wert)
    if not m:
        return None
    try:
        return date(int(m.group("jahr")), int(m.group("monat")), int(m.group("tag")))
    except ValueError:
        return None
