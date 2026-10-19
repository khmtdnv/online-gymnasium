"""Проверяет строгие поля команд, queries и внутренних результатов Journal."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from journal_service.application.class_periods import (
    ClassPeriodResult,
    GetCurrentPeriodForStudentQuery,
    ListPeriodsForStudentQuery,
)
from journal_service.application.classes import CreateClassCommand, ListClassesQuery
from journal_service.application.ports.gateway_user_reader import GatewayUserInfo


@pytest.mark.parametrize("value", [0, 101, True, "10"])
def test_list_query_rejects_invalid_limit(value) -> None:
    """Ошибочная пагинация не должна дойти до репозитория."""
    with pytest.raises(ValidationError):
        ListClassesQuery(limit=value)


@pytest.mark.parametrize("value", [-1, 2**63, True, "0"])
def test_list_query_rejects_invalid_offset(value) -> None:
    """OFFSET соответствует диапазону существующего запроса PostgreSQL."""
    with pytest.raises(ValidationError):
        ListPeriodsForStudentQuery(student_id=uuid4(), offset=value)


@pytest.mark.parametrize("value", [1899, 9999, True, "2026"])
def test_create_class_rejects_invalid_year(value) -> None:
    """Ограничения учебного года проверяются при создании команды."""
    with pytest.raises(ValidationError):
        CreateClassCommand(name="7А", study_year=value)


def test_queries_preserve_defaults() -> None:
    """Отсутствующий фильтр и размер страницы сохраняют прежний смысл."""
    query = ListClassesQuery()
    assert (query.study_year, query.limit, query.offset) == (None, 50, 0)


def test_current_query_rejects_string_uuid() -> None:
    """Внутренний query получает разобранный UUID, не JSON-строку."""
    with pytest.raises(ValidationError):
        GetCurrentPeriodForStudentQuery(student_id=str(uuid4()))


def test_gateway_info_rejects_non_boolean_activity() -> None:
    """Неверный тип upstream-признака не должен превращаться в разрешение."""
    with pytest.raises(ValidationError):
        GatewayUserInfo(id=uuid4(), role="student", is_active="false")


def test_period_result_rejects_naive_time() -> None:
    """Серверное время периода должно содержать часовой пояс."""
    with pytest.raises(ValidationError):
        ClassPeriodResult(
            id=1,
            student_id=uuid4(),
            class_id=1,
            joined_at=datetime(2026, 10, 14, tzinfo=UTC).replace(tzinfo=None),
            left_at=None,
        )
