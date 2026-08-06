"""Tests fuer die Pflege von TraineeClass.bereich (Klassen-Formular) und
Department.zielgruppe (Abteilungs-Formular) -- TEIL B."""
from sqlmodel import Session, select

from app.models import Department, TraineeClass, UnterrichtsTyp

SY = "2025-2026"


# ── Klassen-Formular: bereich ─────────────────────────────────────────────────

def test_klasse_create_stores_bereich_kaufmaennisch(client, session: Session):
    r = client.post("/klassen/", data={
        "name": "Bürokaufleute 1. LJ",
        "berufsschule": "HHS",
        "unterrichts_typ": "TAGE_FEST",
        "bereich": "KAUFMAENNISCH",
    }, follow_redirects=False)
    assert r.status_code == 303

    cls = session.exec(select(TraineeClass).where(TraineeClass.name == "Bürokaufleute 1. LJ")).first()
    assert cls is not None
    assert cls.bereich == "KAUFMAENNISCH"


def test_klasse_create_default_bereich_is_it(client, session: Session):
    """Ohne explizites Feld greift der Formular-/Feld-Default 'IT'."""
    r = client.post("/klassen/", data={
        "name": "FISI 1. LJ",
        "berufsschule": "HHS",
        "unterrichts_typ": "BLOCK_FEST",
    }, follow_redirects=False)
    assert r.status_code == 303

    cls = session.exec(select(TraineeClass).where(TraineeClass.name == "FISI 1. LJ")).first()
    assert cls is not None
    assert cls.bereich == "IT"


def test_klasse_update_changes_bereich(client, session: Session):
    cls = TraineeClass(name="DHBW Sonderklasse", berufsschule="DHBW",
                        unterrichts_typ=UnterrichtsTyp.DH_PHASEN, bereich="IT")
    session.add(cls)
    session.commit()

    r = client.post(f"/klassen/{cls.id}", data={
        "name": "DHBW Sonderklasse",
        "berufsschule": "DHBW",
        "unterrichts_typ": "DH_PHASEN",
        "bereich": "KAUFMAENNISCH",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated = session.get(TraineeClass, cls.id)
    assert updated.bereich == "KAUFMAENNISCH"


def test_klasse_bearbeiten_form_shows_bereich_select(client, session: Session):
    cls = TraineeClass(name="FIAE 2. LJ", berufsschule="HHS",
                        unterrichts_typ=UnterrichtsTyp.BLOCK_FEST, bereich="IT")
    session.add(cls)
    session.commit()

    r = client.get(f"/klassen/{cls.id}/bearbeiten")
    assert r.status_code == 200
    assert 'name="bereich"' in r.text
    assert 'value="IT" selected' in r.text


def test_klassen_liste_zeigt_bereich_badge(client, session: Session):
    cls = TraineeClass(name="Bürokaufleute 2. LJ", berufsschule="HHS",
                        unterrichts_typ=UnterrichtsTyp.TAGE_FEST, bereich="KAUFMAENNISCH")
    session.add(cls)
    session.commit()

    r = client.get("/klassen/")
    assert r.status_code == 200
    assert "Kaufmännisch" in r.text


# ── Abteilungs-Formular: zielgruppe ───────────────────────────────────────────

def test_department_create_stores_zielgruppe_it(client, session: Session):
    r = client.post("/abteilungen/", data={
        "code": "CPX",
        "name": "Cloud Platform X",
        "zielgruppe": "IT",
    }, follow_redirects=False)
    assert r.status_code == 303

    dept = session.exec(select(Department).where(Department.code == "CPX")).first()
    assert dept is not None
    assert dept.zielgruppe == "IT"


def test_department_create_default_zielgruppe_is_beide(client, session: Session):
    r = client.post("/abteilungen/", data={
        "code": "DEF2",
        "name": "Default Zielgruppe",
    }, follow_redirects=False)
    assert r.status_code == 303

    dept = session.exec(select(Department).where(Department.code == "DEF2")).first()
    assert dept is not None
    assert dept.zielgruppe == "BEIDE"


def test_department_update_changes_zielgruppe(client, session: Session):
    dept = Department(code="BKX", name="Buchhaltung X", zielgruppe="BEIDE")
    session.add(dept)
    session.commit()

    r = client.post(f"/abteilungen/{dept.id}", data={
        "code": "BKX",
        "name": "Buchhaltung X",
        "zielgruppe": "KAUFMAENNISCH",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated = session.get(Department, dept.id)
    assert updated.zielgruppe == "KAUFMAENNISCH"


def test_department_bearbeiten_form_shows_zielgruppe_select(client, session: Session):
    dept = Department(code="CPY", name="Cloud Platform Y", zielgruppe="IT")
    session.add(dept)
    session.commit()

    r = client.get(f"/abteilungen/{dept.id}/bearbeiten")
    assert r.status_code == 200
    assert 'name="zielgruppe"' in r.text


def test_abteilungen_liste_zeigt_zielgruppe(client, session: Session):
    dept = Department(code="BKZ", name="Buchhaltung Z", zielgruppe="KAUFMAENNISCH")
    session.add(dept)
    session.commit()

    r = client.get("/abteilungen/")
    assert r.status_code == 200
    assert "Nur kaufmännisch" in r.text
