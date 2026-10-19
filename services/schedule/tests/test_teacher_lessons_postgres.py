"""Реальный SQL и обратимость индекса на выделенной PostgreSQL-БД."""

import asyncio
import os
import subprocess
import sys
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def test_teacher_query_boundaries_and_index_migration(teacher_uuid_legacy_database_url):
    from schedule_service.infrastructure.lesson_repository import (
        SqlAlchemyLessonRepository,
    )

    value = teacher_uuid_legacy_database_url

    def migrate(revision, direction="upgrade"):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", direction, revision],
            env={**os.environ, "DATABASE_URL": value},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    migrate("head")

    async def check(insert=False, index=True):
        engine = create_async_engine(value, poolclass=NullPool)
        try:
            if insert:
                async with engine.begin() as connection:
                    for id, teacher, start, end in [
                        (1, 1, "2026-10-18 23:30Z", "2026-10-19 00:30Z"),
                        (2, 1, "2026-10-19 10:00Z", "2026-10-19 11:00Z"),
                        (3, 1, "2026-10-19 10:00Z", "2026-10-19 11:00Z"),
                        (4, 1, "2026-10-18 23:00Z", "2026-10-19 00:00Z"),
                        (5, 1, "2026-10-26 00:00Z", "2026-10-26 01:00Z"),
                        (6, 2, "2026-10-19 12:00Z", "2026-10-19 13:00Z"),
                    ]:
                        await connection.execute(
                            text(
                                "INSERT INTO scheduled_lessons (id,class_id,teacher_id,subject_id,starts_at,ends_at,status) VALUES (:id,7,:teacher,3,CAST(:start AS timestamptz),CAST(:end AS timestamptz),'canceled')"
                            ),
                            {
                                "id": id,
                                "teacher": UUID(int=teacher),
                                "start": datetime.fromisoformat(start),
                                "end": datetime.fromisoformat(end),
                            },
                        )
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                rows = await SqlAlchemyLessonRepository(session).list_for_teacher(
                    teacher_id=UUID(int=1),
                    date_from=date(2026, 10, 19),
                    date_to=date(2026, 10, 25),
                )
                assert [row.id for row in rows] == [1, 2, 3]
                assert all(row.status == "canceled" for row in rows)
            async with engine.connect() as connection:
                present = await connection.scalar(
                    text(
                        "SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname='scheduled_lessons_teacher_starts_id_idx'"
                    )
                )
                assert bool(present) == index
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM scheduled_lessons")
                    )
                    == 6
                )
        finally:
            await engine.dispose()

    asyncio.run(check(insert=True))
    migrate("d7a8046e2b91", "downgrade")
    try:
        asyncio.run(check(index=False))
    finally:
        migrate("head")
    asyncio.run(check())
