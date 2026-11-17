"""Контракт списка не принимает лишнюю личность и некорректный период."""

from datetime import date

import pytest
from pydantic import ValidationError


def test_personal_homework_query_rejects_spoof_and_invalid_period():
    from gateway_service.application.homework_list import HomeworkPeriod

    query = HomeworkPeriod(date_from=date(2026, 10, 19), date_to=date(2026, 10, 25))
    for update in (
        {"student_id": "other"},
        {"date_to": date(2026, 12, 1)},
        {"offset": -1},
    ):
        with pytest.raises(ValidationError):
            HomeworkPeriod(**(query.model_dump() | update))
