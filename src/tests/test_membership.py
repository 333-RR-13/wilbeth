"""Tests fuer TraineeClassMembership-Feature.

(a) Membership steuert school_sync pro Jahr
(b) Fallback ohne Membership = altes Verhalten
(c) overview trainee_klasse_map nutzt Membership fuers gewaehlte Jahr
(d) Jahreswechsel-Vorschau + Uebernehmen legt korrekte Memberships an,
    Klassen ohne next_class werden nicht uebernommen
(e) klasse_fuer-Helper
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
from app.services.membership_utils import klasse_fuer, upsert_membership
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


# ── (d) Jahreswechsel Vorschau + Uebernehmen ──────────────────────────────────

def test_jahreswechsel_vorschau(client, session: Session):
    """GET /jahreswechsel/?source=SY_A&target=SY_B zeigt korrekte Vorschau."""
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    klasse_a = _add_class(session, "JW FISI 1")
    klasse_b = _add_class(session, "JW FISI 2")
    klasse_a.next_class_id = klasse_b.id
    session.add(klasse_a)

    # Abschluss-Klasse (kein next_class_id)
    klasse_end = _add_class(session, "JW FISI 3 Abschluss")

    trainee1 = _add_trainee(session, "Diana")
    trainee2 = _add_trainee(session, "Emil")
    session.add(TraineeClassMembership(trainee_id=trainee1.id, schoolyear_id=SY_A, klasse_id=klasse_a.id))
    session.add(TraineeClassMembership(trainee_id=trainee2.id, schoolyear_id=SY_A, klasse_id=klasse_end.id))
    session.commit()

    r = client.get(f"/jahreswechsel/?source_year_id={SY_A}&target_year_id={SY_B}")
    assert r.status_code == 200
    assert "JW FISI 1" in r.text
    assert "JW FISI 2" in r.text
    assert "Abschluss" in r.text or "JW FISI 3 Abschluss" in r.text


def test_jahreswechsel_uebernehmen(client, session: Session):
    """POST /jahreswechsel/uebernehmen legt Memberships an, Abschluss nicht."""
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    klasse_a = _add_class(session, "JWU FISI 1")
    klasse_b = _add_class(session, "JWU FISI 2")
    klasse_a.next_class_id = klasse_b.id
    session.add(klasse_a)

    klasse_end = _add_class(session, "JWU FISI 3 Abschluss")

    trainee1 = _add_trainee(session, "Franz")
    trainee2 = _add_trainee(session, "Greta")
    session.add(TraineeClassMembership(trainee_id=trainee1.id, schoolyear_id=SY_A, klasse_id=klasse_a.id))
    session.add(TraineeClassMembership(trainee_id=trainee2.id, schoolyear_id=SY_A, klasse_id=klasse_end.id))
    session.commit()

    r = client.post(
        "/jahreswechsel/uebernehmen",
        data={"source_year_id": SY_A, "target_year_id": SY_B},
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()

    # trainee1 soll in SY_B Klasse B haben
    m1 = session.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee1.id,
            TraineeClassMembership.schoolyear_id == SY_B,
        )
    ).first()
    assert m1 is not None
    assert m1.klasse_id == klasse_b.id

    # trainee2 (Abschluss) soll KEINE Membership in SY_B haben
    m2 = session.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee2.id,
            TraineeClassMembership.schoolyear_id == SY_B,
        )
    ).first()
    assert m2 is None

    # trainee1.klasse_id soll auf klasse_b gesetzt sein
    t1 = session.get(Trainee, trainee1.id)
    assert t1.klasse_id == klasse_b.id


def test_jahreswechsel_skip_existing(client, session: Session):
    """Bereits vorhandene Memberships im Ziel-Jahr werden uebersprungen."""
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    klasse_a = _add_class(session, "JWS FISI 1")
    klasse_b = _add_class(session, "JWS FISI 2")
    klasse_c = _add_class(session, "JWS FISI 2 Variant")
    klasse_a.next_class_id = klasse_b.id
    session.add(klasse_a)

    trainee = _add_trainee(session, "Heidi")
    # Membership in SY_A
    session.add(TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY_A, klasse_id=klasse_a.id))
    # Bereits existierende Membership in SY_B (andere Klasse C)
    session.add(TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY_B, klasse_id=klasse_c.id))
    session.commit()

    r = client.post(
        "/jahreswechsel/uebernehmen",
        data={"source_year_id": SY_A, "target_year_id": SY_B},
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()

    # Membership bleibt klasse_c (nicht ueberschrieben)
    m = session.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee.id,
            TraineeClassMembership.schoolyear_id == SY_B,
        )
    ).first()
    assert m is not None
    assert m.klasse_id == klasse_c.id


# ── (e) klasse_fuer-Helper ─────────────────────────────────────────────────────

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
    """klasse_fuer faellt auf trainee.klasse_id zurueck wenn keine Membership."""
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
