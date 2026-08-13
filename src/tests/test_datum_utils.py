"""Tests fuer app/utils/datum.parse_datum -- TEIL 3 (deutsches Datumsformat).

Der gemeinsame Parser muss BEIDE Formate akzeptieren ("TT.MM.JJJJ" aus dem
neuen Textfeld, "JJJJ-MM-TT" aus alten Links/Tests bzw. einem nativen
Fallback-Feld) und bei jeder Art von Muell None liefern -- NIE eine
Exception (Router uebersetzen None in ein HTTP 400, s. jeweilige Router-Tests)."""
from datetime import date

from app.utils.datum import parse_datum


# ── Gueltige Eingaben, beide Formate ────────────────────────────────────────

def test_deutsches_format_wird_geparst():
    assert parse_datum("01.09.2024") == date(2024, 9, 1)


def test_iso_format_wird_weiterhin_geparst():
    assert parse_datum("2024-09-01") == date(2024, 9, 1)


def test_deutsches_format_ohne_fuehrende_null_wird_geparst():
    assert parse_datum("1.9.2024") == date(2024, 9, 1)


def test_1_september_wird_nicht_als_9_januar_gelesen():
    """Der urspruengliche Datenfehler: ein englischsprachiges input[type=date]
    interpretierte 01.09 als 9. Januar statt 1. September. Das deutsche
    Format ist eindeutig TT.MM.JJJJ -- keine Verwechslungsgefahr mehr."""
    ergebnis = parse_datum("01.09.2024")
    assert ergebnis == date(2024, 9, 1)
    assert ergebnis != date(2024, 1, 9)


# ── Ungueltige Eingaben -> None (nie eine Exception) ────────────────────────

def test_leerer_string_ergibt_none():
    assert parse_datum("") is None


def test_none_ergibt_none():
    assert parse_datum(None) is None


def test_nur_leerzeichen_ergibt_none():
    assert parse_datum("   ") is None


def test_freitext_ergibt_none():
    assert parse_datum("nicht-datum") is None


def test_ungueltiger_tag_ergibt_none():
    assert parse_datum("32.01.2024") is None


def test_ungueltiger_monat_iso_ergibt_none():
    assert parse_datum("2024-13-01") is None


def test_ungueltiger_monat_deutsch_ergibt_none():
    assert parse_datum("01.13.2024") is None


def test_29_februar_nicht_schaltjahr_ergibt_none():
    assert parse_datum("29.02.2023") is None


def test_29_februar_schaltjahr_wird_akzeptiert():
    assert parse_datum("29.02.2024") == date(2024, 2, 29)
