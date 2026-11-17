from uuid import UUID

"""Проверяет recovery обработчика после закрытия неудавшейся транзакции."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from schedule_service.application.create_lesson import (
    CreateLessonCommand,
    CreateLessonHandler,
)
from schedule_service.application.errors import IdempotencyKeyReuse
from schedule_service.application.ports.idempotency_repository import IdempotencyRecord
from schedule_service.domain.lesson import Lesson


@pytest.mark.anyio
@pytest.mark.parametrize("stored_hash", ["h1", "different"])
async def test_duplicate_is_read_only_after_failed_uow_has_exited(stored_hash):
    """Преждевременное чтение, повторные записи или потеря hash-проверки ломают тест."""
    from schedule_service.application.errors import IdempotencyKeyAlreadyExists

    trace = []
    lesson = Lesson(
        id=501,
        class_id=1,
        teacher_id=UUID(int=2),
        subject_id=3,
        starts_at=datetime(2026, 10, 15, 10, tzinfo=UTC),
        ends_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
    )
    write = Mock()
    write.__aenter__ = AsyncMock(return_value=write)

    async def finish(exc_type, exc, tb):
        assert exc_type is IdempotencyKeyAlreadyExists
        trace.append("write rolled back and closed")

    write.__aexit__ = AsyncMock(side_effect=finish)
    write.idempotency.claim = AsyncMock(side_effect=IdempotencyKeyAlreadyExists)
    write.lessons.add = AsyncMock(side_effect=AssertionError("Duplicate lesson"))
    write.outbox.add = AsyncMock(side_effect=AssertionError("Duplicate event"))

    read = Mock()
    read.__aenter__ = AsyncMock(return_value=read)
    read.__aexit__ = AsyncMock(return_value=None)

    async def get_by_key(operation, key):
        assert trace == ["write rolled back and closed"]
        assert (operation, key) == ("create_lesson", "k1")
        trace.append("existing result read")
        return IdempotencyRecord(request_hash=stored_hash, lesson=lesson)

    read.idempotency.get_by_key = AsyncMock(side_effect=get_by_key)
    read.lessons.add = AsyncMock(side_effect=AssertionError("Duplicate lesson"))
    read.outbox.add = AsyncMock(side_effect=AssertionError("Duplicate event"))
    factory = Mock(side_effect=[write, read])
    handler = CreateLessonHandler(factory)
    command = CreateLessonCommand(
        class_id=1,
        teacher_id=UUID(int=2),
        subject_id=3,
        starts_at=lesson.starts_at,
        ends_at=lesson.ends_at,
        idempotency_key="k1",
        request_hash="h1",
    )

    if stored_hash == "h1":
        assert await handler.handle(command) is lesson
    else:
        with pytest.raises(IdempotencyKeyReuse):
            await handler.handle(command)
    assert trace == ["write rolled back and closed", "existing result read"]
