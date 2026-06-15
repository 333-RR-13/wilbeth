"""Tests fuer abgeleitete BS/UNI-Chips aus dem Klassen-Schulplan.

Prueft, dass in Overview- und Azubi-Matrizen eine Schulplan-Woche als
cell-auto-Chip erscheint, wenn kein expliziter Einsatz fuer die Zelle
vorhanden ist — und dass ein echter Einsatz den abgeleiteten Chip
verdraengt.
"""
from sqlmodel import Session

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

SY = "2025-2026"
TOKEN = "chip-test-token-xyz"
# KW innerhalb des Lehrjahrs (start_kw=36/2025, end_kw=35/2026)
SCHOOL_KW = 41
SCHOOL_JAHR = 2025


def _setup(session: Session, school_week_typ: SchoolWeekTyp = SchoolWeekTyp.BERUFSSCHULE) -> dict:
    """Lehrjahr + FISI-Klasse + Schulplan mit einer Schulwoche + Azubi ohne Einsaetze."""
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    cp = Department(code="CP", name="Cloud Platform", kategorie=DepartmentKategorie.ITO)
    session.add(cp)

    klasse = TraineeClass(name="FISI 2. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(klasse)
    session.flush()

    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=SY)
    session.add(plan)
    session.flush()

    session.add(SchoolPlanWeek(plan_id=plan.id, kw=SCHOOL_KW, jahr=SCHOOL_JAHR, typ=school_week_typ))

    trainee = Trainee(
        vorname="Eva", nachname="Ernst", rolle=TraineeRolle.AZUBI,
        klasse_id=klasse.id, share_token=TOKEN,
    )
    session.add(trainee)
    session.flush()
    session.commit()
    return {"trainee_id": trainee.id, "klasse_id": klasse.id, "cp_id": cp.id}


# ── Admin-Uebersicht (/overview) ─────────────────────────────────

def test_overview_shows_bs_chip_without_assignment(client, session):
    """Schulplanwoche (BERUFSSCHULE) ohne Einsatz → cell-auto BS-Chip in der Matrix."""
    _setup(session, SchoolWeekTyp.BERUFSSCHULE)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "cell-auto" in r.text
    assert ">BS<" in r.text


def test_overview_shows_uni_chip_without_assignment(client, session):
    """Schulplanwoche (UNI) ohne Einsatz → cell-auto UNI-Chip in der Matrix."""
    _setup(session, SchoolWeekTyp.UNI)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "cell-auto" in r.text
    assert ">UNI<" in r.text


def test_overview_explicit_assignment_wins(client, session):
    """Expliziter BERUFSSCHULE-Einsatz verdraengt den abgeleiteten chip (kein cell-auto)."""
    ids = _setup(session, SchoolWeekTyp.BERUFSSCHULE)
    # Einsatz fuer genau dieselbe Schulwoche setzen
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY,
        kw=SCHOOL_KW, jahr=SCHOOL_JAHR,
        typ=AssignmentTyp.BERUFSSCHULE, source=AssignmentSource.MANUAL,
    ))
    session.commit()
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # Echter Chip vorhanden, kein cell-auto-Chip
    assert "cell-BERUFSSCHULE" in r.text
    assert "cell-auto" not in r.text


# ── Azubi-Sicht (/mein-plan/{token}) ────────────────────────────

def test_my_plan_shows_bs_chip_without_assignment(client, session):
    """Schulplanwoche (BERUFSSCHULE) ohne Einsatz → cell-auto BS-Chip auf Mein-Plan-Seite."""
    _setup(session, SchoolWeekTyp.BERUFSSCHULE)
    r = client.get(f"/mein-plan/{TOKEN}", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "cell-auto" in r.text
    assert ">BS<" in r.text


def test_my_class_shows_bs_chip_without_assignment(client, session):
    """Schulplanwoche (BERUFSSCHULE) ohne Einsatz → cell-auto BS-Chip auf Klassen-Seite."""
    _setup(session, SchoolWeekTyp.BERUFSSCHULE)
    r = client.get(f"/mein-plan/{TOKEN}/klasse", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "cell-auto" in r.text
    assert ">BS<" in r.text


def test_my_plan_explicit_assignment_wins(client, session):
    """Expliziter Einsatz auf Mein-Plan-Seite: kein cell-auto, echter Chip vorhanden."""
    ids = _setup(session, SchoolWeekTyp.BERUFSSCHULE)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY,
        kw=SCHOOL_KW, jahr=SCHOOL_JAHR,
        typ=AssignmentTyp.BERUFSSCHULE, source=AssignmentSource.MANUAL,
    ))
    session.commit()
    r = client.get(f"/mein-plan/{TOKEN}", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "cell-BERUFSSCHULE" in r.text
    assert "cell-auto" not in r.text
