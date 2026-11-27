"""Single source of study-year dates for the 2026/27 school year.

The module has no dependencies outside the standard library: both the
schedule service and the demo data tools import it, exactly like
school_periods. Every consumer that needs a school date (year generator,
verifier, year fingerprint, "current study week" of the tools) must take
dates from here and nowhere else.

Yearly refresh: update the constants below, bump CALENDAR_VERSION and
regenerate the demo data (the runbook step).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

CALENDAR_VERSION = 1

STUDY_YEAR: tuple[date, date] = (date(2026, 9, 1), date(2027, 5, 29))

QUARTERS: tuple[tuple[date, date], ...] = (
    (date(2026, 9, 1), date(2026, 10, 30)),
    (date(2026, 11, 9), date(2026, 12, 26)),
    (date(2027, 1, 11), date(2027, 3, 19)),
    (date(2027, 3, 30), date(2027, 5, 29)),
)

VACATIONS: tuple[tuple[date, date], ...] = (
    (date(2026, 10, 31), date(2026, 11, 8)),
    (date(2026, 12, 27), date(2027, 1, 10)),
    (date(2027, 3, 20), date(2027, 3, 29)),
)

PUBLIC_HOLIDAYS: tuple[date, ...] = (
    date(2027, 2, 23),
    date(2027, 3, 8),
    date(2027, 5, 1),
)


def _each_date(start: date, end: date) -> Iterator[date]:
    """Yields every date from start to end, both ends inclusive."""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _validate_calendar() -> None:
    """Checks the calendar invariants at module load.

    Raises:
        ValueError: if a range ends before it starts, a quarter leaves
            the study year, quarters overlap each other, a vacation
            overlaps a quarter or a public holiday leaves the year.
    """
    year_start, year_end = STUDY_YEAR
    for label, ranges in (("quarter", QUARTERS), ("vacation", VACATIONS)):
        for start, end in ranges:
            if start > end:
                raise ValueError(f"{label} {start}..{end} ends before it starts")
    for start, end in QUARTERS:
        if not year_start <= start <= end <= year_end:
            raise ValueError(f"quarter {start}..{end} leaves the study year")
    for i, (start_a, end_a) in enumerate(QUARTERS):
        for start_b, end_b in QUARTERS[i + 1 :]:
            if start_a <= end_b and start_b <= end_a:
                raise ValueError(
                    f"quarters {start_a}..{end_a} and {start_b}..{end_b} overlap"
                )
    for vacation_start, vacation_end in VACATIONS:
        for quarter_start, quarter_end in QUARTERS:
            if vacation_start <= quarter_end and quarter_start <= vacation_end:
                raise ValueError(
                    f"vacation {vacation_start}..{vacation_end} overlaps"
                    f" quarter {quarter_start}..{quarter_end}"
                )
    for holiday in PUBLIC_HOLIDAYS:
        if not year_start <= holiday <= year_end:
            raise ValueError(f"public holiday {holiday} leaves the study year")


_validate_calendar()

_VACATION_DATES: frozenset[date] = frozenset(
    day for start, end in VACATIONS for day in _each_date(start, end)
)

HOLIDAYS: tuple[date, ...] = tuple(sorted(_VACATION_DATES | frozenset(PUBLIC_HOLIDAYS)))

_SUNDAY = 6

_SCHOOL_DAYS: tuple[date, ...] = tuple(
    day
    for start, end in QUARTERS
    for day in _each_date(start, end)
    if day.weekday() != _SUNDAY
    and day not in _VACATION_DATES
    and day not in PUBLIC_HOLIDAYS
)
_SCHOOL_DAY_DATES: frozenset[date] = frozenset(_SCHOOL_DAYS)


def school_days() -> list[date]:
    """Returns all school days of the study year.

    School days are Mondays to Saturdays inside the quarters, with
    vacations and public holidays excluded. Saturdays stay in the list:
    grades 1-4 run a five-day week and filter them out themselves.

    Returns:
        A new list of dates in chronological order.
    """
    return list(_SCHOOL_DAYS)


def is_school_day(day: date) -> bool:
    """Checks whether the date is a school day.

    Args:
        day: The date to check.

    Returns:
        True for Monday-to-Saturday dates inside a quarter that are
        neither vacation nor public holiday days.
    """
    return day in _SCHOOL_DAY_DATES


def quarter_of(day: date) -> int:
    """Returns the quarter a date belongs to.

    Args:
        day: The date to locate.

    Returns:
        The quarter number from 1 to 4.

    Raises:
        ValueError: if the date is outside every quarter (a vacation,
            before the study year or after it).
    """
    for number, (start, end) in enumerate(QUARTERS, start=1):
        if start <= day <= end:
            return number
    raise ValueError(f"{day.isoformat()} is outside every quarter")
