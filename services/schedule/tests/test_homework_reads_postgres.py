"""Проверяем фильтры owner-read на реальной отдельной PostgreSQL-БД."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx2 as httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def test_next_lesson_real_filters_and_http():
    from schedule_service.app import create_app
    from schedule_service.config import Settings
    from schedule_service.infrastructure.models.scheduled_lesson import (
        ScheduledLessonRow,
    )
    from schedule_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    value = os.getenv("SCHEDULE_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Requires separate SCHEDULE_TEST_DATABASE_URL")
    url = make_url(value)
    if url.drivername != "postgresql+asyncpg" or not (url.database or "").startswith(
        "schedule_test_"
    ):
        pytest.fail("Only schedule_test_* PostgreSQL allowed")

    async def run():
        engine = create_async_engine(
            value,
            poolclass=NullPool,
            execution_options={"schema_translate_map": {None: "homework_read_probe"}},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        start = datetime(2026, 11, 1, 10, tzinfo=UTC)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
                await conn.execute(text("CREATE SCHEMA homework_read_probe"))
                await conn.run_sync(ScheduledLessonRow.__table__.create)
            async with sessions.begin() as session:
                for id, class_id, subject_id, delta, status in [
                    (11, 7, 3, 0, "planned"),
                    (12, 7, 3, -2, "planned"),
                    (13, 7, 3, 1, "canceled"),
                    (14, 8, 3, 1, "planned"),
                    (15, 7, 4, 2, "planned"),
                    (16, 7, 3, 3, "planned"),
                    (17, 7, 3, 4, "planned"),
                ]:
                    moment = start + timedelta(hours=delta)
                    session.add(
                        ScheduledLessonRow(
                            id=id,
                            class_id=class_id,
                            subject_id=subject_id,
                            teacher_id=UUID(int=class_id),
                            starts_at=moment,
                            ends_at=moment + timedelta(minutes=45),
                            status=status,
                        )
                    )
            settings = Settings(
                database_url=value,
                redis_url="redis://test",
                rabbitmq_url="amqp://test",
                homework_service_token="test-homework",
                _env_file=None,
            )
            app = create_app(
                settings, engine, lambda: SqlAlchemyUnitOfWork(sessions), None
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://schedule"
            ) as client:
                headers = {"Authorization": "Bearer test-homework"}
                batch = await client.post(
                    "/internal/lessons/lookup",
                    headers=headers,
                    json={"lesson_ids": [16, 999, 13]},
                )
                assert batch.status_code == 200
                assert [row["id"] for row in batch.json()] == [13, 16]
                assert batch.json()[0]["status"] == "canceled"
                result = await client.get("/internal/lessons/11/next", headers=headers)
                assert result.status_code == 200
                assert result.json()["id"] == 16
                assert (
                    await client.get("/internal/lessons/17/next", headers=headers)
                ).json() is None
                assert (
                    await client.get("/internal/lessons/13", headers=headers)
                ).json()["status"] == "canceled"
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DROP SCHEMA IF EXISTS homework_read_probe CASCADE")
                )
            await engine.dispose()

    asyncio.run(run())
