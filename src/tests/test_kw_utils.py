"""Tests fuer app/utils/kw.py: kw_to_friday und week_is_past (deterministisch
ueber den optionalen today-Parameter, unabhaengig vom echten Tagesdatum)."""
from datetime import date

from app.utils.kw import kw_to_friday, week_is_past


def test_kw_to_friday_is_monday_plus_4_days():
    # KW 40/2025: Montag ist 2025-09-29 -> Freitag 2025-10-03
    assert kw_to_friday(40, 2025) == date(2025, 10, 3)


def test_week_is_past_true_when_friday_before_today():
    # Freitag der KW liegt vor "heute" -> Woche ist vollstaendig vorbei
    assert week_is_past(40, 2025, today=date(2025, 10, 10)) is True


def test_week_is_past_false_when_today_is_friday_itself():
    # "Freitag < heute" ist eine strikte Bedingung -> am Freitag selbst
    # gilt die Woche noch NICHT als vollstaendig vergangen.
    assert week_is_past(40, 2025, today=date(2025, 10, 3)) is False


def test_week_is_past_false_for_current_week_midweek():
    # Mittwoch derselben Woche -> Freitag liegt noch in der Zukunft
    assert week_is_past(40, 2025, today=date(2025, 10, 1)) is False


def test_week_is_past_false_for_future_week():
    assert week_is_past(40, 2025, today=date(2025, 1, 1)) is False


def test_week_is_past_true_immediately_after_friday():
    assert week_is_past(40, 2025, today=date(2025, 10, 4)) is True
