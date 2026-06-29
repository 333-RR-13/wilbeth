"""Tests fuer POST /einsaetze/copy (Drag & Drop Kopieren in der Matrix)."""
from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    DepartmentKategorie,
    Schoolyear,
    Trainee,
    TraineeRolle,
)

SY = "2025-2026"


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    abt = Department(code="AI", name="Artificial Intelligence", kategorie=DepartmentKategorie.ITO)
    session.add(abt)
    src_t = Trainee(vorname="Anna", nachname="Quelle", rolle=TraineeRolle.AZUBI)
    dst_t = Trainee(vorname="Ben", nachname="Ziel", rolle=TraineeRolle.AZUBI)
    session.add(src_t)
    session.add(dst_t)
    session.flush()
    session.commit()
    return {"src": src_t.id, "dst": dst_t.id, "abt": abt.id}


def _post_copy(client, ids, src_kw=8, src_jahr=2026, dst_kw=9, dst_jahr=2026,
               src_trainee=None, dst_trainee=None):
    return client.post("/einsaetze/copy", data={
        "src_trainee_id": src_trainee or ids["src"],
        "src_kw":         src_kw,
        "src_jahr":       src_jahr,
        "dst_trainee_id": dst_trainee or ids["dst"],
        "dst_kw":         dst_kw,
        "dst_jahr":       dst_jahr,
        "schoolyear_id":  SY,
    })


# ── Copy auf LEERE Ziel-Zelle ─────────────────────────────────────────────────

def test_copy_to_empty_creates_new_assignment(client, session):
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["src"], schoolyear_id=SY,
        kw=8, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=ids["abt"], source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = _post_copy(client, ids)
    assert r.status_code == 200

    # Ziel hat genau 1 Assignment
    dst_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["dst"])
    ).all()
    assert len(dst_rows) == 1
    dst = dst_rows[0]
    assert dst.kw == 9 and dst.jahr == 2026
    assert dst.typ == AssignmentTyp.ABTEILUNG
    assert dst.abteilung_id == ids["abt"]
    assert dst.source == AssignmentSource.MANUAL
    assert dst.notiz == ""


def test_copy_source_unchanged(client, session):
    """Quelle bleibt nach dem Kopieren unverändert."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["src"], schoolyear_id=SY,
        kw=8, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=ids["abt"], source=AssignmentSource.AUTO,
    ))
    session.commit()

    _post_copy(client, ids)

    src_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["src"])
    ).all()
    assert len(src_rows) == 1
    assert src_rows[0].kw == 8


# ── Copy auf BELEGTE Ziel-Zelle ──────────────────────────────────────────────

def test_copy_to_occupied_overwrites(client, session):
    """Wenn Ziel belegt ist, wird es überschrieben – weiterhin genau 1 Assignment."""
    ids = _setup(session)
    abt2 = Department(code="HR", name="Human Resources", kategorie=DepartmentKategorie.ITO)
    session.add(abt2)
    session.flush()

    session.add(Assignment(
        trainee_id=ids["src"], schoolyear_id=SY,
        kw=8, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=ids["abt"], source=AssignmentSource.MANUAL,
    ))
    session.add(Assignment(
        trainee_id=ids["dst"], schoolyear_id=SY,
        kw=9, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=abt2.id, source=AssignmentSource.AUTO,
    ))
    session.commit()

    r = _post_copy(client, ids)
    assert r.status_code == 200

    dst_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["dst"])
    ).all()
    assert len(dst_rows) == 1          # kein Duplikat
    dst = dst_rows[0]
    assert dst.abteilung_id == ids["abt"]   # Wert aus Quelle
    assert dst.source == AssignmentSource.MANUAL


# ── Quelle fehlt → 400, nichts angelegt ──────────────────────────────────────

def test_copy_missing_source_returns_400(client, session):
    ids = _setup(session)
    # Kein Assignment an src KW8

    r = _post_copy(client, ids)
    assert r.status_code == 400

    # Nichts am Ziel angelegt
    dst_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["dst"])
    ).all()
    assert len(dst_rows) == 0


# ── Antwort enthält Abteilungs-Kürzel (Smoke: Partial rendert) ───────────────

def test_copy_response_contains_dept_code(client, session):
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["src"], schoolyear_id=SY,
        kw=8, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=ids["abt"], source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = _post_copy(client, ids)
    assert r.status_code == 200
    # Zell-id der Zielzelle im Response
    assert f'id="cell-{ids["dst"]}-9-2026"' in r.text
    # Abteilungs-Kürzel "AI" im Response (chip)
    assert "AI" in r.text


# ── Gleiche Quelle und Ziel → no-op ──────────────────────────────────────────

def test_copy_same_cell_noop(client, session):
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["src"], schoolyear_id=SY,
        kw=8, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=ids["abt"], source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.post("/einsaetze/copy", data={
        "src_trainee_id": ids["src"],
        "src_kw":         8,
        "src_jahr":       2026,
        "dst_trainee_id": ids["src"],
        "dst_kw":         8,
        "dst_jahr":       2026,
        "schoolyear_id":  SY,
    })
    assert r.status_code == 200

    # Immer noch genau 1 Assignment (keine Duplikate)
    rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["src"])
    ).all()
    assert len(rows) == 1
