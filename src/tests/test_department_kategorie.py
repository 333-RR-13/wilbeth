"""Tests fuer die DepartmentKategorie-Verwaltung.

Abgedeckte Faelle:
  - Kategorie anlegen (POST /abteilungen/kategorien)
  - Kategorie umbenennen (POST /abteilungen/kategorien/{id})
  - Kategorie loeschen wenn nicht in Benutzung (POST /abteilungen/kategorien/{id}/loeschen)
  - Loeschen blockiert wenn Kategorie von Abteilung genutzt wird
  - Abteilung mit kategorie_id anlegen (POST /abteilungen/)
  - Abteilung kategorie_id aendern (POST /abteilungen/{id})
  - Listenseite zeigt Kategorien-Namen statt Enum
"""
from sqlmodel import Session, select

from app.models import Department, DepartmentKategorie


# ── Kategorie anlegen ────────────────────────────────────────────────────────

def test_create_kategorie(client, session: Session):
    """POST /abteilungen/kategorien legt eine neue Kategorie an."""
    r = client.post("/abteilungen/kategorien", data={"name": "Neue Kat"}, follow_redirects=False)
    assert r.status_code == 303

    kat = session.exec(select(DepartmentKategorie).where(DepartmentKategorie.name == "Neue Kat")).first()
    assert kat is not None
    assert kat.name == "Neue Kat"


def test_create_kategorie_strips_whitespace(client, session: Session):
    """Leerzeichen am Rand werden beim Anlegen entfernt."""
    r = client.post("/abteilungen/kategorien", data={"name": "  Leerzeichen  "}, follow_redirects=False)
    assert r.status_code == 303
    kat = session.exec(select(DepartmentKategorie).where(DepartmentKategorie.name == "Leerzeichen")).first()
    assert kat is not None


def test_create_kategorie_empty_name_ignored(client, session: Session):
    """Leerer Name wird still ignoriert (kein DB-Eintrag)."""
    r = client.post("/abteilungen/kategorien", data={"name": "   "}, follow_redirects=False)
    assert r.status_code == 303
    all_kats = session.exec(select(DepartmentKategorie)).all()
    assert len(all_kats) == 0


# ── Kategorie umbenennen ─────────────────────────────────────────────────────

def test_rename_kategorie(client, session: Session):
    """POST /abteilungen/kategorien/{id} benennt eine Kategorie um."""
    kat = DepartmentKategorie(name="Alt")
    session.add(kat)
    session.commit()

    r = client.post(f"/abteilungen/kategorien/{kat.id}", data={"name": "Neu"}, follow_redirects=False)
    assert r.status_code == 303

    session.refresh(kat)
    assert kat.name == "Neu"


# ── Kategorie loeschen ───────────────────────────────────────────────────────

def test_delete_kategorie_unused(client, session: Session):
    """Ungenutzte Kategorie kann geloescht werden."""
    kat = DepartmentKategorie(name="Loeschbar")
    session.add(kat)
    session.commit()
    kat_id = kat.id

    r = client.post(f"/abteilungen/kategorien/{kat_id}/loeschen", follow_redirects=False)
    assert r.status_code == 303

    gone = session.get(DepartmentKategorie, kat_id)
    assert gone is None


def test_delete_kategorie_blocked_when_in_use(client, session: Session):
    """Loeschen einer Kategorie, die von einer Abteilung genutzt wird, wird blockiert."""
    kat = DepartmentKategorie(name="Blockiert")
    session.add(kat)
    session.flush()

    dept = Department(code="BLK", name="Blocked Dept", kategorie_id=kat.id)
    session.add(dept)
    session.commit()
    kat_id = kat.id

    r = client.post(f"/abteilungen/kategorien/{kat_id}/loeschen", follow_redirects=False)
    # Redirect mit err=inuse
    assert r.status_code == 303
    assert "err=inuse" in r.headers["location"]

    # Kategorie ist noch da
    still_there = session.get(DepartmentKategorie, kat_id)
    assert still_there is not None


# ── Abteilung mit kategorie_id anlegen / aendern ─────────────────────────────

def test_create_department_with_kategorie_id(client, session: Session):
    """POST /abteilungen/ speichert kategorie_id korrekt."""
    kat = DepartmentKategorie(name="Test Kat")
    session.add(kat)
    session.commit()

    r = client.post("/abteilungen/", data={
        "code": "TKT",
        "name": "Test Kategorie Dept",
        "kategorie_id": str(kat.id),
    }, follow_redirects=False)
    assert r.status_code == 303

    dept = session.exec(select(Department).where(Department.code == "TKT")).first()
    assert dept is not None
    assert dept.kategorie_id == kat.id


def test_update_department_kategorie_id(client, session: Session):
    """POST /abteilungen/{id} aendert kategorie_id korrekt."""
    kat1 = DepartmentKategorie(name="Kat1")
    kat2 = DepartmentKategorie(name="Kat2")
    session.add_all([kat1, kat2])
    session.flush()

    dept = Department(code="UPK", name="Update Kat", kategorie_id=kat1.id)
    session.add(dept)
    session.commit()

    r = client.post(f"/abteilungen/{dept.id}", data={
        "code": "UPK",
        "name": "Update Kat",
        "kategorie_id": str(kat2.id),
    }, follow_redirects=False)
    assert r.status_code == 303

    session.refresh(dept)
    assert dept.kategorie_id == kat2.id


def test_update_department_kategorie_id_none(client, session: Session):
    """kategorie_id kann auf None gesetzt werden (Option '– keine –')."""
    kat = DepartmentKategorie(name="Kat Leer")
    session.add(kat)
    session.flush()
    dept = Department(code="NOK", name="No Kat", kategorie_id=kat.id)
    session.add(dept)
    session.commit()

    # Kein kategorie_id im Formular => None
    r = client.post(f"/abteilungen/{dept.id}", data={
        "code": "NOK",
        "name": "No Kat",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.refresh(dept)
    assert dept.kategorie_id is None


# ── Liste zeigt Kategorie-Namen ───────────────────────────────────────────────

def test_list_shows_kategorie_name(client, session: Session):
    """GET /abteilungen/ zeigt den Kategorie-Namen statt einen Enum-Wert."""
    kat = DepartmentKategorie(name="Platform Development")
    session.add(kat)
    session.flush()
    dept = Department(code="PD", name="PD Dept", kategorie_id=kat.id)
    session.add(dept)
    session.commit()

    r = client.get("/abteilungen/")
    assert r.status_code == 200
    assert "Platform Development" in r.text


def test_list_shows_dash_for_no_kategorie(client, session: Session):
    """GET /abteilungen/ zeigt '–' wenn keine Kategorie gesetzt ist."""
    dept = Department(code="NOC", name="No Category Dept")
    session.add(dept)
    session.commit()

    r = client.get("/abteilungen/")
    assert r.status_code == 200
    assert "NOC" in r.text


# ── Verwaltungsseite ─────────────────────────────────────────────────────────

def test_kategorien_page_accessible(client, session: Session):
    """GET /abteilungen/kategorien gibt 200 zurueck."""
    r = client.get("/abteilungen/kategorien")
    assert r.status_code == 200
    assert "Kategorien verwalten" in r.text


def test_kategorien_page_lists_existing(client, session: Session):
    """Vorhandene Kategorien werden auf der Verwaltungsseite angezeigt."""
    kat = DepartmentKategorie(name="Sichtbare Kat")
    session.add(kat)
    session.commit()

    r = client.get("/abteilungen/kategorien")
    assert r.status_code == 200
    assert "Sichtbare Kat" in r.text
