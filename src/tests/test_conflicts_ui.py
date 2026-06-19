"""Tests fuer die Konflikt-Erklaerung: describe_conflict, Panel-Route, Zell-Dialog."""
from sqlmodel import Session

from app.models import (
    Assignment,
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
from app.services.conflict_checker import Conflict, ConflictKind, describe_conflict

SY = "2025-2026"


# ── describe_conflict (Unit) ─────────────────────────────────────

def test_describe_schul_konflikt():
    c = Conflict(ConflictKind.SCHUL_KONFLIKT, trainee_id=1, kw=10, jahr=2026,
                 message="x", dept_id=5, trainee_ids=(1,))
    d = describe_conflict(c, {1: "Mustermann, Max"}, {})
    assert d["title"] == "Schul-Konflikt"
    assert d["who"] == "Mustermann, Max"
    assert d["when"] == "KW 10/2026"
    assert "Berufsschule" in d["why"]


def test_describe_ferien_konflikt():
    c = Conflict(ConflictKind.FERIEN_KONFLIKT, trainee_id=2, kw=44, jahr=2025,
                 message="x", holiday_name="Herbstferien", trainee_ids=(2,))
    d = describe_conflict(c, {2: "Schmidt, Anna"}, {})
    assert d["title"] == "Ferien-Konflikt"
    assert "Herbstferien" in d["why"]


def test_describe_doppelbelegung():
    dept = Department(id=7, code="CP", name="Cloud Platform", kategorie=DepartmentKategorie.ITO)
    c = Conflict(ConflictKind.DOPPELBELEGUNG, trainee_id=None, kw=15, jahr=2026,
                 message="x", dept_id=7, trainee_ids=(1, 2))
    d = describe_conflict(c, {1: "Mustermann, Max", 2: "Schmidt, Anna"}, {7: dept})
    assert d["title"] == "Doppelbelegung"
    assert "CP" in d["why"]
    assert "Mustermann, Max" in d["why"]
    assert "Schmidt, Anna" in d["why"]
    assert "keine Mehrfachbelegung" in d["why"]


# ── Setup-Helfer fuer Route-Tests ────────────────────────────────

def _schul_konflikt(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    klasse = TraineeClass(name="FISI 2. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    cp = Department(code="CP", name="Cloud Platform", kategorie=DepartmentKategorie.ITO)
    session.add_all([klasse, cp])
    session.flush()
    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=SY)
    session.add(plan)
    session.flush()
    session.add(SchoolPlanWeek(plan_id=plan.id, kw=41, jahr=2025, typ=SchoolWeekTyp.BERUFSSCHULE))
    t = Trainee(vorname="Max", nachname="Mustermann", rolle=TraineeRolle.AZUBI, klasse_id=klasse.id)
    session.add(t)
    session.flush()
    session.add(Assignment(trainee_id=t.id, schoolyear_id=SY, kw=41, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=cp.id))
    session.commit()
    return {"trainee": t.id, "cp": cp.id}


# ── Panel-Route ──────────────────────────────────────────────────

def test_conflict_panel_route(client, session):
    _schul_konflikt(session)
    r = client.get("/overview/konflikte", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Schul-Konflikt" in r.text
    assert "Berufsschule" in r.text          # die Begruendung
    assert "Mustermann" in r.text            # wer betroffen ist
    assert "KW 41/2025" in r.text


def test_conflict_panel_empty(client, session):
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.commit()
    r = client.get("/overview/konflikte", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Keine Konflikte" in r.text


def test_overview_has_why_button(client, session):
    _schul_konflikt(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "conflict-why-btn" in r.text
    assert "/overview/konflikte" in r.text


# ── Zell-Dialog mit Begründung ───────────────────────────────────

def test_cell_edit_shows_conflict(client, session):
    ids = _schul_konflikt(session)
    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": ids["trainee"], "kw": 41, "jahr": 2025, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    assert "cell-conflict-box" in r.text
    assert "Schul-Konflikt" in r.text
    assert "Berufsschule" in r.text


def test_cell_edit_no_conflict_no_box(client, session):
    ids = _schul_konflikt(session)
    # KW 40 ist keine Schulwoche -> kein Konflikt, keine Box
    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": ids["trainee"], "kw": 40, "jahr": 2025, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    assert "cell-conflict-box" not in r.text


def test_cell_edit_shows_doppelbelegung(client, session):
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    cp = Department(code="CP", name="Cloud Platform", kategorie=DepartmentKategorie.ITO,
                    erlaubt_mehrfachbelegung=False)
    session.add(cp)
    t1 = Trainee(vorname="Max", nachname="Mustermann", rolle=TraineeRolle.AZUBI)
    t2 = Trainee(vorname="Anna", nachname="Schmidt", rolle=TraineeRolle.AZUBI)
    session.add_all([t1, t2])
    session.flush()
    for t in (t1, t2):
        session.add(Assignment(trainee_id=t.id, schoolyear_id=SY, kw=15, jahr=2026,
                               typ=AssignmentTyp.ABTEILUNG, abteilung_id=cp.id))
    session.commit()

    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": t1.id, "kw": 15, "jahr": 2026, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    assert "Doppelbelegung" in r.text
    assert "Schmidt, Anna" in r.text   # der/die andere Beteiligte
