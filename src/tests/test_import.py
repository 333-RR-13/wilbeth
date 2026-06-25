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
  (16) Matrix-Format: Jahreswechsel KW-Mapping korrekt
  (17) Matrix-Format: Namensabgleich mit und ohne Komma, Klammerzusatz
  (18) Matrix-Format: Code-Mapping Abteilung/BS/U/Uni/leer
  (19) Matrix-Format: Legende/Leerzeile wird still uebersprungen
  (20) Matrix-Format: unbekannter Code → ErrorRow
  (21) Matrix-Format: unbekannter Name (Zeile mit Codes) → ErrorRow
  (22) _looks_like_matrix / parse_assignments_auto: korrekte Erkennung
  (23) apply_assignments schreibt Matrix-Ergebnisse mit source=IMPORT, ueberspringt Vorhandene
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
    parse_assignments_auto,
    parse_assignments_matrix,
    parse_school_weeks,
    _looks_like_matrix,
    _split_rows,
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


# ── Matrix-Import Fixtures ────────────────────────────────────────────────────

# Lehrjahr KW36/2025 – KW35/2026 (deckt Jahreswechsel ab)
SY_MATRIX = "2025-2026-matrix"


def _make_matrix_year(session: Session) -> Schoolyear:
    y = Schoolyear(id=SY_MATRIX, start_kw=36, start_year=2025, end_kw=35, end_year=2026)
    session.add(y)
    session.flush()
    return y


def _make_matrix_setup(session: Session) -> dict:
    """Schuljahr + Departments AI/DWP/CS + Trainees Meier,Marvin und Mustermann,Max."""
    _make_matrix_year(session)

    dept_ai = Department(code="AI", name="AI Dept", kategorie=DepartmentKategorie.ITO)
    dept_dwp = Department(code="DWP", name="DWP Dept", kategorie=DepartmentKategorie.ITO)
    dept_cs = Department(code="CS", name="CS Dept", kategorie=DepartmentKategorie.ITO)
    session.add_all([dept_ai, dept_dwp, dept_cs])
    session.flush()

    t1 = Trainee(vorname="Marvin", nachname="Meier", rolle=TraineeRolle.AZUBI)
    t2 = Trainee(vorname="Max", nachname="Mustermann", rolle=TraineeRolle.AZUBI)
    session.add_all([t1, t2])
    session.commit()

    return {
        "dept_ai": dept_ai, "dept_dwp": dept_dwp, "dept_cs": dept_cs,
        "t1": t1, "t2": t2,
    }


# ── 16: Jahreswechsel-KW-Mapping ─────────────────────────────────────────────

def test_matrix_kw_jahreswechsel(session: Session):
    """KW36/KW52 liegen in 2025, KW1 liegt in 2026 (Jahreswechsel korrekt)."""
    _make_matrix_setup(session)

    text = (
        "Woche\t\tKW36\tKW37\tKW52\tKW1\n"
        "Azubi / Studi\n"
        "Meier, Marvin (2.LJ FISI)\t\tAI\tDWP\tAI\tCS\n"
    )
    result = parse_assignments_matrix(text, session, SY_MATRIX)

    assert len(result.errors) == 0, [e.reason for e in result.errors]
    assert len(result.valid) == 4

    kw_jahr = {(pa.kw, pa.jahr) for pa in result.valid}
    assert (36, 2025) in kw_jahr
    assert (37, 2025) in kw_jahr
    assert (52, 2025) in kw_jahr
    assert (1, 2026) in kw_jahr


# ── 17: Namensabgleich mit/ohne Komma, Klammerzusatz ─────────────────────────

def test_matrix_name_matching_with_and_without_comma(session: Session):
    """'Meier, Marvin (2.LJ FISI)' und 'Mustermann Max (2. LJ FISI)' matchen beide."""
    _make_matrix_setup(session)

    text = (
        "Woche\t\tKW36\tKW37\n"
        "Meier, Marvin (2.LJ FISI)\t\tAI\tDWP\n"
        "Mustermann Max (2. LJ FISI)\t\tCS\tAI\n"
    )
    result = parse_assignments_matrix(text, session, SY_MATRIX)

    assert len(result.errors) == 0, [e.reason for e in result.errors]
    assert len(result.valid) == 4

    names = {pa.trainee_name for pa in result.valid}
    assert "Meier, Marvin" in names
    assert "Mustermann, Max" in names


# ── 18: Code-Mapping Abteilung/BS/U/Uni/leer ─────────────────────────────────

def test_matrix_code_mapping(session: Session):
    """DWP/AI/CS → ABTEILUNG+dept; BS → BERUFSSCHULE; U → URLAUB; Uni → UNI; leer → kein Eintrag."""
    _make_matrix_setup(session)

    # KW36=DWP, KW37=BS, KW38=U, KW39=Uni, KW40=leer, KW41=AI
    text = (
        "Woche\t\tKW36\tKW37\tKW38\tKW39\tKW40\tKW41\n"
        "Meier, Marvin (2.LJ FISI)\t\tDWP\tBS\tU\tUni\t\tAI\n"
    )
    result = parse_assignments_matrix(text, session, SY_MATRIX)

    assert len(result.errors) == 0, [e.reason for e in result.errors]
    # KW40 ist leer -> kein Eintrag
    assert len(result.valid) == 5

    typ_map = {pa.kw: pa.typ for pa in result.valid}
    assert typ_map[36] == AssignmentTyp.ABTEILUNG
    assert typ_map[37] == AssignmentTyp.BERUFSSCHULE
    assert typ_map[38] == AssignmentTyp.URLAUB
    assert typ_map[39] == AssignmentTyp.UNI
    assert typ_map[41] == AssignmentTyp.ABTEILUNG

    dept_map_result = {pa.kw: pa.abteilung_code for pa in result.valid}
    assert dept_map_result[36] == "DWP"
    assert dept_map_result[41] == "AI"
    # Nicht-Abteilung hat keine abteilung_id
    assert next(pa.abteilung_id for pa in result.valid if pa.kw == 37) is None


# ── 19: Legende/Leerzeile wird still uebersprungen ───────────────────────────

def test_matrix_legend_rows_silently_skipped(session: Session):
    """Zeile ohne KW-Werte (z.B. Legende 'Produkte ITO\tAnsprechpartner') erzeugt keine ErrorRow."""
    _make_matrix_setup(session)

    text = (
        "Woche\t\tKW36\tKW37\n"
        "Meier, Marvin (2.LJ FISI)\t\tAI\tDWP\n"
        "Produkte ITO\tAnsprechpartner\t\t\n"
        "Irgendwas\t\t\t\n"
    )
    result = parse_assignments_matrix(text, session, SY_MATRIX)

    assert len(result.errors) == 0, [e.reason for e in result.errors]
    assert len(result.valid) == 2  # nur Meier KW36+KW37


# ── 20: unbekannter Code → ErrorRow ──────────────────────────────────────────

def test_matrix_unknown_code_is_error(session: Session):
    """Unbekannter Code (weder Typ noch Abteilung) → ErrorRow."""
    _make_matrix_setup(session)

    # KW36 unbekannter Code, KW37 gültiger Code (damit Kopfzeile ≥2 KW-Spalten hat)
    text = (
        "Woche\t\tKW36\tKW37\n"
        "Meier, Marvin (2.LJ FISI)\t\tXXXUNBEKANNT\tAI\n"
    )
    result = parse_assignments_matrix(text, session, SY_MATRIX)

    # KW37=AI ist gültig; KW36=XXXUNBEKANNT → ErrorRow
    assert len(result.valid) == 1
    assert len(result.errors) == 1
    assert "XXXUNBEKANNT" in result.errors[0].reason


# ── 21: unbekannter Name (Zeile mit Codes) → ErrorRow ────────────────────────

def test_matrix_unknown_name_with_codes_is_error(session: Session):
    """Zeile mit KW-Codes aber unbekanntem Namen → ErrorRow (kein stilles Ueberspringen)."""
    _make_matrix_setup(session)

    text = (
        "Woche\t\tKW36\tKW37\n"
        "Unbekannt Niemand (3.LJ)\t\tAI\tDWP\n"
    )
    result = parse_assignments_matrix(text, session, SY_MATRIX)

    assert len(result.valid) == 0
    assert len(result.errors) == 1
    assert "nicht gefunden" in result.errors[0].reason


# ── 22: _looks_like_matrix / parse_assignments_auto Erkennung ────────────────

def test_looks_like_matrix_true_for_kw_header():
    """_looks_like_matrix: True wenn ≥3 KW-Zellen in ersten 3 Zeilen."""
    rows = _split_rows("Woche\t\tKW36\tKW37\tKW52\tKW1\nMeier\t\tAI\tBS\tU\tDWP")
    assert _looks_like_matrix(rows) is True


def test_looks_like_matrix_false_for_langformat():
    """_looks_like_matrix: False fuer Langformat (Azubi|KW|Jahr|Abteilung)."""
    rows = _split_rows("Azubi\tKW\tJahr\tAbteilung\nMuster, Anna\t10\t2026\tITO-SD")
    assert _looks_like_matrix(rows) is False


def test_parse_assignments_auto_dispatches_matrix(session: Session):
    """parse_assignments_auto waehlt Matrix bei KW-Kopfzeile."""
    _make_matrix_setup(session)

    text = (
        "Woche\t\tKW36\tKW37\n"
        "Meier, Marvin (2.LJ FISI)\t\tAI\tDWP\n"
    )
    result = parse_assignments_auto(text, session, SY_MATRIX)
    assert len(result.valid) == 2
    assert len(result.errors) == 0


def test_parse_assignments_auto_dispatches_langformat(session: Session):
    """parse_assignments_auto waehlt Langformat bei Azubi|KW|Jahr|Abteilung."""
    _make_year(session)
    _make_trainee(session, "Muster", "Anna")
    _make_dept(session, "ITO-SD")
    session.commit()

    text = "Muster, Anna\t10\t2026\tITO-SD"
    result = parse_assignments_auto(text, session, SY)
    assert len(result.valid) == 1
    assert len(result.errors) == 0


# ── 23: apply_assignments mit Matrix-Ergebnissen ─────────────────────────────

def test_apply_assignments_matrix_source_import_skips_existing(session: Session):
    """apply_assignments schreibt Matrix-Einsaetze mit source=IMPORT, ueberspringt Vorhandene."""
    ids = _make_matrix_setup(session)
    t1 = ids["t1"]
    dept_ai = ids["dept_ai"]

    # Einen Einsatz vorab anlegen (KW36)
    session.add(Assignment(
        trainee_id=t1.id,
        schoolyear_id=SY_MATRIX,
        kw=36,
        jahr=2025,
        typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=dept_ai.id,
        source=AssignmentSource.MANUAL,
    ))
    session.commit()

    text = (
        "Woche\t\tKW36\tKW37\n"
        "Meier, Marvin (2.LJ FISI)\t\tAI\tDWP\n"
    )
    parsed = parse_assignments_matrix(text, session, SY_MATRIX).valid
    written, skipped = apply_assignments(session, SY_MATRIX, parsed)

    # KW36 vorhanden → uebersprungen; KW37 neu
    assert len(written) == 1
    assert len(skipped) == 1

    session.expire_all()
    assignments = session.exec(
        select(Assignment).where(Assignment.trainee_id == t1.id)
    ).all()
    # Nur 2 Eintraege: der manuelle KW36 + der neue KW37
    assert len(assignments) == 2

    kw37 = next(a for a in assignments if a.kw == 37)
    assert kw37.source == AssignmentSource.IMPORT
    assert kw37.typ == AssignmentTyp.ABTEILUNG

    kw36 = next(a for a in assignments if a.kw == 36)
    assert kw36.source == AssignmentSource.MANUAL  # unveraendert


# ── Neue Tests: Headerloser Matrix-Import ─────────────────────────────────────

# (b) _looks_like_matrix bei ≥8 Spalten ohne KW-Zelle

def test_looks_like_matrix_true_for_wide_rows_no_kw_header():
    """_looks_like_matrix: True wenn breiteste Zeile ≥8 Spalten, auch ohne KW-Zellen."""
    # 9 Spalten, keine einzige KW-Zelle
    rows = _split_rows("Meier, Marvin (2.LJ)\t\tAI\tBS\tU\tDWP\tCS\tAI\tBS")
    assert _looks_like_matrix(rows) is True


def test_looks_like_matrix_false_for_narrow_no_kw_header():
    """_looks_like_matrix: False wenn ≤5 Spalten und keine KW-Zellen (Langformat)."""
    rows = _split_rows("Muster, Anna\t10\t2026\tITO-SD")
    assert _looks_like_matrix(rows) is False


# (a) Headerloser Matrix-Import mit start_kw=36, Jahreswechsel korrekt

def test_matrix_headerless_jahreswechsel(session: Session):
    """Headerlose Matrix mit start_kw=36: KW36/2025..KW1/2026 korrekt zugeordnet."""
    _make_matrix_setup(session)

    # Spalte 0 = Name, Spalte 1 = leer (Trennspalte), Spalten 2-4 = Codes
    # KW36/2025, KW37/2025, KW52/2025 – wir prüfen Jahreswechsel mit KW1
    # Lehrjahr SY_MATRIX: start_kw=36/2025, end_kw=35/2026
    # Wir geben 3 Codes ab KW36 -> KW36,KW37,KW38 (alles 2025)
    # Und dann testen wir explizit mit 18 Codes um KW52->KW1 zu erreichen
    # (KW36+16 = KW52; KW36+17 = KW1/2026)
    codes_row = ["Meier, Marvin (2.LJ FISI)", ""] + ["AI"] * 17 + ["CS"]
    text = "\t".join(codes_row)
    result = parse_assignments_matrix(text, session, SY_MATRIX, start_kw=36)

    assert len(result.errors) == 0, [e.reason for e in result.errors]
    # 18 Eintraege (KW36..KW52 = 17, + KW1 = 18; aber KW52 2025 existiert auch)
    kw_jahre = {(pa.kw, pa.jahr) for pa in result.valid}
    # KW36/2025 muss drin sein
    assert (36, 2025) in kw_jahre
    # KW1/2026 muss drin sein (Jahreswechsel)
    assert (1, 2026) in kw_jahre
    # KW52/2025 muss drin sein
    assert (52, 2025) in kw_jahre


# (c) Regression: MIT Kopfzeile weiterhin korrekt, start_kw wird ignoriert

def test_matrix_with_header_start_kw_ignored(session: Session):
    """Mit KW-Kopfzeile: start_kw wird ignoriert, Kopfzeile bestimmt Mapping."""
    _make_matrix_setup(session)

    text = (
        "Woche\t\tKW36\tKW37\n"
        "Meier, Marvin (2.LJ FISI)\t\tAI\tDWP\n"
    )
    # start_kw=1 würde falsches Mapping ergeben wenn es nicht ignoriert wird
    result = parse_assignments_matrix(text, session, SY_MATRIX, start_kw=1)

    assert len(result.errors) == 0, [e.reason for e in result.errors]
    assert len(result.valid) == 2

    kw_jahre = {(pa.kw, pa.jahr) for pa in result.valid}
    # Kopfzeile sagt KW36/2025 und KW37/2025 – start_kw=1 darf nichts ändern
    assert (36, 2025) in kw_jahre
    assert (37, 2025) in kw_jahre


# (d) start_kw=None nutzt schoolyear.start_kw als Default

def test_matrix_headerless_default_start_kw(session: Session):
    """Headerlose Matrix mit start_kw=None: schoolyear.start_kw (36) wird als Default genutzt."""
    _make_matrix_setup(session)

    # 3 Codes: werden KW36, KW37, KW38 zugeordnet (start=36 per Default)
    text = "Meier, Marvin (2.LJ FISI)\t\tAI\tDWP\tCS"
    result = parse_assignments_matrix(text, session, SY_MATRIX, start_kw=None)

    assert len(result.errors) == 0, [e.reason for e in result.errors]
    assert len(result.valid) == 3

    kw_jahre = {(pa.kw, pa.jahr) for pa in result.valid}
    assert (36, 2025) in kw_jahre
    assert (37, 2025) in kw_jahre
    assert (38, 2025) in kw_jahre


# (e) Spalten über Lehrjahr-Ende → ErrorRow, kein Crash

def test_matrix_headerless_columns_exceed_schoolyear(session: Session):
    """Headerlose Matrix mit mehr Spalten als Lehrjahr-Wochen → ErrorRow, kein Crash."""
    _make_matrix_setup(session)

    # Lehrjahr SY_MATRIX hat 52 Wochen (KW36/2025..KW35/2026).
    # start_kw=35 (letzte Woche), aber wir geben 5 Codes → 4 überschreiten Ende
    text = "Meier, Marvin (2.LJ FISI)\t\tAI\tDWP\tCS\tAI\tDWP"
    result = parse_assignments_matrix(text, session, SY_MATRIX, start_kw=35)

    # Genau 1 ErrorRow "Spalte ueberschreitet Lehrjahr-Ende"
    exceed_errors = [e for e in result.errors if "ueberschreitet" in e.reason]
    assert len(exceed_errors) == 1

    # Nur die erste Spalte (KW35/2026) landet in valid
    assert len(result.valid) == 1
    assert result.valid[0].kw == 35
    assert result.valid[0].jahr == 2026


# parse_assignments_auto mit headerloser Matrix (start_kw durchgereicht)

def test_parse_assignments_auto_headerless_matrix(session: Session):
    """parse_assignments_auto: Headerlose breite Matrix wird erkannt und mit start_kw verarbeitet."""
    _make_matrix_setup(session)

    # 9 Spalten → _looks_like_matrix gibt True (≥8)
    text = "Meier, Marvin (2.LJ FISI)\t\tAI\tDWP\tCS\tAI\tBS\tU\tDWP"
    result = parse_assignments_auto(text, session, SY_MATRIX, start_kw=36)

    assert len(result.errors) == 0, [e.reason for e in result.errors]
    # 7 Codes (2 Leerspalten übersprungen nach Auswertung: c_start=2, c_end=8 → 7 Spalten)
    assert len(result.valid) == 7
