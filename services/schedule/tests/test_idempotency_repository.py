from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from schedule_service.application.ports.idempotency_repository import IdempotencyRecord
from schedule_service.domain.lesson import Lesson
from schedule_service.infrastructure.idempotency_repository import (
    SqlAlchemyIdempotencyRepository,
)
from schedule_service.infrastructure.models.idempotency_request import (
    IdempotencyRequestRow,
)
from schedule_service.infrastructure.models.scheduled_lesson import ScheduledLessonRow


@pytest.mark.anyio
async def test_repository_claim_returns_none_for_new_key() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = 1
    repository = SqlAlchemyIdempotencyRepository(session)

    result = await repository.claim(
        operation="create_lesson",
        key="k1",
        request_hash="h1",
    )

    assert result is None
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    assert statement.compile().params == {
        "operation": "create_lesson",
        "idempotency_key": "k1",
        "request_hash": "h1",
    }


@pytest.mark.anyio
async def test_repository_get_by_key_returns_existing_completed_lesson() -> None:
    session = AsyncMock(spec=AsyncSession)
    existing_record = IdempotencyRequestRow(
        id=1,
        operation="create_lesson",
        idempotency_key="k1",
        request_hash="h1",
        lesson_id=501,
    )
    existing_lesson = ScheduledLessonRow(
        id=501,
        class_id=10,
        teacher_id=UUID(int=100),
        subject_id=1000,
        starts_at=datetime(2026, 9, 13, 10, tzinfo=UTC),
        ends_at=datetime(2026, 9, 13, 11, tzinfo=UTC),
        status="planned",
        version=1,
    )
    session.scalar.side_effect = [existing_record, existing_lesson]
    repository = SqlAlchemyIdempotencyRepository(session)

    result = await repository.get_by_key(
        operation="create_lesson",
        key="k1",
    )

    assert result == IdempotencyRecord(
        request_hash="h1",
        lesson=Lesson(
            id=501,
            class_id=10,
            teacher_id=UUID(int=100),
            subject_id=1000,
            starts_at=datetime(2026, 9, 13, 10, tzinfo=UTC),
            ends_at=datetime(2026, 9, 13, 11, tzinfo=UTC),
            status="planned",
            version=1,
        ),
    )
    assert session.scalar.await_count == 2


@pytest.mark.anyio
async def test_repository_translates_only_key_unique_conflict() -> None:
    """Только согласованный индекс превращается в конфликт ключа приложения."""
    from schedule_service.application.errors import IdempotencyKeyAlreadyExists

    error = make_integrity_error("23505", "idempotency_requests_operation_key_unique")
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = error
    repository = SqlAlchemyIdempotencyRepository(session)
    with pytest.raises(IdempotencyKeyAlreadyExists) as caught:
        await repository.claim("create_lesson", "k1", "h1")
    assert caught.value.__cause__ is error
    session.rollback.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "code,constraint",
    [
        ("23505", "other_unique"),
        ("23503", "idempotency_requests_operation_key_unique"),
    ],
)
async def test_repository_preserves_unrelated_integrity_error(code, constraint):
    """Чужой unique или FK не должен маскироваться под повтор запроса."""
    error = make_integrity_error(code, constraint)
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = error
    with pytest.raises(IntegrityError) as caught:
        await SqlAlchemyIdempotencyRepository(session).claim(
            "create_lesson", "k1", "h1"
        )
    assert caught.value is error


@pytest.mark.anyio
async def test_repository_returns_none_for_missing_key() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    result = await SqlAlchemyIdempotencyRepository(session).get_by_key(
        "create_lesson", "missing"
    )
    assert result is None


def make_integrity_error(code: str, constraint: str) -> IntegrityError:
    """Повторяет структуру asyncpg→адаптер→SQLAlchemy2.0 без разбора текста."""
    driver_error = Exception("driver")
    driver_error.sqlstate = code
    driver_error.constraint_name = constraint
    adapter_error = Exception("adapter")
    adapter_error.__cause__ = driver_error
    return IntegrityError("INSERT", {}, adapter_error)


@pytest.mark.anyio
async def test_repository_complete_updates_claimed_record() -> None:
    session = AsyncMock(spec=AsyncSession)
    repository = SqlAlchemyIdempotencyRepository(session)
    lesson = Lesson(
        id=501,
        class_id=10,
        teacher_id=UUID(int=100),
        subject_id=1000,
        starts_at=datetime(2026, 9, 13, 10, tzinfo=UTC),
        ends_at=datetime(2026, 9, 13, 11, tzinfo=UTC),
        status="planned",
        version=1,
    )

    await repository.complete(
        operation="create_lesson",
        key="k1",
        lesson=lesson,
    )

    session.execute.assert_awaited_once()
