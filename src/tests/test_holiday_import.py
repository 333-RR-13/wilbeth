"""Tests fuer den Schulferien-Import (services/importer.py + routers/holidays.py).

Abgedeckte Faelle:
  (1)  parse_holidays: gueltige Tab-getrennte Zeilen
  (2)  parse_holidays: Semikolon-getrennte Zeilen
  (3)  parse_holidays: Komma-getrennte Zeilen
  (4)  parse_holidays: Kopfzeile wird erkannt und uebersprungen
  (5)  parse_holidays: leere Zeilen werden ignoriert
  (6)  parse_holidays: ungueltige KW (0) → Fehlerzeile
  (7)  parse_holidays: KW ausserhalb 1-53 → Fehlerzeile
  (8)  parse_holidays: zu wenige Spalten → Fehlerzeile
  (9)  parse_holidays: leerer Name → Fehlerzeile
  (10) apply_holidays: schreibt SchoolHoliday in die DB
  (11) apply_holidays: ueberspringt vorhandene (gleicher name+start_kw+start_year+schoolyear_id)
  (12) Preview-Endpoint schreibt nichts in die DB
  (13) Apply-Endpoint legt Ferien an und redirectet
"""

import pytest
from sqlmodel import Session, select

from app.models import SchoolHoliday, Schoolyear
from app.services.importer import (
    HolidayParseResult,
    ParsedHoliday,
    apply_holidays,
    parse_holidays,
)

# ── Konstanten ────────────────────────────────────────────────────────────────

SY = "2025-2026"


# ── Fixture-Helfer ────────────────────────────────────────────────────────────

def _make_year(session: Session) -> Schoolyear:
    y = Schoolyear(id=SY, start_kw=1, start_year=2026, end_kw=52, end_year=2026)
    session.add(y)
    session.commit()
    return y


# ── 1-3: Parsing verschiedener Trennzeichen (kein DB-Zugriff) ────────────────

def test_parse_holidays_tab_delimited():
    """Tab-getrennte Eingabe (Excel-Einfuegen) wird korrekt geparst."""
    text = "Herbstferien\t42\t2025\t43\t2025\nWeihnachtsferien\t52\t2025\t2\t2026"
    result = parse_holidays(text)
    assert len(result.valid) == 2
    assert len(result.errors) == 0
    h0 = result.valid[0]
    assert h0.name == "Herbstferien"
    assert h0.start_kw == 42
    assert h0.start_year == 2025
    assert h0.end_kw == 43
    assert h0.end_year == 2025
    h1 = result.valid[1]
    assert h1.name == "Weihnachtsferien"
    assert h1.end_kw == 2
    assert h1.end_year == 2026


def test_parse_holidays_semicolon_delimited():
    """Semikolon-getrennte Eingabe (deutsches CSV) wird korrekt geparst."""
    text = "Osterferien;14;2026;17;2026\nPfingstferien;21;2026;22;2026"
    result = parse_holidays(text)
    assert len(result.valid) == 2
    assert len(result.errors) == 0
    assert result.valid[0].name == "Osterferien"
    assert result.valid[0].start_kw == 14


def test_parse_holidays_comma_delimited():
    """Komma-getrennte Eingabe wird korrekt geparst."""
    text = "Sommerferien,27,2026,35,2026"
    result = parse_holidays(text)
    assert len(result.valid) == 1
    assert len(result.errors) == 0
    assert result.valid[0].name == "Sommerferien"
    assert result.valid[0].start_kw == 27


# ── 4: Kopfzeile wird uebersprungen ──────────────────────────────────────────

def test_parse_holidays_header_skipped():
    """Kopfzeile mit bekannten Schlagwoertern wird erkannt und uebersprungen."""
    text = "Name\tStart-KW\tStart-Jahr\tEnd-KW\tEnd-Jahr\nHerbstferien\t42\t2025\t43\t2025"
    result = parse_holidays(text)
    assert len(result.valid) == 1
    assert result.valid[0].name == "Herbstferien"


def test_parse_holidays_header_with_kw_keyword_skipped():
    """Kopfzeile mit 'KW'-Schlagwort wird uebersprungen."""
    text = "Bezeichnung\tKW-Start\tJahr-Start\tKW-Ende\tJahr-Ende\nOsterferien\t14\t2026\t17\t2026"
    result = parse_holidays(text)
    # Kopfzeile hat 'kw' im 2. Feld -> wird uebersprungen
    assert len(result.valid) == 1


# ── 5: Leere Zeilen werden ignoriert ─────────────────────────────────────────

def test_parse_holidays_empty_lines_ignored():
    """Leere Zeilen werden still uebersprungen."""
    text = "Herbstferien\t42\t2025\t43\t2025\n\n\nOsterferien\t14\t2026\t17\t2026\n"
    result = parse_holidays(text)
    assert len(result.valid) == 2
    assert len(result.errors) == 0


# ── 6-7: Ungueltige KW → Fehlerzeile ─────────────────────────────────────────

def test_parse_holidays_invalid_kw_zero():
    """KW 0 ist ungueltig → Fehlerzeile."""
    text = "Herbstferien\t0\t2025\t43\t2025"
    result = parse_holidays(text)
    assert len(result.valid) == 0
    assert len(result.errors) == 1
    assert "ausserhalb" in result.errors[0].reason or "ungueltig" in result.errors[0].reason.lower()


def test_parse_holidays_invalid_kw_54():
    """KW 54 ist ungueltig → Fehlerzeile."""
    text = "Herbstferien\t54\t2025\t43\t2025"
    result = parse_holidays(text)
    assert len(result.valid) == 0
    assert len(result.errors) == 1
    assert "54" in result.errors[0].reason


def test_parse_holidays_non_numeric_kw():
    """Nicht-numerische KW → Fehlerzeile."""
    text = "Herbstferien\tABC\t2025\t43\t2025"
    result = parse_holidays(text)
    assert len(result.valid) == 0
    assert len(result.errors) == 1


# ── 8: Zu wenige Spalten → Fehlerzeile ───────────────────────────────────────

def test_parse_holidays_too_few_columns():
    """Zeile mit weniger als 5 Spalten → Fehlerzeile."""
    text = "Herbstferien\t42\t2025"
    result = parse_holidays(text)
    assert len(result.valid) == 0
    assert len(result.errors) == 1
    assert "Spalten" in result.errors[0].reason


# ── 9: Leerer Name → Fehlerzeile ─────────────────────────────────────────────

def test_parse_holidays_empty_name():
    """Leerer Name in der ersten Spalte → Fehlerzeile."""
    text = "\t42\t2025\t43\t2025"
    result = parse_holidays(text)
    assert len(result.valid) == 0
    assert len(result.errors) == 1
    assert "Name" in result.errors[0].reason


# ── Gemischte gueltige + ungueltige Zeilen ────────────────────────────────────

def test_parse_holidays_mixed_valid_and_errors():
    """Gueltige und ungueltige Zeilen werden korrekt getrennt."""
    text = (
        "Herbstferien\t42\t2025\t43\t2025\n"   # gueltig
        "Falsch\t0\t2025\t43\t2025\n"           # KW 0 ungueltig
        "Osterferien\t14\t2026\t17\t2026\n"     # gueltig
    )
    result = parse_holidays(text)
    assert len(result.valid) == 2
    assert len(result.errors) == 1


# ── 10: apply_holidays schreibt SchoolHoliday ────────────────────────────────

def test_apply_holidays_writes_to_db(session: Session):
    """apply_holidays legt SchoolHoliday-Eintraege in der DB an."""
    _make_year(session)

    text = "Herbstferien\t42\t2025\t43\t2025\nOsterferien\t14\t2026\t17\t2026"
    parsed = parse_holidays(text).valid
    written, skipped = apply_holidays(session, SY, parsed)

    assert len(written) == 2
    assert len(skipped) == 0

    db_holidays = session.exec(
        select(SchoolHoliday).where(SchoolHoliday.schoolyear_id == SY)
    ).all()
    assert len(db_holidays) == 2

    names = {h.name for h in db_holidays}
    assert "Herbstferien" in names
    assert "Osterferien" in names

    herbst = next(h for h in db_holidays if h.name == "Herbstferien")
    assert herbst.start_kw == 42
    assert herbst.start_year == 2025
    assert herbst.end_kw == 43
    assert herbst.end_year == 2025
    assert herbst.schoolyear_id == SY


# ── 11: apply_holidays ueberspringt vorhandene Eintraege ─────────────────────

def test_apply_holidays_skips_existing(session: Session):
    """Vorhandene Ferien (gleicher name+start_kw+start_year+schoolyear_id) werden uebersprungen."""
    _make_year(session)

    # Eintrag vorab anlegen
    session.add(SchoolHoliday(
        schoolyear_id=SY,
        name="Herbstferien",
        start_kw=42,
        start_year=2025,
        end_kw=43,
        end_year=2025,
    ))
    session.commit()

    text = "Herbstferien\t42\t2025\t43\t2025\nOsterferien\t14\t2026\t17\t2026"
    parsed = parse_holidays(text).valid
    written, skipped = apply_holidays(session, SY, parsed)

    assert len(written) == 1   # nur Osterferien neu
    assert len(skipped) == 1   # Herbstferien uebersprungen
    assert "Herbstferien" in skipped[0].reason
    assert "uebersprungen" in skipped[0].reason

    db_holidays = session.exec(
        select(SchoolHoliday).where(SchoolHoliday.schoolyear_id == SY)
    ).all()
    assert len(db_holidays) == 2  # kein Duplikat


def test_apply_holidays_same_name_different_schoolyear(session: Session):
    """Gleicher Name + KW in anderem Ausbildungsjahr wird NICHT uebersprungen."""
    _make_year(session)
    sy2 = Schoolyear(id="2026-2027", start_kw=1, start_year=2027, end_kw=52, end_year=2027)
    session.add(sy2)
    session.commit()

    # Eintrag fuer SY anlegen
    session.add(SchoolHoliday(
        schoolyear_id=SY,
        name="Herbstferien",
        start_kw=42,
        start_year=2025,
        end_kw=43,
        end_year=2025,
    ))
    session.commit()

    # Gleicher Name, aber anderes Ausbildungsjahr
    parsed = parse_holidays("Herbstferien\t42\t2025\t43\t2025").valid
    written, skipped = apply_holidays(session, "2026-2027", parsed)

    assert len(written) == 1
    assert len(skipped) == 0


# ── 12: Preview-Endpoint schreibt nichts ─────────────────────────────────────

def test_holiday_import_preview_no_db_write(client, session: Session):
    """POST /schulferien/import/preview parst und rendert, schreibt NICHTS in DB."""
    _make_year(session)

    r = client.post(
        "/schulferien/import/preview",
        data={
            "schoolyear_id": SY,
            "raw_text": "Herbstferien\t42\t2025\t43\t2025",
        },
    )
    assert r.status_code == 200
    assert "Herbstferien" in r.text

    db_holidays = session.exec(
        select(SchoolHoliday).where(SchoolHoliday.schoolyear_id == SY)
    ).all()
    assert len(db_holidays) == 0


# ── 13: Apply-Endpoint legt Ferien an ────────────────────────────────────────

def test_holiday_import_apply_creates_holidays(client, session: Session):
    """POST /schulferien/import/apply schreibt Schulferien und redirectet."""
    _make_year(session)

    r = client.post(
        "/schulferien/import/apply",
        data={
            "schoolyear_id": SY,
            "raw_text": "Herbstferien\t42\t2025\t43\t2025\nOsterferien\t14\t2026\t17\t2026",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/schulferien/" in r.headers["location"]

    session.expire_all()
    db_holidays = session.exec(
        select(SchoolHoliday).where(SchoolHoliday.schoolyear_id == SY)
    ).all()
    assert len(db_holidays) == 2

    names = {h.name for h in db_holidays}
    assert "Herbstferien" in names
    assert "Osterferien" in names


def test_holiday_import_dialog_endpoint(client, session: Session):
    """GET /schulferien/import/dialog liefert 200 mit Formular-HTML."""
    _make_year(session)

    r = client.get("/schulferien/import/dialog")
    assert r.status_code == 200
    assert "importieren" in r.text.lower()
    assert "Ausbildungsjahr" in r.text
