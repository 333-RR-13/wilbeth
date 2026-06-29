"""Tests fuer app/services/dept_history.py und zugehoerige UI-Integration."""
from sqlmodel import Session

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    Schoolyear,
    Trainee,
    TraineeRolle,
)
from app.services.dept_history import visited_department_ids, visited_departments

SY = "2025-2026"
SY2 = "2024-2025"


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _setup(session: Session) -> dict:
    """Legt Grunddaten an: zwei Schuljahre, zwei Abteilungen, einen Trainee."""
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.add(Schoolyear(id=SY2, start_kw=36, start_year=2024, end_kw=35, end_year=2025))
    cp = Department(code="CP", name="Cloud Platform")
    dp = Department(code="DP", name="Data Platform")
    ba = Department(code="BA", name="Business Apps")
    session.add_all([cp, dp, ba])
    t = Trainee(vorname="Lena", nachname="Lehmann", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "cp": cp.id, "dp": dp.id, "ba": ba.id}


# ── Unit-Tests fuer visited_department_ids ────────────────────────────────────

def test_visited_ids_empty(session: Session):
    """Ohne Einsaetze ist die Menge leer."""
    ids = _setup(session)
    result = visited_department_ids(session, ids["trainee"])
    assert result == set()


def test_visited_ids_single(session: Session):
    """Ein ABTEILUNG-Einsatz liefert dessen ID."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()
    result = visited_department_ids(session, ids["trainee"])
    assert result == {ids["cp"]}


def test_visited_ids_multiple_depts(session: Session):
    """Mehrere verschiedene Abteilungen werden alle erfasst."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY2, kw=2, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["dp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()
    result = visited_department_ids(session, ids["trainee"])
    assert result == {ids["cp"], ids["dp"]}


def test_visited_ids_distinct(session: Session):
    """Dieselbe Abteilung in zwei Schuljahren zaehlt nur einmal."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY2, kw=2, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()
    result = visited_department_ids(session, ids["trainee"])
    assert result == {ids["cp"]}
    assert len(result) == 1


def test_visited_ids_ignores_non_abteilung(session: Session):
    """URLAUB, BERUFSSCHULE etc. werden nicht gezaehlt."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.URLAUB, abteilung_id=None,
        source=AssignmentSource.MANUAL,
    ))
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY2, kw=5, jahr=2025,
        typ=AssignmentTyp.BERUFSSCHULE, abteilung_id=None,
        source=AssignmentSource.MANUAL,
    ))
    session.commit()
    result = visited_department_ids(session, ids["trainee"])
    assert result == set()


def test_visited_ids_exclude_kw_jahr(session: Session):
    """exclude_kw/exclude_jahr blendet genau diese Zelle aus."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY2, kw=2, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["dp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()

    # Ohne Ausschluss: beide sichtbar
    assert visited_department_ids(session, ids["trainee"]) == {ids["cp"], ids["dp"]}

    # KW40/2025 ausschliessen -> nur dp bleibt
    result = visited_department_ids(session, ids["trainee"], exclude_kw=40, exclude_jahr=2025)
    assert result == {ids["dp"]}

    # KW2/2025 ausschliessen -> nur cp bleibt
    result = visited_department_ids(session, ids["trainee"], exclude_kw=2, exclude_jahr=2025)
    assert result == {ids["cp"]}


def test_visited_ids_exclude_only_matching_cell(session: Session):
    """Ausschluss trifft nur exakte KW+Jahr-Kombination, nicht andere."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()
    # Falsche KW -> cp bleibt sichtbar
    result = visited_department_ids(session, ids["trainee"], exclude_kw=41, exclude_jahr=2025)
    assert result == {ids["cp"]}
    # Falsche Jahr -> cp bleibt sichtbar
    result = visited_department_ids(session, ids["trainee"], exclude_kw=40, exclude_jahr=2024)
    assert result == {ids["cp"]}


# ── Unit-Tests fuer visited_departments ──────────────────────────────────────

def test_visited_departments_empty(session: Session):
    ids = _setup(session)
    result = visited_departments(session, ids["trainee"])
    assert result == []


def test_visited_departments_ordered_by_code(session: Session):
    """Ergebnis ist nach Code sortiert."""
    ids = _setup(session)
    # dp (D) vor cp (C) falsch - aber CP kommt vor DP alphabetisch
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["dp"],
        source=AssignmentSource.MANUAL,
    ))
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY2, kw=2, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()
    result = visited_departments(session, ids["trainee"])
    assert [d.code for d in result] == ["CP", "DP"]


# ── Integrations-Tests: /overview zeigt Chips ────────────────────────────────

def test_overview_shows_visited_chip(client, session: Session):
    """Eine Abteilung, in der der Trainee war, erscheint als Chip in der Matrix."""
    ids = _setup(session)
    # CP-Einsatz in einem anderen Schuljahr anlegen
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY2, kw=2, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # CP-Code als visited-col-chip in der rechten Spalte sichtbar
    assert "visited-col-chip" in r.text
    assert ">CP<" in r.text


def test_overview_no_chip_when_no_history(client, session: Session):
    """Ohne ABTEILUNG-Einsaetze werden keine Chips angezeigt."""
    ids = _setup(session)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "visited-col-chip" not in r.text


def test_overview_shows_chip_same_year(client, session: Session):
    """Chips erscheinen auch, wenn der Einsatz im selben Schuljahr ist."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "visited-col-chip" in r.text
    assert ">CP<" in r.text


# ── Integrations-Tests: cell-edit bettet visited_dept_ids ein ────────────────

def test_cell_edit_embeds_visited_ids(client, session: Session):
    """cell-edit liefert die besuchten Abteilungs-IDs im JS-Array."""
    ids = _setup(session)
    # CP-Einsatz in einer anderen KW (nicht KW41)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": ids["trainee"], "kw": 41, "jahr": 2025, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    # Die besuchte CP-ID muss im JS-Array auftauchen
    assert str(ids["cp"]) in r.text
    assert "visitedIds" in r.text


def test_cell_edit_excludes_current_cell(client, session: Session):
    """Bei cell-edit fuer KW40 wird CP aus KW40 ausgeblendet (exclude_kw=40)."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": ids["trainee"], "kw": 40, "jahr": 2025, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    # CP soll NICHT in visitedIds sein, weil es die aktuelle Zelle ist
    import json, re
    m = re.search(r'var visitedIds\s*=\s*(\[[^\]]*\])', r.text)
    assert m is not None, "visitedIds JS-Variable nicht gefunden"
    visited = json.loads(m.group(1))
    assert ids["cp"] not in visited


def test_cell_edit_warning_markup_present(client, session: Session):
    """Das Warning-Element ist im DOM vorhanden."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
        source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": ids["trainee"], "kw": 41, "jahr": 2025, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    assert "cell-repeat-warn" in r.text
    assert "war bereits in dieser Abteilung" in r.text
