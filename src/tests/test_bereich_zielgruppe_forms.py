"""Tests fuer die Pflege von TraineeClass.bereich (Klassen-Formular) und
Department.erlaubte_berufe (Abteilungs-Formular, Checkbox-Liste) -- TEIL B."""
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


# ── Abteilungs-Formular: erlaubte_berufe (Checkbox-Liste) ─────────────────────

def test_department_create_stores_erlaubte_berufe(client, session: Session):
    session.add(TraineeClass(name="FISI 1. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST))
    session.commit()

    r = client.post("/abteilungen/", data={
        "code": "CPX",
        "name": "Cloud Platform X",
        "beruf": ["FISI"],
    }, follow_redirects=False)
    assert r.status_code == 303

    dept = session.exec(select(Department).where(Department.code == "CPX")).first()
    assert dept is not None
    assert dept.erlaubte_berufe == ["FISI"]


def test_department_create_default_erlaubte_berufe_ist_leer(client, session: Session):
    """Ohne Checkbox-Auswahl bleibt die Liste leer -- bedeutet ausdruecklich
    'alle Berufe erlaubt' (der bisherige Zustand zielgruppe='BEIDE')."""
    r = client.post("/abteilungen/", data={
        "code": "DEF2",
        "name": "Default Erlaubte Berufe",
    }, follow_redirects=False)
    assert r.status_code == 303

    dept = session.exec(select(Department).where(Department.code == "DEF2")).first()
    assert dept is not None
    assert dept.erlaubte_berufe == []


def test_department_update_changes_erlaubte_berufe(client, session: Session):
    session.add(TraineeClass(name="Bürokaufleute 1. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.TAGE_FEST))
    session.commit()

    dept = Department(code="BKX", name="Buchhaltung X", erlaubte_berufe=[])
    session.add(dept)
    session.commit()

    r = client.post(f"/abteilungen/{dept.id}", data={
        "code": "BKX",
        "name": "Buchhaltung X",
        "beruf": ["Bürokaufleute"],
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated = session.get(Department, dept.id)
    assert updated.erlaubte_berufe == ["Bürokaufleute"]


def test_department_update_ohne_haken_leert_erlaubte_berufe(client, session: Session):
    """Alle Haken entfernen -> zurueck auf die leere Liste (= alle erlaubt)."""
    session.add(TraineeClass(name="FISI 1. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST))
    session.commit()

    dept = Department(code="CPY", name="Cloud Platform Y", erlaubte_berufe=["FISI"])
    session.add(dept)
    session.commit()

    r = client.post(f"/abteilungen/{dept.id}", data={
        "code": "CPY",
        "name": "Cloud Platform Y",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated = session.get(Department, dept.id)
    assert updated.erlaubte_berufe == []


def test_department_bearbeiten_form_zeigt_beruf_checkboxen(client, session: Session):
    session.add(TraineeClass(name="FISI 1. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST))
    session.commit()

    dept = Department(code="CPY", name="Cloud Platform Y", erlaubte_berufe=["FISI"])
    session.add(dept)
    session.commit()

    r = client.get(f"/abteilungen/{dept.id}/bearbeiten")
    assert r.status_code == 200
    assert 'name="beruf"' in r.text
    assert 'value="FISI"' in r.text
    checkbox_tag = r.text.split('value="FISI"')[1].split(">")[0]
    assert "checked" in checkbox_tag


def test_abteilungen_liste_zeigt_erlaubte_berufe(client, session: Session):
    dept = Department(code="BKZ", name="Buchhaltung Z", erlaubte_berufe=["Bürokaufleute"])
    session.add(dept)
    session.commit()

    r = client.get("/abteilungen/")
    assert r.status_code == 200
    assert "Bürokaufleute" in r.text


def test_abteilungen_liste_zeigt_alle_bei_leerer_liste(client, session: Session):
    dept = Department(code="BEID", name="Beide Bereiche", erlaubte_berufe=[])
    session.add(dept)
    session.commit()

    r = client.get("/abteilungen/")
    assert r.status_code == 200
    zeile = r.text.split("Beide Bereiche")[1].split("</tr>")[0]
    assert "alle" in zeile
