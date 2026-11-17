"""Границы учебных четвертей в демонстрационном календаре."""

from datetime import date

import pytest

from billing_service.study_quarters import quarters_to_invoice, study_quarter_for_date


@pytest.mark.parametrize(
    ("day", "start", "end"),
    [
        (date(2026, 9, 1), date(2026, 9, 1), date(2026, 11, 1)),
        (date(2026, 10, 31), date(2026, 9, 1), date(2026, 11, 1)),
        (date(2026, 11, 1), date(2026, 11, 1), date(2027, 1, 1)),
        (date(2027, 1, 1), date(2027, 1, 1), date(2027, 4, 1)),
        (date(2027, 4, 1), date(2027, 4, 1), date(2027, 6, 1)),
        (date(2027, 5, 31), date(2027, 4, 1), date(2027, 6, 1)),
    ],
)
def test_study_quarter_contains_day(day: date, start: date, end: date) -> None:
    quarter = study_quarter_for_date(day)
    assert quarter is not None
    assert (quarter.start, quarter.end) == (start, end)


@pytest.mark.parametrize("month", [6, 7, 8])
def test_summer_has_no_study_quarter(month: int) -> None:
    assert study_quarter_for_date(date(2027, month, 1)) is None


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 31), [date(2026, 9, 1), date(2026, 11, 1)]),
        (date(2026, 11, 1), [date(2026, 11, 1), date(2027, 1, 1)]),
        (date(2027, 5, 31), [date(2027, 4, 1), date(2027, 9, 1)]),
        (date(2027, 7, 1), [date(2027, 9, 1)]),
    ],
)
def test_invoices_cover_current_and_next_quarter(today, expected):
    assert quarters_to_invoice(today) == expected
