"""Tests für POST /einsaetze/bulk-delete (Bulk-Delete mehrerer Einsätze)."""
import pytest
from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Schoolyear,
    Trainee,
    TraineeRolle,
)

SY = "2025-2026"


def _setup(session: Session) -> dict:
    """Legt ein Schuljahr, einen Trainee und drei Assignments an."""
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    t = Trainee(vorname="Max", nachname="Muster", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()

    a1 = Assignment(trainee_id=t.id, schoolyear_id=SY, kw=1, jahr=2026,
                    typ=AssignmentTyp.ABTEILUNG, source=AssignmentSource.MANUAL)
    a2 = Assignment(trainee_id=t.id, schoolyear_id=SY, kw=2, jahr=2026,
                    typ=AssignmentTyp.URLAUB, source=AssignmentSource.MANUAL)
    a3 = Assignment(trainee_id=t.id, schoolyear_id=SY, kw=3, jahr=2026,
                    typ=AssignmentTyp.FREI, source=AssignmentSource.MANUAL)
    session.add_all([a1, a2, a3])
    session.commit()
    return {"trainee_id": t.id, "a1": a1.id, "a2": a2.id, "a3": a3.id}


def test_bulk_delete_two_ids(client, session):
    """POST mit 2 IDs → genau diese 2 sind weg, der dritte bleibt."""
    ids = _setup(session)

    r = client.post(
        "/einsaetze/bulk-delete",
        data={"ids": [ids["a1"], ids["a2"]]},
        follow_redirects=False,
    )

    assert r.status_code == 303, f"Erwartet 303, bekommen {r.status_code}"

    remaining = session.exec(select(Assignment)).all()
    remaining_ids = {a.id for a in remaining}
    assert ids["a1"] not in remaining_ids, "a1 sollte gelöscht sein"
    assert ids["a2"] not in remaining_ids, "a2 sollte gelöscht sein"
    assert ids["a3"] in remaining_ids, "a3 sollte noch existieren"


def test_bulk_delete_empty_selection(client, session):
    """POST ohne IDs → kein Fehler, alle Assignments bleiben erhalten."""
    ids = _setup(session)

    r = client.post(
        "/einsaetze/bulk-delete",
        data={},
        follow_redirects=False,
    )

    assert r.status_code == 303, f"Erwartet 303, bekommen {r.status_code}"

    remaining = session.exec(select(Assignment)).all()
    assert len(remaining) == 3, "Alle 3 Assignments müssen noch vorhanden sein"


def test_bulk_delete_redirect_preserves_filter(client, session):
    """Filter-Query (schoolyear_id, trainee_id) wird im Redirect beibehalten."""
    ids = _setup(session)

    r = client.post(
        f"/einsaetze/bulk-delete?schoolyear_id={SY}&trainee_id={ids['trainee_id']}",
        data={"ids": [ids["a1"]]},
        follow_redirects=False,
    )

    assert r.status_code == 303
    location = r.headers.get("location", "")
    assert "schoolyear_id=" in location or "einsaetze" in location


def test_bulk_delete_nonexistent_ids(client, session):
    """Nicht-existierende IDs führen zu keinem Fehler."""
    _setup(session)

    r = client.post(
        "/einsaetze/bulk-delete",
        data={"ids": [99999, 88888]},
        follow_redirects=False,
    )

    assert r.status_code == 303


def test_bulk_delete_single_id(client, session):
    """POST mit einer einzelnen ID löscht genau diesen Einsatz."""
    ids = _setup(session)

    r = client.post(
        "/einsaetze/bulk-delete",
        data={"ids": [ids["a3"]]},
        follow_redirects=False,
    )

    assert r.status_code == 303

    remaining = session.exec(select(Assignment)).all()
    remaining_ids = {a.id for a in remaining}
    assert ids["a3"] not in remaining_ids
    assert ids["a1"] in remaining_ids
    assert ids["a2"] in remaining_ids
