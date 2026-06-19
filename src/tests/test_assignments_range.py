"""Tests for range-based assignment creation and hierarchy logic."""
import pytest
from sqlmodel import Session

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
    UnterrichtsTyp,
)
from app.routers.assignments import TYP_RANG, _resolve_range
from app.utils.kw import iter_kw_range


# ── iter_kw_range ─────────────────────────────────────────────────

def test_single_week():
    assert list(iter_kw_range(10, 2025, 10, 2025)) == [(10, 2025)]


def test_multi_week_same_year():
    result = list(iter_kw_range(40, 2025, 42, 2025))
    assert result == [(40, 2025), (41, 2025), (42, 2025)]


def test_year_crossover():
    result = list(iter_kw_range(52, 2025, 2, 2026))
    assert (52, 2025) in result
    assert (1, 2026) in result
    assert (2, 2026) in result
    assert len(result) == 3


def test_kw53_year_2026():
    # 2026 has KW 53; first week of 2027 is KW 1
    result = list(iter_kw_range(52, 2026, 2, 2027))
    assert (52, 2026) in result
    assert (53, 2026) in result
    assert (1, 2027) in result
    assert (2, 2027) in result
    assert len(result) == 4


# ── TYP_RANG values ───────────────────────────────────────────────

def test_rang_order():
    assert TYP_RANG[AssignmentTyp.BERUFSSCHULE] == TYP_RANG[AssignmentTyp.UNI] == 3
    assert TYP_RANG[AssignmentTyp.URLAUB] == 2
    assert TYP_RANG[AssignmentTyp.ABTEILUNG] == 1
    assert TYP_RANG[AssignmentTyp.FREI] == 0


# ── _resolve_range helpers ────────────────────────────────────────

def _make_schoolyear(session: Session) -> str:
    sy = Schoolyear(id="2025-2026", start_kw=36, start_year=2025, end_kw=35, end_year=2026)
    session.add(sy)
    session.commit()
    return sy.id


def _make_trainee(session: Session, klasse_id=None) -> int:
    t = Trainee(vorname="Max", nachname="Muster", rolle="AZUBI", klasse_id=klasse_id)
    session.add(t)
    session.commit()
    return t.id


def _make_assignment(session: Session, trainee_id: int, sy_id: str, kw: int, jahr: int,
                     typ: AssignmentTyp) -> Assignment:
    a = Assignment(
        trainee_id=trainee_id, schoolyear_id=sy_id, kw=kw, jahr=jahr,
        typ=typ, source=AssignmentSource.MANUAL,
    )
    session.add(a)
    session.commit()
    return a


def _make_school_week(session: Session, trainee_id: int, sy_id: str, kw: int, jahr: int) -> None:
    t = session.get(Trainee, trainee_id)
    klasse = TraineeClass(name="FIAE2", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(klasse)
    session.flush()
    t.klasse_id = klasse.id
    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=sy_id)
    session.add(plan)
    session.flush()
    session.add(SchoolPlanWeek(plan_id=plan.id, kw=kw, jahr=jahr, typ=SchoolWeekTyp.BERUFSSCHULE))
    session.commit()


# ── _resolve_range tests ──────────────────────────────────────────

def test_empty_week_creates(session: Session):
    sy = _make_schoolyear(session)
    tid = _make_trainee(session)
    to_create, to_override, skipped, pending = _resolve_range(
        session, tid, sy, [(10, 2025)], AssignmentTyp.ABTEILUNG, frozenset()
    )
    assert to_create == [(10, 2025)]
    assert not to_override
    assert not skipped
    assert not pending


def test_higher_rank_overrides(session: Session):
    sy = _make_schoolyear(session)
    tid = _make_trainee(session)
    _make_assignment(session, tid, sy, 10, 2025, AssignmentTyp.ABTEILUNG)  # rank 1
    to_create, to_override, skipped, pending = _resolve_range(
        session, tid, sy, [(10, 2025)], AssignmentTyp.BERUFSSCHULE, frozenset()  # rank 3
    )
    assert not to_create
    assert len(to_override) == 1
    assert to_override[0][0] == 10
    assert not skipped
    assert not pending


def test_lower_rank_skipped(session: Session):
    sy = _make_schoolyear(session)
    tid = _make_trainee(session)
    _make_assignment(session, tid, sy, 10, 2025, AssignmentTyp.BERUFSSCHULE)  # rank 3
    to_create, to_override, skipped, pending = _resolve_range(
        session, tid, sy, [(10, 2025)], AssignmentTyp.ABTEILUNG, frozenset()  # rank 1
    )
    assert not to_create
    assert not to_override
    assert len(skipped) == 1
    assert not pending


def test_same_rank_triggers_pending(session: Session):
    sy = _make_schoolyear(session)
    tid = _make_trainee(session)
    _make_assignment(session, tid, sy, 10, 2025, AssignmentTyp.ABTEILUNG)  # rank 1
    to_create, to_override, skipped, pending = _resolve_range(
        session, tid, sy, [(10, 2025)], AssignmentTyp.ABTEILUNG, frozenset()
    )
    assert not to_create
    assert not to_override
    assert not skipped
    assert len(pending) == 1


def test_same_rank_with_override_key_overrides(session: Session):
    sy = _make_schoolyear(session)
    tid = _make_trainee(session)
    _make_assignment(session, tid, sy, 10, 2025, AssignmentTyp.ABTEILUNG)
    to_create, to_override, skipped, pending = _resolve_range(
        session, tid, sy, [(10, 2025)], AssignmentTyp.ABTEILUNG, frozenset({"10:2025"})
    )
    assert not to_create
    assert len(to_override) == 1
    assert not skipped
    assert not pending


def test_urlaub_on_school_week_skipped(session: Session):
    sy = _make_schoolyear(session)
    tid = _make_trainee(session)
    _make_school_week(session, tid, sy, 41, 2025)
    to_create, to_override, skipped, pending = _resolve_range(
        session, tid, sy, [(41, 2025)], AssignmentTyp.URLAUB, frozenset()
    )
    assert not to_create
    assert not to_override
    assert len(skipped) == 1
    assert skipped[0][2] == "Schulwoche"
    assert not pending


def test_urlaub_on_non_school_week_creates(session: Session):
    sy = _make_schoolyear(session)
    tid = _make_trainee(session)
    to_create, to_override, skipped, pending = _resolve_range(
        session, tid, sy, [(41, 2025)], AssignmentTyp.URLAUB, frozenset()
    )
    assert to_create == [(41, 2025)]


def test_range_mixed_outcomes(session: Session):
    sy = _make_schoolyear(session)
    tid = _make_trainee(session)
    _make_assignment(session, tid, sy, 11, 2025, AssignmentTyp.BERUFSSCHULE)  # rank 3, skip
    _make_assignment(session, tid, sy, 12, 2025, AssignmentTyp.FREI)          # rank 0, override
    # KW 10: empty → create, KW 11: BS higher → skip, KW 12: FREI lower → override
    kw_list = [(10, 2025), (11, 2025), (12, 2025)]
    to_create, to_override, skipped, pending = _resolve_range(
        session, tid, sy, kw_list, AssignmentTyp.ABTEILUNG, frozenset()
    )
    assert to_create == [(10, 2025)]
    assert len(to_override) == 1 and to_override[0][0] == 12
    assert len(skipped) == 1 and skipped[0][0] == 11
    assert not pending
