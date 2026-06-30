"""Tests fuer die Trainee-Detailseite."""
from datetime import date

from sqlmodel import Session

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeRolle,
    UnterrichtsTyp,
)

SY = "2025-2026"


def _schoolyear(session: Session) -> Schoolyear:
    sy = Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026)
    session.add(sy)
    session.commit()
    return sy


def test_detail_with_assignments(client, session):
    _schoolyear(session)
    cp = Department(code="CP", name="Cloud Platform")
    # Einstiegsklasse = 1. LJ; Trainee ist im 2. LJ -> wird automatisch berechnet
    klasse_1lj = TraineeClass(name="FISI 1. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    klasse_2lj = TraineeClass(name="FISI 2. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add_all([cp, klasse_1lj, klasse_2lj])
    session.flush()
    # Explizit next_class_id setzen damit Berechnung greift
    klasse_1lj.next_class_id = klasse_2lj.id
    session.add(klasse_1lj)
    # Ausbildungsbeginn 2024-09-01 -> start_year=2024; SY 2025-2026 -> steps=1 -> 2. LJ
    t = Trainee(
        vorname="Felix",
        nachname="Fischer",
        rolle=TraineeRolle.AZUBI,
        klasse_id=klasse_1lj.id,
        ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(t)
    session.flush()
    session.add(Assignment(trainee_id=t.id, schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=cp.id, source=AssignmentSource.MANUAL))
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Fischer" in r.text
    assert "Felix" in r.text
    # Berechnete Klasse (2. LJ) wird angezeigt
    assert "FISI 2. LJ" in r.text
    assert "Fachinformatiker" in r.text
    assert "CP" in r.text


def test_detail_shows_static_class_without_ausbildungsbeginn(client, session):
    """Ohne ausbildungsbeginn faellt klasse_fuer auf statischen Fallback (trainee.klasse_id)."""
    _schoolyear(session)
    klasse = TraineeClass(name="FISI 2. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(klasse)
    session.flush()
    t = Trainee(vorname="Felix", nachname="Fischer", rolle=TraineeRolle.AZUBI, klasse_id=klasse.id)
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "FISI 2. LJ" in r.text
    assert "Fachinformatiker" in r.text


def test_detail_shows_membership_override(client, session):
    """Existiert eine Membership, wird deren Klasse angezeigt (Override schlaegt Berechnung)."""
    _schoolyear(session)
    klasse_1lj = TraineeClass(name="FISI 1. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    klasse_3lj = TraineeClass(name="FISI 3. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add_all([klasse_1lj, klasse_3lj])
    session.flush()
    t = Trainee(
        vorname="Wiederholer",
        nachname="Weber",
        rolle=TraineeRolle.AZUBI,
        klasse_id=klasse_1lj.id,
        ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(t)
    session.flush()
    # Override: fuer SY -> 3. LJ (statt berechnete 2. LJ)
    session.add(TraineeClassMembership(trainee_id=t.id, schoolyear_id=SY, klasse_id=klasse_3lj.id))
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "FISI 3. LJ" in r.text


def test_detail_dh_student_shows_semester_label(client, session):
    """DH-Student: Visitenkarte zeigt Semester-Label."""
    _schoolyear(session)
    klasse = TraineeClass(name="DHBW Cybersecurity 1", berufsschule="DHBW", unterrichts_typ=UnterrichtsTyp.DH_PHASEN)
    session.add(klasse)
    session.flush()
    # Ausbildungsbeginn 2024-09-01 -> start_year=2024; SY 2025-2026 -> steps=1
    # base = 2*1 = 2 -> "3./4. Semester" (halbjahr="")
    t = Trainee(
        vorname="Diana",
        nachname="Dahl",
        rolle=TraineeRolle.DH_STUDENT,
        klasse_id=klasse.id,
        ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Semester" in r.text
    assert "3." in r.text


def test_detail_azubi_has_no_semester_label(client, session):
    """AZUBI bekommt kein Semester-Label."""
    _schoolyear(session)
    klasse = TraineeClass(name="FISI 1. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(klasse)
    session.flush()
    t = Trainee(
        vorname="Anton",
        nachname="Azubi",
        rolle=TraineeRolle.AZUBI,
        klasse_id=klasse.id,
        ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    # "Semester" als eigenstaendiges Label darf nicht erscheinen
    assert "<dt>Semester</dt>" not in r.text


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
    cp = Department(code="CP", name="Cloud Platform")
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
