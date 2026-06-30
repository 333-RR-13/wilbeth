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
    d = Department(code=name[:3].upper(), name=name)
    session.add(d)
    session.flush()
    return d


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


# ── (a) Jahresabschluss Aktionen ──────────────────────────────────────────────

def test_absolvent_wird_archiviert(client, session: Session):
    """Absolvent (AZUBI in FISI 3. LJ) wird nach POST /jahresabschluss/abschliessen aktiv=False."""
    closing = _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)  # Folgejahr anlegen

    fisi3 = _add_class(session, "FISI 3. LJ")
    fisi2 = _add_class(session, "FISI 2. LJ")
    fisi1 = _add_class(session, "FISI 1. LJ")

    # Absolvent: AZUBI im 3. LJ -> kein next_class_for
    absolvent = _add_trainee(session, "AbsolventMax", klasse_id=fisi3.id, aktiv=True)
    session.add(TraineeClassMembership(
        trainee_id=absolvent.id, schoolyear_id=SY_A, klasse_id=fisi3.id
    ))

    # Nicht-Absolvent: AZUBI im 2. LJ -> rueckt auf 3. LJ auf
    weiter = _add_trainee(session, "WeiterAnna", klasse_id=fisi2.id, aktiv=True)
    session.add(TraineeClassMembership(
        trainee_id=weiter.id, schoolyear_id=SY_A, klasse_id=fisi2.id
    ))
    session.commit()

    r = client.post(
        "/jahresabschluss/abschliessen",
        data={"schoolyear_id": SY_A},
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    assert session.get(Trainee, absolvent.id).aktiv is False, \
        "Absolvent (FISI 3. LJ) muss nach Abschluss archiviert sein"
    assert session.get(Trainee, weiter.id).aktiv is True, \
        "2.-LJ-AZUBI muss nach Abschluss aktiv bleiben"


def test_aktion_wiederholt_schreibt_override_membership(client, session: Session):
    """aktion 'wiederholt' schreibt Override-Membership fuers Folgejahr mit gleicher Klasse."""
    from app.services.membership_utils import klasse_fuer as _klasse_fuer

    closing = _add_year(session, SY_A, 2025)
    folge = _add_year(session, SY_B, 2026)

    fisi2 = _add_class(session, "FISI 2. LJ")
    fisi3 = _add_class(session, "FISI 3. LJ")  # next_class_for(fisi2) ergibt fisi3

    wiederholer = _add_trainee(session, "WiederholerKlaus", klasse_id=fisi2.id, aktiv=True)
    session.add(TraineeClassMembership(
        trainee_id=wiederholer.id, schoolyear_id=SY_A, klasse_id=fisi2.id
    ))
    session.commit()

    r = client.post(
        "/jahresabschluss/abschliessen",
        data={
            "schoolyear_id": SY_A,
            f"aktion_{wiederholer.id}": "wiederholt",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    # klasse_fuer(folgejahr) muss fisi2 (gleiche Klasse) zurueckgeben, nicht fisi3
    klasse_id = _klasse_fuer(session, session.get(Trainee, wiederholer.id), SY_B)
    assert klasse_id == fisi2.id, \
        "Wiederholer muss im Folgejahr dieselbe Klasse (fisi2) haben, nicht die aufgestiegene"


def test_aktion_abbruch_setzt_inaktiv(client, session: Session):
    """aktion 'abbruch' setzt trainee.aktiv=False."""
    _add_year(session, SY_A, 2025)

    fisi1 = _add_class(session, "FISI 1. LJ")
    abbrecher = _add_trainee(session, "AbbrecherTom", klasse_id=fisi1.id, aktiv=True)
    session.add(TraineeClassMembership(
        trainee_id=abbrecher.id, schoolyear_id=SY_A, klasse_id=fisi1.id
    ))
    session.commit()

    r = client.post(
        "/jahresabschluss/abschliessen",
        data={
            "schoolyear_id": SY_A,
            f"aktion_{abbrecher.id}": "abbruch",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    assert session.get(Trainee, abbrecher.id).aktiv is False, \
        "Abbrecher muss nach Abschluss inaktiv sein"


def test_aktion_wechselt_schreibt_override_membership(client, session: Session):
    """aktion 'wechselt' mit gewaehlter Klasse schreibt die Override-Membership entsprechend."""
    from app.services.membership_utils import klasse_fuer as _klasse_fuer

    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    fisi2 = _add_class(session, "FISI 2. LJ")
    fiae1 = _add_class(session, "FIAE 1. LJ")

    wechsler = _add_trainee(session, "WechslerLisa", klasse_id=fisi2.id, aktiv=True)
    session.add(TraineeClassMembership(
        trainee_id=wechsler.id, schoolyear_id=SY_A, klasse_id=fisi2.id
    ))
    session.commit()

    r = client.post(
        "/jahresabschluss/abschliessen",
        data={
            "schoolyear_id": SY_A,
            f"aktion_{wechsler.id}": "wechselt",
            f"wechsel_klasse_{wechsler.id}": str(fiae1.id),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    klasse_id = _klasse_fuer(session, session.get(Trainee, wechsler.id), SY_B)
    assert klasse_id == fiae1.id, \
        "Wechsler muss im Folgejahr die gewaehlte Zielklasse (fiae1) haben"
