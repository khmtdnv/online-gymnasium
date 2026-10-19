"""Проверяет запись периода; PostgreSQL-инварианты проверяются отдельно."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from asyncpg.exceptions import ForeignKeyViolationError, UniqueViolationError
from sqlalchemy.exc import EmulatedDBAPIException, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from journal_service.domain.student_class_period import StudentClassPeriod
from journal_service.infrastructure.student_class_period_repository import (
    SqlAlchemyStudentClassPeriodRepository,
)


def test_create_period_returns_server_fields_without_commit() -> None:
    """ID и joined_at берутся из БД, а клиентские поля не назначают их."""
    session = Mock(spec=AsyncSession)
    rows = []
    session.add.side_effect = rows.append
    joined_at = datetime(2026, 10, 14, 12, tzinfo=UTC)

    async def flush() -> None:
        rows[0].id = 123

    async def refresh(row) -> None:
        row.joined_at = joined_at

    session.flush = AsyncMock(side_effect=flush)
    session.refresh = AsyncMock(side_effect=refresh)
    student = uuid4()
    supplied = StudentClassPeriod(student, 10)
    result = asyncio.run(
        SqlAlchemyStudentClassPeriodRepository(session).create_period(supplied)
    )
    assert result == StudentClassPeriod(student, 10, id=123, joined_at=joined_at)
    assert result is not supplied
    assert supplied.id is None
    assert rows[0].student_id == student
    assert rows[0].class_id == 10
    assert rows[0].left_at is None
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    ("error_type", "constraint", "translated"),
    [
        (UniqueViolationError, "student_class_periods_current_student_unique", True),
        (UniqueViolationError, "student_class_periods_pkey", False),
        (ForeignKeyViolationError, "student_class_periods_class_id_fkey", False),
        (
            ForeignKeyViolationError,
            "student_class_periods_current_student_unique",
            False,
        ),
    ],
)
def test_create_period_recognises_only_named_unique(
    error_type, constraint, translated
) -> None:
    """Не маскирует чужие unique/FK под конфликт текущего класса."""
    from journal_service.application.ports.errors import CurrentPeriodAlreadyExistsError

    driver_error = error_type("constraint failed")
    driver_error.constraint_name = constraint
    failure = IntegrityError(
        "INSERT", {}, EmulatedDBAPIException("failed", driver_error)
    )
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock(side_effect=failure)
    error = CurrentPeriodAlreadyExistsError if translated else IntegrityError
    with pytest.raises(error) as caught:
        asyncio.run(
            SqlAlchemyStudentClassPeriodRepository(session).create_period(
                StudentClassPeriod(uuid4(), 10)
            )
        )
    if translated:
        assert caught.value.__cause__ is failure
    else:
        assert caught.value is failure
    session.refresh.assert_not_awaited()
    session.commit.assert_not_called()


def test_create_period_preserves_non_integrity_failure() -> None:
    """Обычный сбой драйвера сохраняется и не вызывает commit."""
    session = Mock(spec=AsyncSession)
    failure = RuntimeError("connection lost")
    session.flush = AsyncMock(side_effect=failure)
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(
            SqlAlchemyStudentClassPeriodRepository(session).create_period(
                StudentClassPeriod(uuid4(), 10)
            )
        )
    assert caught.value is failure
    session.commit.assert_not_called()
