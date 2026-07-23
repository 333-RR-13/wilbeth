"""Tests fuer app/services/school_sync.py und die Router-Hooks.

Szenarios:
1. sync_class erzeugt AUTO BERUFSSCHULE fuer alle Mitglieder einer Klasse.
2. Manuelle Eintraege werden von sync_trainee nicht ueberschrieben.
3. Trainee verlaesst Klasse → sync_trainee entfernt seine AUTO BS-Eintraege.
4. SchoolPlanWeek entfernen → sync_class loescht die AUTO-Eintraege.
5. Route POST /trainees/ + Klasse mit Schulplan → AUTO-Eintrag wird angelegt.
6. Route POST /klassen/{id} synchronisiert AUTO-Eintraege der aktuellen (ueber
   den Anker berechneten) Mitglieder; eine Mitglieder-Pflege ueber diese Route
   (Checkbox 'mitglied') gibt es nicht mehr - ein mitgeschicktes 'mitglied'-Feld
   bleibt wirkungslos.
7. UNI-Mapping: SchoolPlanWeek typ=UNI → AUTO-Eintrag typ=UNI.
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
    TraineeRolle,
    UnterrichtsTyp,
)
from app.services.school_sync import sync_class, sync_trainee

SY = "2025-2026"
KW = 10
JAHR = 2026


# ── Hilfs-Setup ──────────────────────────────────────────────────────────────

def _make_year(session: Session) -> None:
    if session.get(Schoolyear, SY) is None:
        session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
        session.flush()


def _make_class_with_plan(session: Session, week_typ: SchoolWeekTyp = SchoolWeekTyp.BERUFSSCHULE) -> dict:
    """Klasse + SchoolPlan + eine SchoolPlanWeek + 2 Trainees ohne Einsaetze."""
    _make_year(session)
    klasse = TraineeClass(name="FISI 2. LJ", berufsschule="JD Schule",
                          unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(klasse)
    session.flush()

    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=SY)
    session.add(plan)
    session.flush()

    week = SchoolPlanWeek(plan_id=plan.id, kw=KW, jahr=JAHR, typ=week_typ)
    session.add(week)

    t1 = Trainee(vorname="Anna", nachname="Apfel", rolle=TraineeRolle.AZUBI, klasse_id=klasse.id)
    t2 = Trainee(vorname="Bernd", nachname="Birne", rolle=TraineeRolle.AZUBI, klasse_id=klasse.id)
    session.add_all([t1, t2])
    session.commit()

    return {
        "klasse_id": klasse.id,
        "plan_id": plan.id,
        "week_id": week.id,
        "t1_id": t1.id,
        "t2_id": t2.id,
    }


# ── 1. sync_class erzeugt AUTO BERUFSSCHULE fuer alle Mitglieder ─────────────

def test_sync_class_creates_auto_bs_for_members(session: Session):
    ids = _make_class_with_plan(session)

    sync_class(session, ids["klasse_id"])

    assignments = session.exec(
        select(Assignment).where(Assignment.trainee_id.in_([ids["t1_id"], ids["t2_id"]]))  # type: ignore[attr-defined]
    ).all()

    assert len(assignments) == 2
    for a in assignments:
        assert a.source == AssignmentSource.AUTO
        assert a.typ == AssignmentTyp.BERUFSSCHULE
        assert a.kw == KW
        assert a.jahr == JAHR
        assert a.schoolyear_id == SY


# ── 2. MANUAL-Eintrag wird nicht ueberschrieben ──────────────────────────────

def test_sync_does_not_overwrite_manual_entry(session: Session):
    ids = _make_class_with_plan(session)

    # Manueller ABTEILUNG-Eintrag in exakt der Schulwoche
    manual = Assignment(
        trainee_id=ids["t1_id"],
        schoolyear_id=SY,
        kw=KW,
        jahr=JAHR,
        typ=AssignmentTyp.ABTEILUNG,
        source=AssignmentSource.MANUAL,
    )
    session.add(manual)
    session.commit()

    sync_class(session, ids["klasse_id"])

    all_a = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["t1_id"])
    ).all()

    # Genau ein Eintrag: der manuelle — kein zusaetzlicher AUTO
    assert len(all_a) == 1
    assert all_a[0].source == AssignmentSource.MANUAL
    assert all_a[0].typ == AssignmentTyp.ABTEILUNG

    # t2 bekommt AUTO (Zelle leer)
    t2_a = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["t2_id"])
    ).all()
    assert len(t2_a) == 1
    assert t2_a[0].source == AssignmentSource.AUTO


# ── 3. Trainee verlaesst Klasse → AUTO-Eintraege werden entfernt ─────────────

def test_sync_removes_auto_when_trainee_leaves_class(session: Session):
    ids = _make_class_with_plan(session)

    # Erst AUTO-Eintraege erzeugen
    sync_class(session, ids["klasse_id"])

    # Sicherstellen, dass AUTO-Eintrag vorhanden ist
    a_before = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["t1_id"])
    ).all()
    assert len(a_before) == 1
    assert a_before[0].source == AssignmentSource.AUTO

    # Trainee aus Klasse entfernen
    t1 = session.get(Trainee, ids["t1_id"])
    t1.klasse_id = None
    session.commit()

    # Sync fuer diesen Trainee
    sync_trainee(session, ids["t1_id"])

    # AUTO-Eintrag muss weg sein
    a_after = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["t1_id"])
    ).all()
    assert len(a_after) == 0

    # t2 bleibt unveraendert
    t2_a = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["t2_id"])
    ).all()
    assert len(t2_a) == 1
    assert t2_a[0].source == AssignmentSource.AUTO


# ── 4. SchoolPlanWeek loeschen → AUTO geloescht, MANUAL bleibt ──────────────

def test_sync_after_week_removed_deletes_auto_keeps_manual(session: Session):
    ids = _make_class_with_plan(session)

    # Zweite Woche und MANUAL-Eintrag in einer anderen Woche
    other_kw = KW + 1
    plan = session.get(SchoolPlan, ids["plan_id"])
    other_week = SchoolPlanWeek(plan_id=plan.id, kw=other_kw, jahr=JAHR, typ=SchoolWeekTyp.BERUFSSCHULE)
    session.add(other_week)
    session.commit()

    sync_class(session, ids["klasse_id"])

    # 2 AUTO-Eintraege pro Trainee (2 Wochen × 2 Trainees = 4 gesamt)
    all_auto = session.exec(
        select(Assignment).where(Assignment.source == AssignmentSource.AUTO)
    ).all()
    assert len(all_auto) == 4

    # Manueller Eintrag in KW other_kw fuer t1 (fuer spaetere Pruefung)
    manual_other = Assignment(
        trainee_id=ids["t1_id"],
        schoolyear_id=SY,
        kw=other_kw + 5,  # noch eine andere Woche ohne Plan
        jahr=JAHR,
        typ=AssignmentTyp.URLAUB,
        source=AssignmentSource.MANUAL,
    )
    session.add(manual_other)
    session.commit()

    # Erste SchoolPlanWeek loeschen (KW = KW)
    week = session.get(SchoolPlanWeek, ids["week_id"])
    session.delete(week)
    session.commit()

    sync_class(session, ids["klasse_id"])

    # Nur noch je 1 AUTO fuer jede Person (fuer other_kw)
    auto_kw = session.exec(
        select(Assignment).where(
            Assignment.source == AssignmentSource.AUTO,
            Assignment.kw == KW,
        )
    ).all()
    assert len(auto_kw) == 0

    auto_other_kw = session.exec(
        select(Assignment).where(
            Assignment.source == AssignmentSource.AUTO,
            Assignment.kw == other_kw,
        )
    ).all()
    assert len(auto_other_kw) == 2

    # Manueller Urlaub bleibt
    manual_check = session.exec(
        select(Assignment).where(
            Assignment.trainee_id == ids["t1_id"],
            Assignment.source == AssignmentSource.MANUAL,
        )
    ).all()
    assert len(manual_check) == 1
    assert manual_check[0].typ == AssignmentTyp.URLAUB


# ── 5. Route POST /trainees/ → AUTO-Eintrag wird angelegt ────────────────────

def test_create_trainee_route_triggers_auto_assignment(client, session: Session):
    _make_year(session)
    klasse = TraineeClass(name="FISI Route Test", berufsschule="JD",
                          unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(klasse)
    session.flush()

    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=SY)
    session.add(plan)
    session.flush()

    session.add(SchoolPlanWeek(plan_id=plan.id, kw=KW, jahr=JAHR, typ=SchoolWeekTyp.BERUFSSCHULE))
    session.commit()

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Felix",
            "nachname": "Fisch",
            "rolle": "AZUBI",
            "sonderfall": "1",
            "klasse_id": str(klasse.id),
            "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    trainee = session.exec(
        select(Trainee).where(Trainee.nachname == "Fisch")
    ).first()
    assert trainee is not None

    auto_a = session.exec(
        select(Assignment).where(
            Assignment.trainee_id == trainee.id,
            Assignment.source == AssignmentSource.AUTO,
        )
    ).all()
    assert len(auto_a) == 1
    assert auto_a[0].typ == AssignmentTyp.BERUFSSCHULE
    assert auto_a[0].kw == KW
    assert auto_a[0].jahr == JAHR


# ── 6. Route POST /klassen/{id}: resynct bestehende Mitglieder, keine Pflege mehr ──

def test_update_class_route_resyncs_existing_members(client, session: Session):
    """POST /klassen/{id} synct AUTO-Eintraege fuer die aktuell (per Anker)
    zugeordneten Mitglieder t1/t2 - unabhaengig von einer Mitglieder-Pflege,
    die es ueber diese Route nicht mehr gibt."""
    ids = _make_class_with_plan(session)

    # Noch keine Assignments vorhanden (sync_class wurde bisher nie aufgerufen)
    assert session.exec(select(Assignment)).all() == []

    r = client.post(
        f"/klassen/{ids['klasse_id']}",
        data={
            "name": "FISI 2. LJ",
            "berufsschule": "JD Schule",
            "unterrichts_typ": "BLOCK_FEST",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    for tid in (ids["t1_id"], ids["t2_id"]):
        auto_a = session.exec(
            select(Assignment).where(
                Assignment.trainee_id == tid,
                Assignment.source == AssignmentSource.AUTO,
            )
        ).all()
        assert len(auto_a) == 1
        assert auto_a[0].typ == AssignmentTyp.BERUFSSCHULE


def test_update_class_route_ignores_mitglied_param(client, session: Session):
    """Ein (z. B. von einem alten Client) mitgeschicktes 'mitglied'-Feld hat
    keine Wirkung mehr - es gibt keinen Mitglieder-Schreibpfad ueber diese Route."""
    ids = _make_class_with_plan(session)

    t3 = Trainee(vorname="Clara", nachname="Citrus", rolle=TraineeRolle.AZUBI, klasse_id=None)
    session.add(t3)
    session.commit()

    r = client.post(
        f"/klassen/{ids['klasse_id']}",
        data={
            "name": "FISI 2. LJ",
            "berufsschule": "JD Schule",
            "unterrichts_typ": "BLOCK_FEST",
            "mitglied": [str(t3.id)],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    t3_check = session.get(Trainee, t3.id)
    assert t3_check.klasse_id is None  # unveraendert

    assert session.exec(
        select(Assignment).where(Assignment.trainee_id == t3.id)
    ).all() == []


# ── 7. UNI-Mapping ───────────────────────────────────────────────────────────

def test_uni_mapping_creates_auto_uni_assignment(session: Session):
    ids = _make_class_with_plan(session, week_typ=SchoolWeekTyp.UNI)

    sync_class(session, ids["klasse_id"])

    assignments = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["t1_id"])
    ).all()
    assert len(assignments) == 1
    assert assignments[0].typ == AssignmentTyp.UNI
    assert assignments[0].source == AssignmentSource.AUTO
