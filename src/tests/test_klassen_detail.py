"""Tests fuer Klassen-Bearbeiten-Formular mit integrierter Mitglieder-Zuweisung."""
from sqlmodel import Session, select

from app.models import Trainee, TraineeClass, TraineeRolle, UnterrichtsTyp
from seed.seed import seed_classes


# ── Fixtures ─────────────────────────────────────────────────────

def _setup_class_with_trainees(session: Session) -> dict:
    """Creates one class with two trainees already assigned."""
    cls = TraineeClass(
        name="FISI 2. LJ",
        berufsschule="Josef-Durler Rastatt",
        unterrichts_typ=UnterrichtsTyp.BLOCK_FEST,
    )
    session.add(cls)
    session.flush()

    t1 = Trainee(vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI, klasse_id=cls.id)
    t2 = Trainee(vorname="Beate", nachname="Bergmann", rolle=TraineeRolle.AZUBI, klasse_id=cls.id)
    t3 = Trainee(vorname="Carolin", nachname="Clasen", rolle=TraineeRolle.AZUBI, klasse_id=None)
    session.add_all([t1, t2, t3])
    session.commit()

    return {"cls_id": cls.id, "t1_id": t1.id, "t2_id": t2.id, "t3_id": t3.id}


# ── GET /klassen/{id}/bearbeiten ──────────────────────────────────

def test_edit_form_returns_200_and_shows_member_checklist(client, session):
    """GET /klassen/{id}/bearbeiten returns 200 and shows member checkboxes."""
    ids = _setup_class_with_trainees(session)
    r = client.get(f"/klassen/{ids['cls_id']}/bearbeiten")
    assert r.status_code == 200
    assert 'name="mitglied"' in r.text
    assert "Altmann" in r.text
    assert "Bergmann" in r.text
    assert "Clasen" in r.text


# ── POST /klassen/{id} with member assignment ─────────────────────

def test_post_edit_assigns_and_removes_members(client, session):
    """POST /klassen/{id} assigns checked trainees and clears unchecked ones."""
    ids = _setup_class_with_trainees(session)
    cls_id = ids["cls_id"]

    # t1 stays checked, t2 is unchecked (leaves class), t3 is newly added
    r = client.post(
        f"/klassen/{cls_id}",
        data={
            "name": "FISI 2. LJ",
            "berufsschule": "Josef-Durler Rastatt",
            "unterrichts_typ": "BLOCK_FEST",
            "mitglied": [str(ids["t1_id"]), str(ids["t3_id"])],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/klassen/" in r.headers["location"]

    session.expire_all()
    t1 = session.get(Trainee, ids["t1_id"])
    t2 = session.get(Trainee, ids["t2_id"])
    t3 = session.get(Trainee, ids["t3_id"])

    assert t1.klasse_id == cls_id       # was checked, stays in class
    assert t2.klasse_id is None         # was in class but unchecked -> removed
    assert t3.klasse_id == cls_id       # newly checked -> added


# ── Seed: 1st-year classes ────────────────────────────────────────

def test_seed_classes_includes_first_year(session):
    """seed_classes() creates FISI 1. LJ and FIAE 1. LJ entries."""
    classes = seed_classes(session)
    assert "FISI 1. LJ" in classes
    assert "FIAE 1. LJ" in classes
    assert classes["FISI 1. LJ"].unterrichts_typ == UnterrichtsTyp.BLOCK_FEST
    assert classes["FIAE 1. LJ"].unterrichts_typ == UnterrichtsTyp.BLOCK_FEST
