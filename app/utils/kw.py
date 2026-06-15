from datetime import date, timedelta
from collections.abc import Iterator


WEEKDAY_LABELS = {1: "Mo", 2: "Di", 3: "Mi", 4: "Do", 5: "Fr", 6: "Sa", 7: "So"}
WEEKDAY_FULL = {
    1: "Montag", 2: "Dienstag", 3: "Mittwoch", 4: "Donnerstag",
    5: "Freitag", 6: "Samstag", 7: "Sonntag",
}


def parse_weekdays(csv: str) -> list[int]:
    """ "2,3" -> [2, 3] (ISO-Wochentage Mo=1..So=7)."""
    if not csv:
        return []
    return [int(x) for x in csv.split(",") if x.strip().isdigit()]


def format_weekdays(csv: str, full: bool = False, halbtag: int | None = None) -> str:
    """ "2,3" -> "Di, Mi" (voll: "Dienstag, Mittwoch"); markiert den Halbtag."""
    labels = WEEKDAY_FULL if full else WEEKDAY_LABELS
    parts = []
    for d in parse_weekdays(csv):
        s = labels.get(d, str(d))
        if halbtag and d == halbtag:
            s += " (halbtags)"
        parts.append(s)
    return ", ".join(parts)


def kw_to_monday(kw: int, year: int) -> date:
    """ISO 8601 calendar week → Monday of that week."""
    return date.fromisocalendar(year, kw, 1)


def monday_to_kw(d: date) -> tuple[int, int]:
    """Date → (kw, year) tuple."""
    iso = d.isocalendar()
    return iso.week, iso.year


def iter_schoolyear_weeks(
    start_kw: int,
    start_year: int,
    end_kw: int,
    end_year: int,
) -> Iterator[tuple[int, int]]:
    """Yields (kw, year) for every ISO week from start to end inclusive."""
    current = kw_to_monday(start_kw, start_year)
    end_monday = kw_to_monday(end_kw, end_year)
    while current <= end_monday:
        iso = current.isocalendar()
        yield iso.week, iso.year
        current += timedelta(weeks=1)


def iter_kw_range(
    start_kw: int,
    start_year: int,
    end_kw: int,
    end_year: int,
) -> Iterator[tuple[int, int]]:
    """Yields (kw, year) for every ISO week in [start, end] inclusive."""
    yield from iter_schoolyear_weeks(start_kw, start_year, end_kw, end_year)


def holiday_contains_week(
    h_start_kw: int,
    h_start_year: int,
    h_end_kw: int,
    h_end_year: int,
    kw: int,
    jahr: int,
) -> bool:
    """True if (kw, jahr) falls within the given holiday range (inclusive)."""
    monday = kw_to_monday(kw, jahr)
    return kw_to_monday(h_start_kw, h_start_year) <= monday <= kw_to_monday(h_end_kw, h_end_year)
