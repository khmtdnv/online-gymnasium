"""Проверяет модуль-копию календаря: четверти, окна и школьную дату."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from journal_service.domain.study_quarters import (
    CALENDAR_VERSION,
    QUARTERS,
    SCHOOL_TIMEZONE,
    quarter_bounds,
    quarter_of,
    school_today,
    validate_window,
)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 9, 1), 1),
        (date(2026, 10, 30), 1),
        (date(2026, 11, 9), 2),
        (date(2026, 12, 26), 2),
        (date(2027, 1, 11), 3),
        (date(2027, 3, 19), 3),
        (date(2027, 3, 30), 4),
        (date(2027, 5, 29), 4),
    ],
)
def test_quarter_of_returns_number_for_quarter_dates(day: date, expected: int) -> None:
    """Определяет номер четверти для граничных и внутренних дат."""
    assert quarter_of(day) == expected


@pytest.mark.parametrize(
    "day",
    [
        date(2026, 8, 31),
        date(2026, 11, 1),
        date(2026, 10, 31),
        date(2027, 6, 1),
    ],
)
def test_quarter_of_rejects_days_outside_quarters(day: date) -> None:
    """Отклоняет даты до года, на каникулах и после года."""
    with pytest.raises(ValueError):
        quarter_of(day)


@pytest.mark.parametrize("quarter", [1, 2, 3, 4])
def test_quarter_bounds_match_the_copy(quarter: int) -> None:
    """Возвращает границы четверти из копии календаря."""
    assert quarter_bounds(quarter) == QUARTERS[quarter - 1]


@pytest.mark.parametrize("quarter", [0, 5, -1])
def test_quarter_bounds_reject_wrong_numbers(quarter: int) -> None:
    """Отклоняет номера четвертей вне 1–4."""
    with pytest.raises(ValueError):
        quarter_bounds(quarter)


def test_validate_window_accepts_week_and_quarter() -> None:
    """Пропускает окно недели и окно максимальной четверти."""
    validate_window(date(2026, 11, 9), date(2026, 11, 15))
    longest = max(QUARTERS, key=lambda bounds: (bounds[1] - bounds[0]).days)
    validate_window(longest[0], longest[1])


def test_validate_window_rejects_empty_and_year_long_windows() -> None:
    """Отклоняет обратное окно и окно длиннее четверти."""
    with pytest.raises(ValueError):
        validate_window(date(2026, 11, 15), date(2026, 11, 9))
    with pytest.raises(ValueError):
        validate_window(date(2026, 9, 1), date(2027, 5, 29))


def test_school_today_uses_school_timezone() -> None:
    """Возвращает дату момента школьного часового пояса."""
    assert isinstance(school_today(), date)
    utc_moment = datetime(2026, 11, 27, 20, 30, tzinfo=ZoneInfo("UTC"))
    school_moment = utc_moment.astimezone(SCHOOL_TIMEZONE)
    assert school_moment.date() == date(2026, 11, 28)


def test_calendar_copy_is_versioned() -> None:
    """Копия календаря несёт версию для сверки с оригиналом Schedule."""
    assert CALENDAR_VERSION == 1
    assert len(QUARTERS) == 4
