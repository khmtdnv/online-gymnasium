from datetime import date, timedelta

import pytest

from schedule_service.domain.school_calendar import (
    CALENDAR_VERSION,
    HOLIDAYS,
    PUBLIC_HOLIDAYS,
    QUARTERS,
    STUDY_YEAR,
    VACATIONS,
    is_school_day,
    quarter_of,
    school_days,
)

# A full study week of a six-day grade: Monday to Saturday.
FULL_WEEK_SCHOOL_DAYS = 6

# Weekdays of the shortened weeks: 2027-02-23 is a Tuesday and
# 2027-03-08 is a Monday; both are public holidays without lessons.
FEB_23 = date(2027, 2, 23)
MAR_08 = date(2027, 3, 8)


def _each_date(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _week_school_days(day: date) -> list[date]:
    week_start = _week_start(day)
    week_end = week_start + timedelta(days=6)
    return [d for d in school_days() if week_start <= d <= week_end]


def test_calendar_constants_shape() -> None:
    assert CALENDAR_VERSION == 1
    assert len(QUARTERS) == 4
    assert len(VACATIONS) == 3
    assert all(day in HOLIDAYS for day in PUBLIC_HOLIDAYS)
    assert all(
        day in HOLIDAYS for start, end in VACATIONS for day in _each_date(start, end)
    )


def test_quarters_do_not_overlap_and_stay_inside_study_year() -> None:
    year_start, year_end = STUDY_YEAR
    for start, end in QUARTERS:
        assert year_start <= start <= end <= year_end
    for i, (start_a, end_a) in enumerate(QUARTERS):
        for start_b, end_b in QUARTERS[i + 1 :]:
            assert end_a < start_b


def test_vacations_do_not_overlap_quarters() -> None:
    for vacation_start, vacation_end in VACATIONS:
        for quarter_start, quarter_end in QUARTERS:
            assert vacation_end < quarter_start or quarter_end < vacation_start


def test_school_days_are_monday_to_saturday_without_holidays() -> None:
    days = school_days()

    assert days == sorted(set(days))
    holiday_dates = set(HOLIDAYS)
    quarter_weekdays = {
        day
        for start, end in QUARTERS
        for day in _each_date(start, end)
        if day.weekday() < 6
    }
    expected = sorted(quarter_weekdays - holiday_dates)

    assert days == expected
    assert all(is_school_day(day) for day in days)


def test_vacation_days_are_not_school_days() -> None:
    for start, end in VACATIONS:
        for day in _each_date(start, end):
            assert not is_school_day(day)


def test_public_holiday_and_ordinary_sunday_are_not_school_days() -> None:
    for holiday in PUBLIC_HOLIDAYS:
        assert not is_school_day(holiday)

    ordinary_sunday = date(2026, 9, 13)
    assert ordinary_sunday.weekday() == 6
    assert not is_school_day(ordinary_sunday)


def test_full_study_week_has_six_school_days() -> None:
    assert len(_week_school_days(date(2026, 9, 7))) == FULL_WEEK_SCHOOL_DAYS


def test_week_of_feb_23_is_shorter_than_full_week() -> None:
    week = _week_school_days(FEB_23)

    assert len(week) < FULL_WEEK_SCHOOL_DAYS
    assert FEB_23 not in week
    assert not is_school_day(FEB_23)


def test_week_of_mar_08_is_shorter_than_full_week() -> None:
    week = _week_school_days(MAR_08)

    assert len(week) < FULL_WEEK_SCHOOL_DAYS
    assert MAR_08 not in week
    assert not is_school_day(MAR_08)


def test_year_totals_weeks_and_days() -> None:
    days = school_days()

    assert len(days) == 203
    assert len([day for day in days if day.weekday() < 5]) == 171
    assert len({_week_start(day) for day in days}) == 35


def test_quarter_of_at_boundaries_and_inside() -> None:
    for number, (start, end) in enumerate(QUARTERS, start=1):
        assert quarter_of(start) == number
        assert quarter_of(end) == number

    mid_first = QUARTERS[0][0] + timedelta(days=10)
    assert quarter_of(mid_first) == 1


def test_quarter_of_rejects_vacations_and_dates_outside_year() -> None:
    for start, end in VACATIONS:
        middle = start + timedelta(days=(end - start).days // 2)
        for day in (start, middle, end):
            with pytest.raises(ValueError):
                quarter_of(day)

    year_start, year_end = STUDY_YEAR
    with pytest.raises(ValueError):
        quarter_of(year_start - timedelta(days=1))
    with pytest.raises(ValueError):
        quarter_of(year_end + timedelta(days=1))
