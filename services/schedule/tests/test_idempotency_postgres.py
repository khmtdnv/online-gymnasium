from uuid import UUID

"""Реальные гонки ключей и атомарность урока/outbox в отдельной PostgreSQL-БД."""

import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from schedule_service.application.create_lesson import (
    CreateLessonCommand,
    CreateLessonHandler,
)
from schedule_service.application.errors import IdempotencyKeyReuse
from schedule_service.infrastructure.idempotency_repository import (
    SqlAlchemyIdempotencyRepository,
)
from schedule_service.infrastructure.models.idempotency_request import (
    IdempotencyRequestRow,
)
from schedule_service.infrastructure.models.outbox_event import OutboxEventRow
from schedule_service.infrastructure.models.scheduled_lesson import ScheduledLessonRow
from schedule_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


@pytest.fixture(scope="module")
def postgres_url():
    """Разрешает миграции только в явно выбранной отдельной тестовой БД."""
    value = os.environ.get("SCHEDULE_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Нужна отдельная БД SCHEDULE_TEST_DATABASE_URL")
    url = make_url(value)
    if url.drivername != "postgresql+asyncpg" or not (url.database or "").startswith(
        "schedule_test_"
    ):
        raise ValueError("Only schedule_test_* PostgreSQL databases are allowed")
    with patch.dict(os.environ, {"DATABASE_URL": value}):
        command.upgrade(Config("alembic.ini"), "head")
    return value


def create_command(key, request_hash="h1", class_id=10):
    return CreateLessonCommand(
        class_id=class_id,
        teacher_id=UUID(int=100),
        subject_id=1000,
        starts_at=datetime(2026, 10, 15, 10, tzinfo=UTC),
        ends_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        idempotency_key=key,
        request_hash=request_hash,
    )


async def clean_and_count(engine, *, clean=False):
    async with engine.begin() as connection:
        if clean:
            # URL уже проверен fixture; порядок соответствует внешним ключам.
            await connection.execute(text("DELETE FROM idempotency_requests"))
            await connection.execute(text("DELETE FROM outbox_events"))
            await connection.execute(text("DELETE FROM scheduled_lessons"))
        return tuple(
            [
                await connection.scalar(select(func.count()).select_from(model))
                for model in (ScheduledLessonRow, IdempotencyRequestRow, OutboxEventRow)
            ]
        )


@pytest.mark.parametrize("different_hash", [False, True])
def test_concurrent_requests_create_one_lesson_and_two_events(
    postgres_url, different_hash
):
    """Потеря recovery, неверная причина DB-ошибки или повторная запись ломают тест."""

    async def run():
        engine = create_async_engine(postgres_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        barrier = asyncio.Barrier(2)

        class RacingRepository(SqlAlchemyIdempotencyRepository):
            async def claim(self, operation, key, request_hash):
                await barrier.wait()
                await super().claim(operation, key, request_hash)

        class RacingUow(SqlAlchemyUnitOfWork):
            async def __aenter__(self):
                await super().__aenter__()
                self.idempotency = RacingRepository(self._session)
                return self

        try:
            await clean_and_count(engine, clean=True)
            handler = CreateLessonHandler(lambda: RacingUow(sessions))
            results = await asyncio.wait_for(
                asyncio.gather(
                    handler.handle(create_command("race", "h1")),
                    handler.handle(
                        create_command("race", "h2" if different_hash else "h1")
                    ),
                    return_exceptions=True,
                ),
                timeout=15,
            )
            successes = [
                result for result in results if not isinstance(result, BaseException)
            ]
            errors = [result for result in results if isinstance(result, BaseException)]
            assert len(successes) == (1 if different_hash else 2), results
            if different_hash:
                assert len(errors) == 1 and isinstance(
                    errors[0], IdempotencyKeyReuse
                ), results
            else:
                assert successes[0].id == successes[1].id
            assert await clean_and_count(engine) == (1, 1, 2)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_outbox_failure_rolls_back_key_and_lesson_then_same_key_can_retry(postgres_url):
    """Неудача создания не оставляет занятого ключа или частично записанного урока."""

    async def run():
        engine = create_async_engine(postgres_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        class BrokenOutboxUow(SqlAlchemyUnitOfWork):
            async def __aenter__(self):
                await super().__aenter__()

                async def fail(event):
                    raise RuntimeError("outbox unavailable")

                self.outbox.add = fail
                return self

        try:
            await clean_and_count(engine, clean=True)
            with pytest.raises(RuntimeError, match="outbox unavailable"):
                await CreateLessonHandler(lambda: BrokenOutboxUow(sessions)).handle(
                    create_command("retry")
                )
            assert await clean_and_count(engine) == (0, 0, 0)
            result = await CreateLessonHandler(
                lambda: SqlAlchemyUnitOfWork(sessions)
            ).handle(create_command("retry"))
            assert result.id is not None
            assert await clean_and_count(engine) == (1, 1, 2)
        finally:
            await engine.dispose()

    asyncio.run(run())
