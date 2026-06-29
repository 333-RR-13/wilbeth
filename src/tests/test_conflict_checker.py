import pytest
from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentTyp,
    Department,
    SchoolHoliday,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.services.conflict_checker import ConflictKind, find_conflicts

YEAR_ID = "2025-2026"


def _setup_base(session: Session):
    """Create year + class + trainee + empty school plan."""
    year = Schoolyear(id=YEAR_ID, start_kw=36, start_year=2025, end_kw=35, end_year=2026)
    session.add(year)

    klasse = TraineeClass(
        name="FI-25",
        berufsschule="BS Karlsruhe",
        unterrichts_typ=UnterrichtsTyp.BLOCK_FEST,
    )
    session.add(klasse)
    session.flush()

    trainee = Trainee(
        vorname="Max",
        nachname="Mustermann",
        rolle=TraineeRolle.AZUBI,
        klasse_id=klasse.id,
        aktiv=True,
    )
    session.add(trainee)
    session.flush()

    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=YEAR_ID)
    session.add(plan)
    session.flush()

    return year, klasse, trainee, plan


# ── No conflicts ─────────────────────────────────────────────────────────────

def test_no_assignments_no_conflicts(session):
    _setup_base(session)
    assert find_conflicts(session, YEAR_ID) == []


def test_abteilung_outside_school_week_no_conflict(session):
    year, klasse, trainee, plan = _setup_base(session)

    # School week at KW 10, assignment at KW 11 → no conflict
    session.add(SchoolPlanWeek(plan_id=plan.id, kw=10, jahr=2026, typ=SchoolWeekTyp.BERUFSSCHULE))
    dept = Department(code="IT", name="IT")
    session.add(dept)
    session.flush()

    session.add(Assignment(
        trainee_id=trainee.id, schoolyear_id=YEAR_ID,
        kw=11, jahr=2026, typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id,
    ))
    session.flush()

    assert find_conflicts(session, YEAR_ID) == []


# ── SCHUL_KONFLIKT ────────────────────────────────────────────────────────────

def test_schul_konflikt_abteilung_in_bs_week(session):
    year, klasse, trainee, plan = _setup_base(session)

    session.add(SchoolPlanWeek(plan_id=plan.id, kw=10, jahr=2026, typ=SchoolWeekTyp.BERUFSSCHULE))
    dept = Department(code="IT", name="IT-Abt")
    session.add(dept)
    session.flush()

    session.add(Assignment(
        trainee_id=trainee.id, schoolyear_id=YEAR_ID,
        kw=10, jahr=2026, typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id,
    ))
    session.flush()

    conflicts = find_conflicts(session, YEAR_ID)
    assert any(c.kind == ConflictKind.SCHUL_KONFLIKT and c.trainee_id == trainee.id for c in conflicts)


def test_schul_konflikt_urlaub_in_bs_week(session):
    """URLAUB in a school week is a hard conflict."""
    year, klasse, trainee, plan = _setup_base(session)

    session.add(SchoolPlanWeek(plan_id=plan.id, kw=10, jahr=2026, typ=SchoolWeekTyp.BERUFSSCHULE))
    session.flush()

    session.add(Assignment(
        trainee_id=trainee.id, schoolyear_id=YEAR_ID,
        kw=10, jahr=2026, typ=AssignmentTyp.URLAUB,
    ))
    session.flush()

    conflicts = find_conflicts(session, YEAR_ID)
    assert any(c.kind == ConflictKind.SCHUL_KONFLIKT and c.trainee_id == trainee.id for c in conflicts)


def test_no_schul_konflikt_for_trainee_without_class(session):
    """Trainees without a class can't have SCHUL_KONFLIKT (no plan to match)."""
    year, klasse, _, plan = _setup_base(session)

    unassigned = Trainee(
        vorname="Karl", nachname="Ohne",
        rolle=TraineeRolle.PRAKTIKANT, klasse_id=None, aktiv=True,
    )
    session.add(unassigned)
    session.add(SchoolPlanWeek(plan_id=plan.id, kw=10, jahr=2026, typ=SchoolWeekTyp.BERUFSSCHULE))
    session.flush()

    dept = Department(code="HR", name="HR")
    session.add(dept)
    session.flush()

    session.add(Assignment(
        trainee_id=unassigned.id, schoolyear_id=YEAR_ID,
        kw=10, jahr=2026, typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id,
    ))
    session.flush()

    conflicts = find_conflicts(session, YEAR_ID)
    assert not any(c.kind == ConflictKind.SCHUL_KONFLIKT for c in conflicts)


# ── FERIEN_KONFLIKT ───────────────────────────────────────────────────────────

def test_ferien_konflikt_bs_in_holiday(session):
    year, klasse, trainee, plan = _setup_base(session)

    session.add(SchoolHoliday(
        schoolyear_id=YEAR_ID, name="Weihnachtsferien",
        start_kw=1, start_year=2026,
        end_kw=5, end_year=2026,
    ))
    session.flush()

    session.add(Assignment(
        trainee_id=trainee.id, schoolyear_id=YEAR_ID,
        kw=3, jahr=2026, typ=AssignmentTyp.BERUFSSCHULE,
    ))
    session.flush()

    conflicts = find_conflicts(session, YEAR_ID)
    assert any(c.kind == ConflictKind.FERIEN_KONFLIKT and c.trainee_id == trainee.id for c in conflicts)


def test_ferien_konflikt_uni_in_holiday(session):
    year, klasse, trainee, plan = _setup_base(session)

    session.add(SchoolHoliday(
        schoolyear_id=YEAR_ID, name="Sommerferien",
        start_kw=28, start_year=2026,
        end_kw=32, end_year=2026,
    ))
    session.flush()

    session.add(Assignment(
        trainee_id=trainee.id, schoolyear_id=YEAR_ID,
        kw=30, jahr=2026, typ=AssignmentTyp.UNI,
    ))
    session.flush()

    conflicts = find_conflicts(session, YEAR_ID)
    assert any(c.kind == ConflictKind.FERIEN_KONFLIKT for c in conflicts)


def test_no_ferien_konflikt_outside_holiday(session):
    year, klasse, trainee, plan = _setup_base(session)

    session.add(SchoolHoliday(
        schoolyear_id=YEAR_ID, name="Osterferien",
        start_kw=15, start_year=2026,
        end_kw=16, end_year=2026,
    ))
    session.flush()

    # Assignment is BEFORE the holiday
    session.add(Assignment(
        trainee_id=trainee.id, schoolyear_id=YEAR_ID,
        kw=14, jahr=2026, typ=AssignmentTyp.BERUFSSCHULE,
    ))
    session.flush()

    assert find_conflicts(session, YEAR_ID) == []


# ── DOPPELBELEGUNG ────────────────────────────────────────────────────────────

def _make_second_trainee(session: Session) -> Trainee:
    klasse2 = TraineeClass(name="FI-24", berufsschule="BS KA", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(klasse2)
    session.flush()
    t2 = Trainee(vorname="Anna", nachname="Schmidt", rolle=TraineeRolle.AZUBI, klasse_id=klasse2.id, aktiv=True)
    session.add(t2)
    session.flush()
    return t2


def test_doppelbelegung_detected(session):
    year, klasse, trainee, plan = _setup_base(session)
    t2 = _make_second_trainee(session)

    dept = Department(code="SEC", name="Security", erlaubt_mehrfachbelegung=False)
    session.add(dept)
    session.flush()

    session.add(Assignment(trainee_id=trainee.id, schoolyear_id=YEAR_ID, kw=15, jahr=2026, typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id))
    session.add(Assignment(trainee_id=t2.id, schoolyear_id=YEAR_ID, kw=15, jahr=2026, typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id))
    session.flush()

    conflicts = find_conflicts(session, YEAR_ID)
    assert any(c.kind == ConflictKind.DOPPELBELEGUNG and c.kw == 15 for c in conflicts)


def test_doppelbelegung_not_detected_when_allowed(session):
    """erlaubt_mehrfachbelegung=True suppresses DOPPELBELEGUNG."""
    year, klasse, trainee, plan = _setup_base(session)
    t2 = _make_second_trainee(session)

    dept = Department(code="SVC", name="Service", erlaubt_mehrfachbelegung=True)
    session.add(dept)
    session.flush()

    session.add(Assignment(trainee_id=trainee.id, schoolyear_id=YEAR_ID, kw=20, jahr=2026, typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id))
    session.add(Assignment(trainee_id=t2.id, schoolyear_id=YEAR_ID, kw=20, jahr=2026, typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id))
    session.flush()

    conflicts = find_conflicts(session, YEAR_ID)
    assert not any(c.kind == ConflictKind.DOPPELBELEGUNG for c in conflicts)


def test_single_trainee_per_dept_no_doppelbelegung(session):
    year, klasse, trainee, plan = _setup_base(session)

    dept = Department(code="NET", name="Netz", erlaubt_mehrfachbelegung=False)
    session.add(dept)
    session.flush()

    # Only one trainee in this dept/week
    session.add(Assignment(trainee_id=trainee.id, schoolyear_id=YEAR_ID, kw=22, jahr=2026, typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id))
    session.flush()

    conflicts = find_conflicts(session, YEAR_ID)
    assert not any(c.kind == ConflictKind.DOPPELBELEGUNG for c in conflicts)
