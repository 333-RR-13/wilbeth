"""Tests fuer Azubi-Archivierung.

(a) Jahreswechsel setzt Abschluss-Azubis auf aktiv=False, Promotete bleiben aktiv=True
(b) Reaktivieren-Endpoint setzt aktiv=True
(c) Loeschen-Endpoint entfernt Trainee + Assignments + Wishes + Memberships
(d) Trainees-Liste ?status=archiviert / ?status=aktiv filtert korrekt
"""

import pytest
from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeRolle,
    TraineeWish,
    UnterrichtsTyp,
    Department,
    DepartmentKategorie,
)

SY_A = "2025-2026"
SY_B = "2026-2027"


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _add_year(session: Session, sy_id: str, start_year: int) -> Schoolyear:
    y = Schoolyear(id=sy_id, start_kw=36, start_year=start_year, end_kw=35, end_year=start_year + 1)
    session.add(y)
    session.flush()
    return y


def _add_class(session: Session, name: str) -> TraineeClass:
    from app.models.school_plan import SchoolWeekTyp
    c = TraineeClass(name=name, berufsschule="JD Schule", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.flush()
    return c


def _add_trainee(session: Session, name: str, klasse_id: int | None = None, aktiv: bool = True) -> Trainee:
    t = Trainee(vorname=name, nachname="Test", rolle=TraineeRolle.AZUBI,
                klasse_id=klasse_id, aktiv=aktiv)
    session.add(t)
    session.flush()
    return t


def _add_dept(session: Session, name: str = "IT") -> Department:
    d = Department(code=name[:3].upper(), name=name, kategorie=DepartmentKategorie.ITO)
    session.add(d)
    session.flush()
    return d


# ── (a) Jahreswechsel archiviert Abschluss-Azubis ─────────────────────────────

def test_jahreswechsel_archiviert_abschluss(client, session: Session):
    """Ein FISI-3.LJ-Azubi (keine naechste Klasse) wird nach uebernehmen aktiv=False.
    Ein FISI-2.LJ-Azubi (wird promotet zu FISI-3.LJ) bleibt aktiv=True."""
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    # FISI 2. LJ → FISI 3. LJ (via Namens-Ableitung, kein next_class_id noetig)
    k2 = _add_class(session, "FISI 2. LJ")
    k3 = _add_class(session, "FISI 3. LJ")
    # FISI 3. LJ hat KEINE naechste Klasse → Abschluss

    # Promotierter Azubi: in SY_A Klasse 2
    azubi_promot = _add_trainee(session, "Promotiert", klasse_id=k2.id, aktiv=True)
    session.add(TraineeClassMembership(
        trainee_id=azubi_promot.id, schoolyear_id=SY_A, klasse_id=k2.id
    ))

    # Abschluss-Azubi: in SY_A Klasse 3
    azubi_abschl = _add_trainee(session, "Abschluss", klasse_id=k3.id, aktiv=True)
    session.add(TraineeClassMembership(
        trainee_id=azubi_abschl.id, schoolyear_id=SY_A, klasse_id=k3.id
    ))
    session.commit()

    r = client.post(
        "/jahreswechsel/uebernehmen",
        data={"source_year_id": SY_A, "target_year_id": SY_B},
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()

    # Abschluss-Azubi muss archiviert sein
    t_abschl = session.get(Trainee, azubi_abschl.id)
    assert t_abschl.aktiv is False, "Abschluss-Azubi muss nach Jahreswechsel archiviert sein"

    # Promotierter Azubi muss aktiv bleiben
    t_promot = session.get(Trainee, azubi_promot.id)
    assert t_promot.aktiv is True, "Promotierter Azubi muss nach Jahreswechsel aktiv bleiben"


# ── (b) Reaktivieren-Endpoint ──────────────────────────────────────────────────

def test_reaktivieren_endpoint(client, session: Session):
    """POST /trainees/{id}/reaktivieren setzt aktiv=True."""
    azubi = _add_trainee(session, "Archiviert", aktiv=False)
    session.commit()

    assert azubi.aktiv is False

    r = client.post(f"/trainees/{azubi.id}/reaktivieren", follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    t = session.get(Trainee, azubi.id)
    assert t.aktiv is True, "Azubi muss nach Reaktivieren aktiv=True sein"


# ── (c) Loeschen-Endpoint entfernt alle abhaengigen Daten ─────────────────────

def test_loeschen_endpoint_entfernt_abhaengige_daten(client, session: Session):
    """POST /trainees/{id}/loeschen loescht Trainee + Assignments + Wishes + Memberships."""
    _add_year(session, SY_A, 2025)
    klasse = _add_class(session, "Loesch-Test Klasse")
    dept = _add_dept(session, "LT")

    azubi = _add_trainee(session, "ZuLoeschen", klasse_id=klasse.id, aktiv=False)

    # Abhaengige Daten anlegen
    session.add(Assignment(
        trainee_id=azubi.id,
        schoolyear_id=SY_A,
        kw=10,
        jahr=2026,
        typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=dept.id,
        source=AssignmentSource.MANUAL,
    ))
    session.add(TraineeWish(trainee_id=azubi.id, department_id=dept.id, prioritaet=1))
    session.add(TraineeClassMembership(
        trainee_id=azubi.id, schoolyear_id=SY_A, klasse_id=klasse.id
    ))
    session.commit()

    trainee_id = azubi.id

    # Vorher: je 1 Eintrag
    assert session.exec(select(Assignment).where(Assignment.trainee_id == trainee_id)).first() is not None
    assert session.exec(select(TraineeWish).where(TraineeWish.trainee_id == trainee_id)).first() is not None
    assert session.exec(select(TraineeClassMembership).where(TraineeClassMembership.trainee_id == trainee_id)).first() is not None

    r = client.post(f"/trainees/{trainee_id}/loeschen", follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()

    # Trainee weg
    assert session.get(Trainee, trainee_id) is None, "Trainee muss nach Loeschen weg sein"
    # Abhaengige Zeilen weg
    assert session.exec(select(Assignment).where(Assignment.trainee_id == trainee_id)).first() is None, \
        "Assignments muessen nach Loeschen weg sein"
    assert session.exec(select(TraineeWish).where(TraineeWish.trainee_id == trainee_id)).first() is None, \
        "Wishes muessen nach Loeschen weg sein"
    assert session.exec(select(TraineeClassMembership).where(TraineeClassMembership.trainee_id == trainee_id)).first() is None, \
        "Memberships muessen nach Loeschen weg sein"


# ── (d) Trainees-Liste Status-Filter ──────────────────────────────────────────

def test_liste_status_filter_aktiv(client, session: Session):
    """GET /trainees/?status=aktiv enthaelt nur aktive Azubis."""
    aktiv = _add_trainee(session, "Aktiver", aktiv=True)
    inaktiv = _add_trainee(session, "Archivierter", aktiv=False)
    session.commit()

    r = client.get("/trainees/?status=aktiv")
    assert r.status_code == 200
    assert aktiv.vorname in r.text
    assert inaktiv.vorname not in r.text


def test_liste_status_filter_archiviert(client, session: Session):
    """GET /trainees/?status=archiviert enthaelt nur inaktive Azubis."""
    aktiv = _add_trainee(session, "NochAktiv", aktiv=True)
    inaktiv = _add_trainee(session, "Archiviert2", aktiv=False)
    session.commit()

    r = client.get("/trainees/?status=archiviert")
    assert r.status_code == 200
    assert inaktiv.vorname in r.text
    assert aktiv.vorname not in r.text


def test_liste_status_filter_alle(client, session: Session):
    """GET /trainees/?status=alle enthaelt sowohl aktive als auch inaktive Azubis."""
    aktiv = _add_trainee(session, "AlleAktiv", aktiv=True)
    inaktiv = _add_trainee(session, "AlleArchiv", aktiv=False)
    session.commit()

    r = client.get("/trainees/?status=alle")
    assert r.status_code == 200
    assert aktiv.vorname in r.text
    assert inaktiv.vorname in r.text


def test_liste_default_zeigt_nur_aktive(client, session: Session):
    """GET /trainees/ (ohne status-Param) zeigt standardmaessig nur aktive."""
    aktiv = _add_trainee(session, "StandardAktiv", aktiv=True)
    inaktiv = _add_trainee(session, "StandardArchiv", aktiv=False)
    session.commit()

    r = client.get("/trainees/")
    assert r.status_code == 200
    assert aktiv.vorname in r.text
    assert inaktiv.vorname not in r.text
