"""Unit-Test fuer die reine Klassifizierungsfunktion der Migration 0018
(Betreuer.funktionen aus dem bisherigen Einzelwert funktion).

Die eigentliche Migration wird NICHT hier, sondern manuell gegen eine
Offline-PG-DDL-Ausgabe und eine echte SQLite-Kopie geprueft (siehe
Projektauftrag "Migration real pruefen"), analog test_migration_0016_berufe.py.
"""
import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0018_funktionen.py"
)
_spec = importlib.util.spec_from_file_location("migration_0018_funktionen", _MODULE_PATH)
_migration_0018 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration_0018)

_funktionen_aus_einzelwert = _migration_0018._funktionen_aus_einzelwert


# ── _funktionen_aus_einzelwert ────────────────────────────────────────────

def test_bekannte_funktion_wird_einzelliste():
    assert _funktionen_aus_einzelwert("HR") == ["HR"]
    assert _funktionen_aus_einzelwert("TECHNISCH") == ["TECHNISCH"]
    assert _funktionen_aus_einzelwert("EINSATZPLANUNG") == ["EINSATZPLANUNG"]
    assert _funktionen_aus_einzelwert("SONSTIGES") == ["SONSTIGES"]


def test_leerer_wert_wird_leere_liste():
    assert _funktionen_aus_einzelwert("") == []
    assert _funktionen_aus_einzelwert(None) == []


def test_unbekannter_wert_wird_leere_liste():
    """KEIN Fallback auf SONSTIGES -- eine leere Funktionsliste ist
    ausdruecklich erlaubt (reiner Abteilungs-Ausbilder, s.
    app/models/betreuer.py)."""
    assert _funktionen_aus_einzelwert("IRGENDWAS") == []
