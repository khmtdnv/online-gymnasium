from datetime import date
from typing import Never

import pytest

from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.domain.lesson import Lesson


class NoopScheduleCache:
    async def get(self, *, class_id: int, day: date) -> list[Lesson] | None:
        return None

    async def get_generation(self, *, class_id: int, day: date) -> int:
        return 0

    async def try_acquire_fill_lock(
        self,
        *,
        class_id: int,
        day: date,
        token: str,
        ttl_ms: int,
    ) -> bool:
        return True

    async def release_fill_lock(
        self,
        *,
        class_id: int,
        day: date,
        token: str,
    ) -> None:
        return None

    async def set_if_generation(
        self,
        *,
        class_id: int,
        day: date,
        lessons: list[Lesson],
        ttl_seconds: int,
        expected_generation: int,
    ) -> bool:
        return True

    async def invalidate(self, *, class_id: int, days: tuple[date, ...]) -> None:
        return None

    async def aclose(self) -> None:
        return None


@pytest.fixture
def unused_uow_factory() -> UnitOfWorkFactory:
    def factory() -> Never:
        raise AssertionError("This test must not create a UnitOfWork")

    return factory


@pytest.fixture
def teacher_uuid_legacy_database_url():
    """Создаёт старую схему только в явно выделенной тестовой PostgreSQL-БД."""
    import os
    from unittest.mock import patch

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    value = os.environ.get("SCHEDULE_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Нужна отдельная SCHEDULE_TEST_DATABASE_URL")
    url = make_url(value)
    if url.drivername != "postgresql+asyncpg" or not (url.database or "").startswith(
        "schedule_test_"
    ):
        raise ValueError("Only schedule_test_* PostgreSQL databases are allowed")

    def reset():
        import asyncio

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        async def clear():
            engine = create_async_engine(value, poolclass=NullPool)
            try:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "DROP TABLE IF EXISTS subjects, idempotency_requests, outbox_events, scheduled_lessons, alembic_version"
                        )
                    )
            finally:
                await engine.dispose()

        asyncio.run(clear())
        with patch.dict(os.environ, {"DATABASE_URL": value}):
            command.upgrade(Config("alembic.ini"), "c9c13a8d994d")

    reset()
    try:
        yield value
    finally:
        # Ни один сценарий UUID не оставляет изменённую схему следующим тестам.
        reset()
