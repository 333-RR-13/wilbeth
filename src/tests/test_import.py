"""Tests fuer den Bulk-Import (services/importer.py + routers/imports.py).

Abgedeckte Faelle:
  (1)  Parsing Tab-getrennt (Excel-Copy)
  (2)  Parsing Semikolon-getrennt (deutsches Excel-CSV)
  (3)  Parsing Komma-getrennt
  (4)  Kopfzeile wird erkannt und uebersprungen
  (5)  Leere Zeilen werden ignoriert
  (6)  Schulplan-Import: Wochen werden angelegt
  (7)  Schulplan-Import: vorhandene Woche wird uebersprungen (kein Duplikat)
  (8)  Schulplan-Import: nach Schreiben wird sync_class aufgerufen (AUTO-Eintrag)
  (9)  Einsatz-Import: Azubi + Abteilung werden gematcht, source=IMPORT
  (10) Einsatz-Import: unbekannter Azubi → Fehlerzeile, kein DB-Write
  (11) Einsatz-Import: unbekannte Abteilung → Fehlerzeile, kein DB-Write
  (12) Einsatz-Import: bestehender Einsatz → uebersprungen + gemeldet
  (13) Vorschau-Endpunkt schreibt nichts in die DB
  (14) Typ-Kuerzel: BS→BERUFSSCHULE, HS→UNI
  (15) Einsatz-Import ohne Typ-Spalte: Default ABTEILUNG
"""

import pytest
from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    DepartmentKategorie,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.services.importer import (
    apply_assignments,
    apply_school_weeks,
    parse_assignments,
    parse_school_weeks,
)

# ── Konstanten ────────────────────────────────────────────────────────────────

SY = "2025-2026"
KW = 10
JAHR = 2026


# ── Fixture-Helfer ────────────────────────────────────────────────────────────

def _make_year(session: Session) -> Schoolyear:
    y = Schoolyear(id=SY, start_kw=1, start_year=2026, end_kw=52, end_year=2026)
    session.add(y)
    session.flush()
    return y


def _make_class_with_plan(session: Session) -> dict:
    _make_year(session)
    klasse = TraineeClass(
        name="FISI Import",
        berufsschule="JD Schule",
        unterrichts_typ=UnterrichtsTyp.BLOCK_FEST,
    )
    session.add(klasse)
    session.flush()

    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=SY)
    session.add(plan)
    session.flush()

    t1 = Trainee(vorname="Max", nachname="Mustermann", rolle=TraineeRolle.AZUBI, klasse_id=klasse.id)
    session.add(t1)
    session.commit()

    return {"klasse_id": klasse.id, "plan_id": plan.id, "trainee_id": t1.id}


def _make_dept(session: Session, code: str = "ITO-SD") -> Department:
    d = Department(
        code=code,
        name=f"Abt {code}",
        kategorie=DepartmentKategorie.ITO,
    )
    session.add(d)
    session.flush()
    return d


def _make_trainee(session: Session, nachname: str = "Muster", vorname: str = "Anna") -> Trainee:
    t = Trainee(vorname=vorname, nachname=nachname, rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    return t


# ── 1-5: Parsing-Tests (kein DB-Zugriff) ─────────────────────────────────────

def test_parse_school_weeks_tab_delimited():
    """Tab-getrennte Eingabe (Excel-Copy) wird korrekt geparst."""
    text = "10\t2026\tBS\n11\t2026\tBERUFSSCHULE\n12\t2026\tHS"
    result = parse_school_weeks(text)
    assert len(result.valid) == 3
    assert len(result.errors) == 0
    assert result.valid[0].kw == 10
    assert result.valid[0].typ == SchoolWeekTyp.BERUFSSCHULE
    assert result.valid[2].typ == SchoolWeekTyp.UNI


def test_parse_school_weeks_semicolon_delimited():
    """Semikolon-getrennte Eingabe (deutsches Excel-CSV) wird korrekt geparst."""
    text = "10;2026;BS\n11;2026;HS"
    result = parse_school_weeks(text)
    assert len(result.valid) == 2
    assert len(result.errors) == 0
    assert result.valid[0].kw == 10
    assert result.valid[1].typ == SchoolWeekTyp.UNI


def test_parse_school_weeks_comma_delimited():
    """Komma-getrennte Eingabe wird korrekt geparst."""
    text = "10,2026,BS\n11,2026,UNI"
    result = parse_school_weeks(text)
    assert len(result.valid) == 2
    assert len(result.errors) == 0


def test_parse_school_weeks_header_skipped():
    """Kopfzeile wird erkannt und uebersprungen."""
    text = "KW\tJahr\tTyp\n10\t2026\tBS\n11\t2026\tHS"
    result = parse_school_weeks(text)
    assert len(result.valid) == 2
    assert result.valid[0].kw == 10


def test_parse_school_weeks_empty_lines_ignored():
    """Leere Zeilen werden ignoriert."""
    text = "10\t2026\tBS\n\n\n11\t2026\tHS\n"
    result = parse_school_weeks(text)
    assert len(result.valid) == 2


def test_parse_school_weeks_invalid_typ():
    """Unbekannter Typ erzeugt eine Fehlerzeile."""
    text = "10\t2026\tUNBEKANNT"
    result = parse_school_weeks(text)
    assert len(result.valid) == 0
    assert len(result.errors) == 1
    assert "Typ" in result.errors[0].reason


def test_parse_school_weeks_kw_out_of_range():
    """KW 0 ist ungueltig."""
    text = "0\t2026\tBS"
    result = parse_school_weeks(text)
    assert len(result.valid) == 0
    assert len(result.errors) == 1


def test_parse_typ_shortcuts():
    """BS → BERUFSSCHULE, HS → UNI."""
    text = "10\t2026\tBS\n11\t2026\tHS"
    result = parse_school_weeks(text)
    assert result.valid[0].typ == SchoolWeekTyp.BERUFSSCHULE
    assert result.valid[1].typ == SchoolWeekTyp.UNI


# ── 6-8: Schulplan-Import (DB) ────────────────────────────────────────────────

def test_apply_school_weeks_creates_weeks(session: Session):
    """Wochen werden korrekt in der DB angelegt."""
    ids = _make_class_with_plan(session)
    text = "10\t2026\tBS\n11\t2026\tHS"
    parsed = parse_school_weeks(text).valid
    written, skipped = apply_school_weeks(session, ids["plan_id"], parsed)

    assert len(written) == 2
    assert len(skipped) == 0

    db_weeks = session.exec(
        select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == ids["plan_id"])
    ).all()
    assert len(db_weeks) == 2
    kwjahr_pairs = {(w.kw, w.jahr) for w in db_weeks}
    assert (10, 2026) in kwjahr_pairs
    assert (11, 2026) in kwjahr_pairs


def test_apply_school_weeks_skips_existing(session: Session):
    """Bereits vorhandene Woche wird uebersprungen, kein Duplikat."""
    ids = _make_class_with_plan(session)
    # Woche vorab anlegen
    session.add(SchoolPlanWeek(plan_id=ids["plan_id"], kw=10, jahr=2026, typ=SchoolWeekTyp.BERUFSSCHULE))
    session.commit()

    text = "10\t2026\tBS\n11\t2026\tHS"
    parsed = parse_school_weeks(text).valid
    written, skipped = apply_school_weeks(session, ids["plan_id"], parsed)

    assert len(written) == 1   # nur KW 11 neu
    assert len(skipped) == 1   # KW 10 uebersprungen
    assert "KW 10" in skipped[0].reason

    db_weeks = session.exec(
        select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == ids["plan_id"])
    ).all()
    assert len(db_weeks) == 2  # keine Duplikate


def test_apply_school_weeks_triggers_sync(session: Session):
    """Nach dem Import wird sync_class aufgerufen → AUTO-Assignment fuer Trainee."""
    ids = _make_class_with_plan(session)
    text = "10\t2026\tBS"
    parsed = parse_school_weeks(text).valid
    apply_school_weeks(session, ids["plan_id"], parsed)

    auto_a = session.exec(
        select(Assignment).where(
            Assignment.trainee_id == ids["trainee_id"],
            Assignment.source == AssignmentSource.AUTO,
        )
    ).all()
    assert len(auto_a) == 1
    assert auto_a[0].typ == AssignmentTyp.BERUFSSCHULE
    assert auto_a[0].kw == 10


# ── 9-15: Einsatz-Import (DB) ─────────────────────────────────────────────────

def test_parse_assignments_matches_trainee_and_dept(session: Session):
    """Azubi + Abteilung werden korrekt gematcht."""
    _make_year(session)
    t = _make_trainee(session, "Muster", "Anna")
    d = _make_dept(session, "ITO-SD")
    session.commit()

    text = "Muster, Anna\t10\t2026\tITO-SD"
    result = parse_assignments(text, session, SY)
    assert len(result.valid) == 1
    assert len(result.errors) == 0
    assert result.valid[0].trainee_id == t.id
    assert result.valid[0].abteilung_id == d.id
    assert result.valid[0].kw == 10


def test_parse_assignments_case_insensitive(session: Session):
    """Azubi- und Abteilungs-Matching ist case-insensitive."""
    _make_year(session)
    _make_trainee(session, "Muster", "Anna")
    _make_dept(session, "ITO-SD")
    session.commit()

    text = "muster, anna\t10\t2026\tito-sd"
    result = parse_assignments(text, session, SY)
    assert len(result.valid) == 1
    assert len(result.errors) == 0


def test_parse_assignments_unknown_trainee_is_error(session: Session):
    """Unbekannter Azubi → Fehlerzeile, kein valid-Eintrag."""
    _make_year(session)
    _make_dept(session, "ITO-SD")
    session.commit()

    text = "Unbekannt, Nobody\t10\t2026\tITO-SD"
    result = parse_assignments(text, session, SY)
    assert len(result.valid) == 0
    assert len(result.errors) == 1
    assert "nicht gefunden" in result.errors[0].reason


def test_parse_assignments_unknown_dept_is_error(session: Session):
    """Unbekannte Abteilung → Fehlerzeile, kein valid-Eintrag."""
    _make_year(session)
    _make_trainee(session, "Muster", "Anna")
    session.commit()

    text = "Muster, Anna\t10\t2026\tXXX-UNBEKANNT"
    result = parse_assignments(text, session, SY)
    assert len(result.valid) == 0
    assert len(result.errors) == 1
    assert "nicht gefunden" in result.errors[0].reason


def test_apply_assignments_sets_source_import(session: Session):
    """Importierte Einsaetze erhalten source=IMPORT."""
    _make_year(session)
    t = _make_trainee(session, "Muster", "Anna")
    d = _make_dept(session, "ITO-SD")
    session.commit()

    text = "Muster, Anna\t10\t2026\tITO-SD"
    parsed = parse_assignments(text, session, SY).valid
    written, skipped = apply_assignments(session, SY, parsed)

    assert len(written) == 1
    assert len(skipped) == 0

    a = session.exec(
        select(Assignment).where(Assignment.trainee_id == t.id)
    ).first()
    assert a is not None
    assert a.source == AssignmentSource.IMPORT
    assert a.typ == AssignmentTyp.ABTEILUNG
    assert a.abteilung_id == d.id


def test_apply_assignments_skips_existing(session: Session):
    """Bestehender Einsatz (gleiche trainee_id+kw+jahr) wird uebersprungen."""
    _make_year(session)
    t = _make_trainee(session, "Muster", "Anna")
    d = _make_dept(session, "ITO-SD")
    session.commit()

    # Einsatz vorab anlegen
    session.add(Assignment(
        trainee_id=t.id,
        schoolyear_id=SY,
        kw=10,
        jahr=2026,
        typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=d.id,
        source=AssignmentSource.MANUAL,
    ))
    session.commit()

    text = "Muster, Anna\t10\t2026\tITO-SD"
    parsed = parse_assignments(text, session, SY).valid
    written, skipped = apply_assignments(session, SY, parsed)

    assert len(written) == 0
    assert len(skipped) == 1
    assert "uebersprungen" in skipped[0].reason

    # Originaler Eintrag unveraendert (MANUAL, nicht IMPORT)
    a = session.exec(
        select(Assignment).where(Assignment.trainee_id == t.id)
    ).first()
    assert a.source == AssignmentSource.MANUAL


def test_apply_assignments_no_db_write_on_error(session: Session):
    """Bei parse-Fehlern (unbekannter Azubi) wird nichts in die DB geschrieben."""
    _make_year(session)
    _make_dept(session, "ITO-SD")
    session.commit()

    text = "Unbekannt, Nobody\t10\t2026\tITO-SD"
    result = parse_assignments(text, session, SY)
    # Vorschau-Simulation: keine valid-Zeilen → apply wird nicht aufgerufen
    assert len(result.valid) == 0

    count = session.exec(select(Assignment)).all()
    assert len(count) == 0


def test_parse_assignments_default_typ_abteilung(session: Session):
    """Fehlende Typ-Spalte → Default ABTEILUNG."""
    _make_year(session)
    _make_trainee(session, "Muster", "Anna")
    _make_dept(session, "ITO-SD")
    session.commit()

    text = "Muster, Anna\t10\t2026\tITO-SD"  # keine 5. Spalte
    result = parse_assignments(text, session, SY)
    assert len(result.valid) == 1
    assert result.valid[0].typ == AssignmentTyp.ABTEILUNG


def test_parse_assignments_non_abteilung_typ(session: Session):
    """Typ URLAUB/FREI/BS/HS korrekt gemappt; Abteilung dann nicht noetig."""
    _make_year(session)
    _make_trainee(session, "Muster", "Anna")
    session.commit()

    text = "Muster, Anna\t10\t2026\t\tURLAUB"
    result = parse_assignments(text, session, SY)
    assert len(result.valid) == 1
    assert result.valid[0].typ == AssignmentTyp.URLAUB
    assert result.valid[0].abteilung_id is None


# ── Endpunkt-Tests (HTMX-Partials) ───────────────────────────────────────────

def test_schulplan_import_preview_no_db_write(client, session: Session):
    """POST /imports/schulplan/{id}/preview schreibt nichts in die DB."""
    ids = _make_class_with_plan(session)
    plan_id = ids["plan_id"]

    r = client.post(
        f"/imports/schulplan/{plan_id}/preview",
        data={"raw_text": "10\t2026\tBS\n11\t2026\tHS"},
    )
    assert r.status_code == 200

    # Kein DB-Write
    weeks = session.exec(
        select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan_id)
    ).all()
    assert len(weeks) == 0


def test_einsaetze_import_preview_no_db_write(client, session: Session):
    """POST /imports/einsaetze/preview schreibt nichts in die DB."""
    _make_year(session)
    t = _make_trainee(session, "Muster", "Anna")
    _make_dept(session, "ITO-SD")
    session.commit()

    r = client.post(
        "/imports/einsaetze/preview",
        data={
            "schoolyear_id": SY,
            "raw_text": "Muster, Anna\t10\t2026\tITO-SD",
        },
    )
    assert r.status_code == 200

    # Kein DB-Write
    assignments = session.exec(
        select(Assignment).where(Assignment.trainee_id == t.id)
    ).all()
    assert len(assignments) == 0


def test_schulplan_import_dialog_endpoint(client, session: Session):
    """GET /imports/schulplan/{id}/dialog liefert 200 mit Formular-HTML."""
    ids = _make_class_with_plan(session)
    r = client.get(f"/imports/schulplan/{ids['plan_id']}/dialog")
    assert r.status_code == 200
    assert "importieren" in r.text.lower()


def test_einsaetze_import_dialog_endpoint(client, session: Session):
    """GET /imports/einsaetze/dialog liefert 200."""
    r = client.get(f"/imports/einsaetze/dialog?schoolyear_id={SY}")
    assert r.status_code == 200
    assert "importieren" in r.text.lower()


def test_schulplan_import_apply_redirect(client, session: Session):
    """POST /imports/schulplan/{id}/apply schreibt Wochen und redirectet."""
    ids = _make_class_with_plan(session)
    plan_id = ids["plan_id"]

    r = client.post(
        f"/imports/schulplan/{plan_id}/apply",
        data={"raw_text": "10\t2026\tBS"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert f"/schulplaene/{plan_id}" in r.headers["location"]

    weeks = session.exec(
        select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan_id)
    ).all()
    assert len(weeks) == 1


def test_einsaetze_import_apply_redirect(client, session: Session):
    """POST /imports/einsaetze/apply schreibt Einsaetze und redirectet."""
    _make_year(session)
    t = _make_trainee(session, "Muster", "Anna")
    _make_dept(session, "ITO-SD")
    session.commit()

    r = client.post(
        "/imports/einsaetze/apply",
        data={
            "schoolyear_id": SY,
            "raw_text": "Muster, Anna\t10\t2026\tITO-SD",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/overview" in r.headers["location"]

    session.expire_all()
    a = session.exec(
        select(Assignment).where(Assignment.trainee_id == t.id)
    ).first()
    assert a is not None
    assert a.source == AssignmentSource.IMPORT
