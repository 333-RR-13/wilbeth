"""Tests fuer (A) aktiv-Filter und (B) Gruppierung in der Uebersichts-Matrix."""
from sqlmodel import Session

from app.models import (
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.models.trainee_class_membership import TraineeClassMembership
from app.services.membership_utils import beruf_und_lehrjahr

SY = "2025-2026"


# ---------------------------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------------------------

def _make_year(session: Session) -> None:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.flush()


def _make_class(session: Session, name: str) -> TraineeClass:
    c = TraineeClass(name=name, berufsschule="BS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.flush()
    return c


def _add_membership(session: Session, trainee_id: int, klasse_id: int) -> None:
    session.add(TraineeClassMembership(
        trainee_id=trainee_id,
        schoolyear_id=SY,
        klasse_id=klasse_id,
    ))
    session.flush()


# ---------------------------------------------------------------------------
# (A) aktiv-Filter
# ---------------------------------------------------------------------------

def test_inaktiver_azubi_nicht_sichtbar(client, session):
    """Trainee mit aktiv=False darf in der Uebersicht nicht erscheinen."""
    _make_year(session)
    aktiv = Trainee(vorname="Anna", nachname="Aktiv", rolle=TraineeRolle.AZUBI, aktiv=True)
    inaktiv = Trainee(vorname="Igor", nachname="Inaktiv", rolle=TraineeRolle.AZUBI, aktiv=False)
    session.add_all([aktiv, inaktiv])
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Aktiv" in r.text
    assert "Inaktiv" not in r.text


def test_aktiver_azubi_sichtbar(client, session):
    """Trainee mit aktiv=True erscheint in der Uebersicht."""
    _make_year(session)
    aktiv = Trainee(vorname="Anna", nachname="Sichtbar", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(aktiv)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Sichtbar" in r.text


# ---------------------------------------------------------------------------
# (B) Gruppierung – Beruf- und Klassen-Header
# ---------------------------------------------------------------------------

def test_gruppierung_reihenfolge_beruf_klasse(client, session):
    """Ohne Header, aber die Azubi-Reihenfolge ist nach Beruf -> Lehrjahr gruppiert."""
    _make_year(session)
    fisi1 = _make_class(session, "FISI 1. LJ")
    fisi2 = _make_class(session, "FISI 2. LJ")
    fiae2 = _make_class(session, "FIAE 2. LJ")

    t1 = Trainee(vorname="Adam", nachname="Alpha", rolle=TraineeRolle.AZUBI)
    t2 = Trainee(vorname="Berta", nachname="Beta", rolle=TraineeRolle.AZUBI)
    t3 = Trainee(vorname="Carla", nachname="Ceta", rolle=TraineeRolle.AZUBI)
    session.add_all([t1, t2, t3])
    session.flush()

    _add_membership(session, t1.id, fisi1.id)
    _add_membership(session, t2.id, fisi2.id)
    _add_membership(session, t3.id, fiae2.id)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # Keine sichtbaren Gruppen-Ueberschriften mehr
    assert "matrix-group-beruf" not in r.text
    assert "matrix-group-klasse" not in r.text
    # Reihenfolge: FIAE (Ceta) -> FISI 1. LJ (Alpha) -> FISI 2. LJ (Beta)
    ceta_pos = r.text.index("Ceta")
    alpha_pos = r.text.index("Alpha")
    beta_pos = r.text.index("Beta")
    assert ceta_pos < alpha_pos < beta_pos, "Reihenfolge FIAE -> FISI 1. LJ -> FISI 2. LJ"


def test_keine_gruppen_header(client, session):
    """Es werden KEINE Beruf-/Klassen-Ueberschriften gerendert (nur die Azubis)."""
    _make_year(session)
    fisi2 = _make_class(session, "FISI 2. LJ")

    t = Trainee(vorname="Dirk", nachname="Dorf", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    _add_membership(session, t.id, fisi2.id)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "matrix-group-beruf" not in r.text
    assert "matrix-group-klasse" not in r.text
    assert "Dorf" in r.text   # Azubi selbst erscheint weiterhin


def test_trainee_ohne_klasse_wird_angezeigt(client, session):
    """Trainee ohne Klassen-Membership erscheint trotzdem in der Uebersicht."""
    _make_year(session)
    t = Trainee(vorname="Emil", nachname="Einzel", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Einzel" in r.text


def test_trainee_reihenfolge_innerhalb_klasse(client, session):
    """Trainees innerhalb einer Klasse sind nach (nachname, vorname) sortiert."""
    _make_year(session)
    fisi2 = _make_class(session, "FISI 2. LJ")

    t1 = Trainee(vorname="Zoe", nachname="Zahn", rolle=TraineeRolle.AZUBI)
    t2 = Trainee(vorname="Aaron", nachname="Abel", rolle=TraineeRolle.AZUBI)
    session.add_all([t1, t2])
    session.flush()
    _add_membership(session, t1.id, fisi2.id)
    _add_membership(session, t2.id, fisi2.id)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    abel_pos = r.text.index("Abel")
    zahn_pos = r.text.index("Zahn")
    assert abel_pos < zahn_pos, "Abel soll vor Zahn erscheinen (alphabetisch)"


# ---------------------------------------------------------------------------
# beruf_und_lehrjahr Unit-Tests
# ---------------------------------------------------------------------------

def test_beruf_und_lehrjahr_fisi():
    assert beruf_und_lehrjahr("FISI 2. LJ") == ("FISI", 2)


def test_beruf_und_lehrjahr_buero():
    assert beruf_und_lehrjahr("Büro 3. LJ") == ("Büro", 3)


def test_beruf_und_lehrjahr_dhbw():
    assert beruf_und_lehrjahr("DHBW Cybersecurity") == ("DHBW Cybersecurity", None)


def test_beruf_und_lehrjahr_none():
    assert beruf_und_lehrjahr(None) == ("Ohne Klasse", None)
