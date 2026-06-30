"""Tests fuer TraineeClassMembership-Feature.

(a) Membership steuert school_sync pro Jahr
(b) Fallback ohne Membership = altes Verhalten
(c) overview trainee_klasse_map nutzt Membership fuers gewaehlte Jahr
(d) klasse_fuer-Helper (Override / Fallback / berechnet) + semester_label
"""

import pytest
from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.services.membership_utils import klasse_fuer, next_class_for, semester_label, upsert_membership
from app.services.school_sync import sync_trainee

SY_A = "2025-2026"
SY_B = "2026-2027"


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _add_year(session: Session, sy_id: str, start_year: int) -> Schoolyear:
    y = Schoolyear(id=sy_id, start_kw=36, start_year=start_year, end_kw=35, end_year=start_year + 1)
    session.add(y)
    session.flush()
    return y


def _add_class(session: Session, name: str) -> TraineeClass:
    c = TraineeClass(name=name, berufsschule="JD Schule", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.flush()
    return c


def _add_plan_week(session: Session, klasse_id: int, sy_id: str, kw: int, jahr: int,
                   typ: SchoolWeekTyp = SchoolWeekTyp.BERUFSSCHULE) -> None:
    plan = session.exec(
        select(SchoolPlan).where(SchoolPlan.klasse_id == klasse_id, SchoolPlan.schoolyear_id == sy_id)
    ).first()
    if plan is None:
        plan = SchoolPlan(klasse_id=klasse_id, schoolyear_id=sy_id)
        session.add(plan)
        session.flush()
    session.add(SchoolPlanWeek(plan_id=plan.id, kw=kw, jahr=jahr, typ=typ))
    session.flush()


def _add_trainee(session: Session, name: str, klasse_id: int | None = None) -> Trainee:
    t = Trainee(vorname=name, nachname="Test", rolle=TraineeRolle.AZUBI, klasse_id=klasse_id)
    session.add(t)
    session.flush()
    return t


def _add_trainee_full(
    session: Session,
    name: str,
    klasse_id: int | None = None,
    rolle: TraineeRolle = TraineeRolle.AZUBI,
    ausbildungsbeginn=None,
) -> Trainee:
    t = Trainee(
        vorname=name,
        nachname="Test",
        rolle=rolle,
        klasse_id=klasse_id,
        ausbildungsbeginn=ausbildungsbeginn,
    )
    session.add(t)
    session.flush()
    return t


# ── (a) Membership steuert school_sync pro Jahr ────────────────────────────────

def test_membership_sync_per_year(session: Session):
    """Azubi in Klasse A (SY_A, KW 25) und Klasse B (SY_B, KW 40) →
    korrekte AUTO-Einsaetze je Jahr."""
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    klasse_a = _add_class(session, "FISI 1. LJ")
    klasse_b = _add_class(session, "FISI 2. LJ")
    _add_plan_week(session, klasse_a.id, SY_A, kw=25, jahr=2026)
    _add_plan_week(session, klasse_b.id, SY_B, kw=40, jahr=2026)

    trainee = _add_trainee(session, "Anna", klasse_id=klasse_a.id)
    # Membership fuer beide Jahre
    session.add(TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY_A, klasse_id=klasse_a.id))
    session.add(TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY_B, klasse_id=klasse_b.id))
    session.commit()

    sync_trainee(session, trainee.id)

    assignments = session.exec(
        select(Assignment).where(
            Assignment.trainee_id == trainee.id,
            Assignment.source == AssignmentSource.AUTO,
        )
    ).all()

    assert len(assignments) == 2
    by_year = {a.schoolyear_id: a for a in assignments}
    assert SY_A in by_year
    assert SY_B in by_year
    assert by_year[SY_A].kw == 25
    assert by_year[SY_B].kw == 40


# ── (b) Fallback ohne Membership = altes Verhalten ────────────────────────────

def test_fallback_without_membership(session: Session):
    """Trainee ohne Membership: bisheriges Verhalten ueber trainee.klasse_id."""
    _add_year(session, SY_A, 2025)
    klasse = _add_class(session, "FISI No Membership")
    _add_plan_week(session, klasse.id, SY_A, kw=10, jahr=2026)

    trainee = _add_trainee(session, "Bob", klasse_id=klasse.id)
    # KEINE Membership anlegen
    session.commit()

    sync_trainee(session, trainee.id)

    assignments = session.exec(
        select(Assignment).where(
            Assignment.trainee_id == trainee.id,
            Assignment.source == AssignmentSource.AUTO,
        )
    ).all()

    assert len(assignments) == 1
    assert assignments[0].kw == 10
    assert assignments[0].schoolyear_id == SY_A


# ── (c) overview trainee_klasse_map nutzt Membership ──────────────────────────

def test_overview_klasse_map_uses_membership(client, session: Session):
    """GET /overview?schoolyear_id=SY_B → Membership fuer SY_B wird genutzt."""
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    klasse_a = _add_class(session, "FISI Ov A")
    klasse_b = _add_class(session, "FISI Ov B")

    trainee = _add_trainee(session, "Clara", klasse_id=klasse_a.id)
    # Membership fuer SY_B mit Klasse B
    session.add(TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY_B, klasse_id=klasse_b.id))
    session.commit()

    r = client.get(f"/overview?schoolyear_id={SY_B}")
    assert r.status_code == 200
    # Klasse B soll im HTML vorkommen (trainee_klasse_map -> klasse_b)
    assert klasse_b.name in r.text


# ── (d) klasse_fuer-Helper ─────────────────────────────────────────────────────

def test_klasse_fuer_with_membership(session: Session):
    """klasse_fuer gibt Membership-Klasse zurueck wenn vorhanden."""
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    klasse_a = _add_class(session, "KF FISI 1")
    klasse_b = _add_class(session, "KF FISI 2")

    trainee = _add_trainee(session, "Igor", klasse_id=klasse_a.id)
    session.add(TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY_B, klasse_id=klasse_b.id))
    session.commit()

    assert klasse_fuer(session, trainee, SY_B) == klasse_b.id


def test_klasse_fuer_fallback(session: Session):
    """klasse_fuer faellt auf trainee.klasse_id zurueck wenn keine Membership und
    kein Anker (ausbildungsbeginn None)."""
    _add_year(session, SY_A, 2025)
    klasse_a = _add_class(session, "KFF FISI 1")
    trainee = _add_trainee(session, "Jana", klasse_id=klasse_a.id)
    session.commit()

    assert klasse_fuer(session, trainee, SY_A) == klasse_a.id


def test_klasse_fuer_no_class(session: Session):
    """klasse_fuer gibt None zurueck wenn weder Membership noch klasse_id."""
    _add_year(session, SY_A, 2025)
    trainee = _add_trainee(session, "Kai", klasse_id=None)
    session.commit()

    assert klasse_fuer(session, trainee, SY_A) is None


def test_upsert_membership_creates(session: Session):
    """upsert_membership legt neue Membership an."""
    _add_year(session, SY_A, 2025)
    klasse = _add_class(session, "Upsert Test")
    trainee = _add_trainee(session, "Lena")
    session.commit()

    upsert_membership(session, trainee.id, SY_A, klasse.id)
    session.commit()

    m = session.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee.id,
            TraineeClassMembership.schoolyear_id == SY_A,
        )
    ).first()
    assert m is not None
    assert m.klasse_id == klasse.id


def test_upsert_membership_updates(session: Session):
    """upsert_membership aktualisiert bestehende Membership."""
    _add_year(session, SY_A, 2025)
    klasse_a = _add_class(session, "Upsert A")
    klasse_b = _add_class(session, "Upsert B")
    trainee = _add_trainee(session, "Max")
    session.add(TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY_A, klasse_id=klasse_a.id))
    session.commit()

    upsert_membership(session, trainee.id, SY_A, klasse_b.id)
    session.commit()

    memberships = session.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee.id,
            TraineeClassMembership.schoolyear_id == SY_A,
        )
    ).all()
    assert len(memberships) == 1
    assert memberships[0].klasse_id == klasse_b.id


# ── Klassen-Progression nach Namens-Konvention ("<Beruf> n. LJ") ──────────────

def test_next_class_for_by_name(session: Session):
    """next_class_for leitet die naechste Klasse aus dem Namen ab."""
    k1 = _add_class(session, "FISI 1. LJ")
    k2 = _add_class(session, "FISI 2. LJ")
    k3 = _add_class(session, "FISI 3. LJ")
    b1 = _add_class(session, "Büro 1. LJ")
    b2 = _add_class(session, "Büro 2. LJ")
    session.commit()
    alle = [k1, k2, k3, b1, b2]

    assert next_class_for(k1, alle).id == k2.id
    assert next_class_for(k2, alle).id == k3.id
    assert next_class_for(k3, alle) is None      # 3. LJ = Abschluss
    assert next_class_for(b1, alle).id == b2.id  # funktioniert auch fuer Büro
    assert next_class_for(b2, alle) is None       # kein "Büro 3. LJ" vorhanden


def test_next_class_for_override(session: Session):
    """Expliziter next_class_id schlaegt die Namens-Ableitung."""
    a = _add_class(session, "Sonderklasse A")
    b = _add_class(session, "Sonderklasse B")
    a.next_class_id = b.id
    session.add(a)
    session.commit()

    assert next_class_for(a, [a, b]).id == b.id


def test_update_without_class_selection_preserves_klasse(client, session: Session):
    """Speichern OHNE Klassenwahl soll die bestehende Klasse NICHT loeschen (Bug A)."""
    _add_year(session, SY_A, 2025)
    klasse = _add_class(session, "FISI 1. LJ")
    trainee = _add_trainee(session, "Preserve", klasse_id=klasse.id)
    session.commit()

    # POST ohne membership_klasse_id (leere Auswahl)
    r = client.post(
        f"/trainees/{trainee.id}",
        data={
            "vorname": "Preserve",
            "nachname": "Test",
            "rolle": "AZUBI",
            "klasse_id": "",
            "membership_year_id": SY_A,
            "membership_klasse_id": "",  # keine Klasse gewaehlt
            "notizen": "",
            "steckbrief": "",
            "aktiv": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    t = session.get(Trainee, trainee.id)
    # klasse_id muss unveraendert bleiben
    assert t.klasse_id == klasse.id


# ── Berechnetes klasse_fuer + semester_label ──────────────────────────────────

def test_klasse_fuer_berechnet_naechstes_lj(session: Session):
    """(a) AZUBI mit ausbildungsbeginn 2025 + Einstiegsklasse 'FISI 1. LJ',
    ohne Membership fuers Zieljahr -> klasse_fuer(2026-2027) liefert 'FISI 2. LJ'."""
    from datetime import date
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    k1 = _add_class(session, "FISI 1. LJ")
    k2 = _add_class(session, "FISI 2. LJ")

    # ausbildungsbeginn im September 2025 -> start_year = 2025
    trainee = _add_trainee_full(
        session,
        "Berechnet",
        klasse_id=k1.id,
        rolle=TraineeRolle.AZUBI,
        ausbildungsbeginn=date(2025, 9, 1),
    )
    session.commit()

    # Keine explizite Membership fuer SY_B -> Berechnung greift
    result = klasse_fuer(session, trainee, SY_B)
    assert result == k2.id


def test_klasse_fuer_absolvent_azubi(session: Session):
    """(b) AZUBI im Abschlussjahr -> klasse_fuer fuers Folgejahr -> None."""
    from datetime import date
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    # Nur k3 existiert, kein k4 -> Abschluss nach 3. LJ
    k3 = _add_class(session, "FISI 3. LJ")

    # start_year 2025, target SY_B start_year 2026 -> steps=1
    # next_class_for(k3) -> None (3. LJ = Abschluss) -> AZUBI -> return None
    trainee = _add_trainee_full(
        session,
        "Absolvent",
        klasse_id=k3.id,
        rolle=TraineeRolle.AZUBI,
        ausbildungsbeginn=date(2025, 9, 1),
    )
    session.commit()

    result = klasse_fuer(session, trainee, SY_B)
    assert result is None


def test_klasse_fuer_override_schlaegt_berechnung(session: Session):
    """(c) Explizite Membership schlaegt die berechnete Klasse."""
    from datetime import date
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    k1 = _add_class(session, "FISI 1. LJ")
    k2 = _add_class(session, "FISI 2. LJ")
    k_override = _add_class(session, "Sonder Override")

    # Berechnung wuerde k2 liefern (ausbildungsbeginn 2025, target 2026)
    trainee = _add_trainee_full(
        session,
        "Override",
        klasse_id=k1.id,
        rolle=TraineeRolle.AZUBI,
        ausbildungsbeginn=date(2025, 9, 1),
    )
    # Aber: explizite Membership fuer SY_B zeigt auf k_override
    session.add(TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY_B, klasse_id=k_override.id))
    session.commit()

    result = klasse_fuer(session, trainee, SY_B)
    assert result == k_override.id


def test_dh_student_klasse_bleibt_und_semester_label(session: Session):
    """(d) DH-Student: klasse_fuer bleibt gleiche Klasse (kein Abschluss);
    semester_label liefert das erwartete Label."""
    from datetime import date
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    # DH-Klassen haben kein "<Beruf> n. LJ"-Muster -> next_class_for gibt None zurueck
    k_dh = _add_class(session, "DHBW Cybersecurity")

    # start_year = 2025, target SY_B start_year = 2026 -> steps = 1
    # next_class_for(k_dh) -> None (kein LJ-Muster)
    # rolle != AZUBI -> break -> klasse bleibt k_dh
    trainee = _add_trainee_full(
        session,
        "DH Student",
        klasse_id=k_dh.id,
        rolle=TraineeRolle.DH_STUDENT,
        ausbildungsbeginn=date(2025, 9, 1),
    )
    session.commit()

    # klasse_fuer: DH bleibt in k_dh
    result = klasse_fuer(session, trainee, SY_B)
    assert result == k_dh.id

    # semester_label fuer SY_B (steps_years=1, base=2):
    # halbjahr "1" -> "3. Semester"
    # halbjahr "2" -> "4. Semester"
    # halbjahr ""  -> "3./4. Semester"
    assert semester_label(session, trainee, SY_B, "1") == "3. Semester"
    assert semester_label(session, trainee, SY_B, "2") == "4. Semester"
    assert semester_label(session, trainee, SY_B, "") == "3./4. Semester"

    # semester_label fuer SY_A (steps_years=0, base=0):
    # halbjahr "1" -> "1. Semester"
    assert semester_label(session, trainee, SY_A, "1") == "1. Semester"

    # semester_label fuer AZUBI -> None
    azubi = _add_trainee_full(
        session, "Azubi SL", klasse_id=k_dh.id, rolle=TraineeRolle.AZUBI,
        ausbildungsbeginn=date(2025, 9, 1),
    )
    session.commit()
    assert semester_label(session, azubi, SY_B, "1") is None
