"""Tests fuer den Inline-Cell-Edit der Matrix (cell-edit / cell-save / cell-delete)."""
from sqlmodel import Session, select

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
    TraineeRolle,
    UnterrichtsTyp,
)

SY = "2025-2026"


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    cp = Department(code="CP", name="Cloud Platform")
    session.add(cp)
    t = Trainee(vorname="Jonas", nachname="Jäger", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "cp": cp.id}


def test_cell_edit_form(client, session):
    ids = _setup(session)
    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": ids["trainee"], "kw": 40, "jahr": 2025, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    assert 'name="typ"' in r.text
    assert "Jäger" in r.text


def test_cell_save_creates(client, session):
    ids = _setup(session)
    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 40, "jahr": 2025,
        "typ": "ABTEILUNG", "abteilung_id": ids["cp"], "notiz": "",
    })
    assert r.status_code == 200
    # Antwort enthaelt die Zelle und den OOB-Konfliktzaehler
    assert f'id="cell-{ids["trainee"]}-40-2025"' in r.text
    assert 'id="conflict-counter"' in r.text
    assert 'hx-swap-oob="true"' in r.text

    a = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).first()
    assert a is not None
    assert a.typ == AssignmentTyp.ABTEILUNG
    assert a.abteilung_id == ids["cp"]


def test_cell_save_updates_existing(client, session):
    ids = _setup(session)
    session.add(Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
                           source=AssignmentSource.MANUAL))
    session.commit()

    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 40, "jahr": 2025,
        "typ": "URLAUB", "abteilung_id": "", "notiz": "Urlaub genehmigt",
    })
    assert r.status_code == 200

    rows = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).all()
    assert len(rows) == 1  # kein Duplikat
    assert rows[0].typ == AssignmentTyp.URLAUB
    assert rows[0].abteilung_id is None  # Abteilung geleert bei Nicht-ABTEILUNG


def test_cell_delete(client, session):
    ids = _setup(session)
    a = Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
                   typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
                   source=AssignmentSource.MANUAL)
    session.add(a)
    session.commit()
    aid = a.id

    r = client.post("/einsaetze/cell-delete", data={
        "assignment_id": aid, "trainee_id": ids["trainee"], "schoolyear_id": SY,
        "kw": 40, "jahr": 2025,
    })
    assert r.status_code == 200
    assert session.get(Assignment, aid) is None
    # Leere Zelle wird zurueckgegeben
    assert f'id="cell-{ids["trainee"]}-40-2025"' in r.text


def test_cell_edit_form_shows_bestaetigung_select(client, session):
    ids = _setup(session)
    session.add(Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
                           bestaetigung="bestaetigt",
                           source=AssignmentSource.MANUAL))
    session.commit()

    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": ids["trainee"], "kw": 40, "jahr": 2025, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    assert 'name="bestaetigung"' in r.text
    assert 'value="bestaetigt" selected' in r.text


def test_cell_save_persists_bestaetigung(client, session):
    ids = _setup(session)
    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 40, "jahr": 2025,
        "typ": "ABTEILUNG", "abteilung_id": ids["cp"], "notiz": "",
        "bestaetigung": "bestaetigt",
    })
    assert r.status_code == 200

    a = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).first()
    assert a is not None
    assert a.bestaetigung == "bestaetigt"

    # Marker-Klasse erscheint in der OOB-gerenderten Zelle
    assert "mc-confirm-bestaetigt" in r.text


def test_cell_save_defaults_bestaetigung_offen_when_not_sent(client, session):
    ids = _setup(session)
    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 40, "jahr": 2025,
        "typ": "ABTEILUNG", "abteilung_id": ids["cp"], "notiz": "",
    })
    assert r.status_code == 200

    a = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).first()
    assert a.bestaetigung == "offen"
    assert "mc-confirm-offen" in r.text


def test_cell_save_keeps_existing_bestaetigung_when_not_sent(client, session):
    ids = _setup(session)
    session.add(Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
                           bestaetigung="abgelehnt",
                           source=AssignmentSource.MANUAL))
    session.commit()

    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 40, "jahr": 2025,
        "typ": "ABTEILUNG", "abteilung_id": ids["cp"], "notiz": "geändert",
    })
    assert r.status_code == 200

    a = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).first()
    assert a.bestaetigung == "abgelehnt"


def test_cell_save_conflict_counter(client, session):
    ids = _setup(session)
    # Schulwoche KW41/2025 fuer eine Klasse, Trainee dieser Klasse zuordnen
    klasse = TraineeClass(name="FIAE 2. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(klasse)
    session.flush()
    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=SY)
    session.add(plan)
    session.flush()
    session.add(SchoolPlanWeek(plan_id=plan.id, kw=41, jahr=2025, typ=SchoolWeekTyp.BERUFSSCHULE))
    t = session.get(Trainee, ids["trainee"])
    t.klasse_id = klasse.id
    session.commit()

    # ABTEILUNG in Schulwoche -> Konflikt -> Zaehler zeigt 1
    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 41, "jahr": 2025,
        "typ": "ABTEILUNG", "abteilung_id": ids["cp"], "notiz": "",
    })
    assert r.status_code == 200
    assert "1 Konflikt" in r.text
