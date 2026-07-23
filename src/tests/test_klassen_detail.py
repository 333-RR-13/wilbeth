"""Tests fuer die Klassen-Bearbeiten-Seite: reine ANZEIGE der berechneten
Mitglieder (ueber klasse_fuer), keine Mitglieder-Pflege mehr auf der
Klassen-Seite - Ausnahmen werden ausschliesslich am Trainee gepflegt."""
from sqlmodel import Session, select

from app.models import (
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeRolle,
    UnterrichtsTyp,
)
from seed.seed import seed_classes

SY = "2025-2026"


# ── Fixtures ─────────────────────────────────────────────────────

def _add_year(session: Session, sy_id: str = SY, start_year: int = 2025) -> Schoolyear:
    y = Schoolyear(id=sy_id, start_kw=36, start_year=start_year, end_kw=35, end_year=start_year + 1)
    session.add(y)
    session.flush()
    return y


def _setup_class_with_trainees(session: Session) -> dict:
    """Eine Klasse mit einem ueber den Anker (trainee.klasse_id) zugeordneten
    Trainee und einem per Override (TraineeClassMembership) zugeordneten Trainee."""
    _add_year(session)
    cls = TraineeClass(
        name="FISI 2. LJ",
        berufsschule="Josef-Durler Rastatt",
        unterrichts_typ=UnterrichtsTyp.BLOCK_FEST,
    )
    session.add(cls)
    session.flush()

    t1 = Trainee(vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI, klasse_id=cls.id)
    t2 = Trainee(vorname="Beate", nachname="Bergmann", rolle=TraineeRolle.AZUBI, klasse_id=None)
    t3 = Trainee(vorname="Carolin", nachname="Clasen", rolle=TraineeRolle.AZUBI, klasse_id=None)
    session.add_all([t1, t2, t3])
    session.commit()

    # t2 gehoert per Override zu dieser Klasse (kein Anker-Bezug)
    session.add(TraineeClassMembership(trainee_id=t2.id, schoolyear_id=SY, klasse_id=cls.id))
    session.commit()

    return {"cls_id": cls.id, "t1_id": t1.id, "t2_id": t2.id, "t3_id": t3.id}


# ── GET /klassen/{id}/bearbeiten ──────────────────────────────────

def test_edit_form_shows_computed_members_without_checkbox_pflege(client, session):
    """GET /klassen/{id}/bearbeiten zeigt die berechneten Mitglieder (Anker + Override),
    aber KEINE Mitglieder-Checkbox-Pflege mehr."""
    ids = _setup_class_with_trainees(session)
    r = client.get(f"/klassen/{ids['cls_id']}/bearbeiten?year_id={SY}")
    assert r.status_code == 200
    assert 'name="mitglied"' not in r.text
    assert "Altmann" in r.text          # Anker-Mitglied
    assert "Bergmann" in r.text         # Override-Mitglied
    assert "Clasen" not in r.text       # kein Mitglied dieser Klasse


def test_override_member_shows_ausnahme_badge(client, session):
    """Der per Override zugeordnete Trainee bekommt das 'Ausnahme'-Badge,
    der ueber den Anker zugeordnete nicht."""
    ids = _setup_class_with_trainees(session)
    r = client.get(f"/klassen/{ids['cls_id']}/bearbeiten?year_id={SY}")
    assert r.status_code == 200

    zeile_bergmann = r.text.split("Bergmann")[1].split("</div>")[0]
    assert "Ausnahme" in zeile_bergmann

    zeile_altmann = r.text.split("Altmann")[1].split("</div>")[0]
    assert "Ausnahme" not in zeile_altmann


# ── POST /klassen/{id}: keine Mitglieder-Pflege mehr ──────────────

def test_post_edit_no_longer_writes_memberships(client, session):
    """POST /klassen/{id} ohne 'mitglied'-Feld speichert nur die Klassen-Stammdaten;
    bestehende Memberships bleiben unangetastet, keine neuen werden angelegt."""
    ids = _setup_class_with_trainees(session)
    cls_id = ids["cls_id"]

    vor = session.exec(select(TraineeClassMembership)).all()
    anzahl_vor = len(vor)

    r = client.post(
        f"/klassen/{cls_id}",
        data={
            "name": "FISI 2. LJ geaendert",
            "berufsschule": "Josef-Durler Rastatt",
            "unterrichts_typ": "BLOCK_FEST",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/klassen/" in r.headers["location"]

    session.expire_all()
    cls = session.get(TraineeClass, cls_id)
    assert cls.name == "FISI 2. LJ geaendert"

    nach = session.exec(select(TraineeClassMembership)).all()
    assert len(nach) == anzahl_vor

    # Der ueber den Anker zugeordnete Trainee bleibt unveraendert zugeordnet
    t1 = session.get(Trainee, ids["t1_id"])
    assert t1.klasse_id == cls_id


# ── Seed: 1st-year classes ────────────────────────────────────────

def test_seed_classes_includes_first_year(session):
    """seed_classes() creates FISI 1. LJ and FIAE 1. LJ entries."""
    classes = seed_classes(session)
    assert "FISI 1. LJ" in classes
    assert "FIAE 1. LJ" in classes
    assert classes["FISI 1. LJ"].unterrichts_typ == UnterrichtsTyp.BLOCK_FEST
    assert classes["FIAE 1. LJ"].unterrichts_typ == UnterrichtsTyp.BLOCK_FEST
