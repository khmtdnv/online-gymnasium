"""Проверяет перенос серверной границы в новый период без commit репозитория."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from journal_service.domain.student_class_period import StudentClassPeriod
from journal_service.infrastructure.student_class_period_repository import (
    SqlAlchemyStudentClassPeriodRepository,
)


def test_create_period_preserves_explicit_transfer_boundary() -> None:
    """Потеря переданной даты создаст разрыв между закрытием и вступлением."""
    boundary = datetime(2026, 10, 16, 12, 30, tzinfo=UTC)
    session = Mock(spec=AsyncSession)
    rows = []
    session.add.side_effect = rows.append

    async def flush() -> None:
        rows[0].id = 20

    session.flush = AsyncMock(side_effect=flush)
    session.refresh = AsyncMock()
    period = StudentClassPeriod(uuid4(), 2, joined_at=boundary)
    result = asyncio.run(
        SqlAlchemyStudentClassPeriodRepository(session).create_period(period)
    )
    assert result.joined_at == boundary
    assert result.id == 20
    assert rows[0].joined_at == boundary
    session.commit.assert_not_called()
