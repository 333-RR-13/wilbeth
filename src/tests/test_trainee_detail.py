"""Tests fuer die Trainee-Detailseite."""
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


def _schoolyear(session: Session) -> None:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.commit()


def test_detail_with_assignments(client, session):
    _schoolyear(session)
    cp = Department(code="CP", name="Cloud Platform", kategorie=DepartmentKategorie.ITO)
    session.add(cp)
    t = Trainee(vorname="Felix", nachname="Fischer", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    session.add(Assignment(trainee_id=t.id, schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=cp.id, source=AssignmentSource.MANUAL))
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Fischer" in r.text
    assert "Felix" in r.text
    assert "Lehrjahr 2025-2026" in r.text
    assert "CP" in r.text


def test_detail_empty_state(client, session):
    _schoolyear(session)
    t = Trainee(vorname="Greta", nachname="Greiner", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Noch keine Einsätze" in r.text


def test_detail_conflict_highlight(client, session):
    _schoolyear(session)
    klasse = TraineeClass(name="FIAE 2. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    cp = Department(code="CP", name="Cloud Platform", kategorie=DepartmentKategorie.ITO)
    session.add_all([klasse, cp])
    session.flush()

    # Schulwoche KW41/2025 fuer die Klasse
    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=SY)
    session.add(plan)
    session.flush()
    session.add(SchoolPlanWeek(plan_id=plan.id, kw=41, jahr=2025, typ=SchoolWeekTyp.BERUFSSCHULE))

    t = Trainee(vorname="Hannah", nachname="Huber", rolle=TraineeRolle.AZUBI, klasse_id=klasse.id)
    session.add(t)
    session.flush()
    # ABTEILUNG in einer Schulwoche -> SCHUL_KONFLIKT
    session.add(Assignment(trainee_id=t.id, schoolyear_id=SY, kw=41, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=cp.id, source=AssignmentSource.MANUAL))
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "row-conflict" in r.text


def test_list_links_to_detail(client, session):
    _schoolyear(session)
    t = Trainee(vorname="Ingo", nachname="Imhof", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()

    r = client.get("/trainees/")
    assert r.status_code == 200
    assert f'href="/trainees/{t.id}"' in r.text
    assert 'id="trainee-search"' in r.text  # Suchfeld vorhanden
