"""Tests fuer die Trainee-Detailseite."""
from datetime import date, timedelta

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
    TraineeWish,
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


def test_wuensche_gruppiert_nach_prioritaet(client, session):
    """Wuensche erscheinen nach Prioritaet gruppiert (Muss/Sollte/Kann-
    Ueberschriften in dieser Reihenfolge), mit den Abteilungs-Kuerzeln je
    Stufe -- der Notiztext kommt darunter unter 'Notizen / Anmerkungen'."""
    _schoolyear(session)
    cp = Department(code="CP", name="Cloud Platform")
    ba = Department(code="BA", name="Business Applications")
    ai = Department(code="AI", name="Artificial Intelligence")
    session.add_all([cp, ba, ai])
    session.flush()
    t = Trainee(vorname="Wanda", nachname="Wunsch", rolle=TraineeRolle.AZUBI,
                wunsch_notiz="Bitte fair verteilen")
    session.add(t)
    session.flush()
    session.add_all([
        TraineeWish(trainee_id=t.id, department_id=cp.id, prioritaet=1),
        TraineeWish(trainee_id=t.id, department_id=ba.id, prioritaet=2),
        TraineeWish(trainee_id=t.id, department_id=ai.id, prioritaet=3),
    ])
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    muss_pos = r.text.index("Muss")
    sollte_pos = r.text.index("Sollte")
    kann_pos = r.text.index("Kann")
    cp_pos = r.text.index(">CP<")
    ba_pos = r.text.index(">BA<")
    ai_pos = r.text.index(">AI<")
    assert muss_pos < cp_pos < sollte_pos < ba_pos < kann_pos < ai_pos
    assert "Notizen / Anmerkungen" in r.text
    assert "Bitte fair verteilen" in r.text


def test_wuensche_stufen_ohne_eintraege_werden_weggelassen(client, session):
    """Prioritaetsstufen ohne Wuensche bekommen keine Ueberschrift."""
    _schoolyear(session)
    cp = Department(code="CP", name="Cloud Platform")
    session.add(cp)
    session.flush()
    t = Trainee(vorname="Erik", nachname="Einzel", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    session.add(TraineeWish(trainee_id=t.id, department_id=cp.id, prioritaet=1))
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Muss" in r.text
    assert "Sollte" not in r.text
    assert "Kann" not in r.text


def _week_offset(weeks: int) -> tuple[int, int]:
    """(kw, jahr) fuer "heute plus/minus 'weeks' Wochen" -- deterministisch
    relativ zu date.today()."""
    iso = (date.today() + timedelta(weeks=weeks)).isocalendar()
    return iso.week, iso.year


def test_wunsch_mit_vergangenem_einsatz_erscheint_unter_bereits_erfuellt(client, session):
    """Ein Wunsch, den der Trainee bereits (in der Vergangenheit) in genau
    dieser Abteilung erfuellt hat, verschwindet aus der Prioritaets-Gruppe
    und erscheint stattdessen unter "Bereits erfuellt"."""
    _schoolyear(session)
    cp = Department(code="CP", name="Cloud Platform")
    session.add(cp)
    session.flush()
    t = Trainee(vorname="Petra", nachname="Plan", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    session.add(TraineeWish(trainee_id=t.id, department_id=cp.id, prioritaet=1))
    kw, jahr = _week_offset(-8)
    session.add(Assignment(
        trainee_id=t.id, schoolyear_id=SY, kw=kw, jahr=jahr,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=cp.id, source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Bereits erfüllt" in r.text
    assert "Muss" not in r.text  # keine offene Prio-Gruppe mehr


def test_wunsch_mit_zukuenftigem_einsatz_bleibt_in_prio_gruppe(client, session):
    """Ein bereits geplanter, aber noch nicht abgeschlossener Einsatz gilt
    NICHT als erfuellt -- der Wunsch bleibt in seiner Prioritaets-Gruppe."""
    _schoolyear(session)
    cp = Department(code="CP", name="Cloud Platform")
    session.add(cp)
    session.flush()
    t = Trainee(vorname="Fritz", nachname="Future", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    session.add(TraineeWish(trainee_id=t.id, department_id=cp.id, prioritaet=1))
    kw, jahr = _week_offset(8)
    session.add(Assignment(
        trainee_id=t.id, schoolyear_id=SY, kw=kw, jahr=jahr,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=cp.id, source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Muss" in r.text
    assert ">CP<" in r.text
    assert "Bereits erfüllt" not in r.text


def test_wunsch_ohne_einsatz_bleibt_unveraendert(client, session):
    """Ein Wunsch ohne jeden Einsatz bleibt wie bisher in seiner Prio-Gruppe."""
    _schoolyear(session)
    cp = Department(code="CP", name="Cloud Platform")
    session.add(cp)
    session.flush()
    t = Trainee(vorname="Nora", nachname="Neu", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    session.add(TraineeWish(trainee_id=t.id, department_id=cp.id, prioritaet=1))
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Muss" in r.text
    assert ">CP<" in r.text
    assert "Bereits erfüllt" not in r.text


def test_list_links_to_detail(client, session):
    _schoolyear(session)
    t = Trainee(vorname="Ingo", nachname="Imhof", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()

    r = client.get("/trainees/")
    assert r.status_code == 200
    assert f'href="/trainees/{t.id}"' in r.text
    assert 'id="trainee-search"' in r.text  # Suchfeld vorhanden
