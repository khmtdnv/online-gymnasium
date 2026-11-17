"""Миграция предметов и календарные границы на отдельной PostgreSQL-БД."""

import asyncio
import os
from datetime import datetime
from unittest.mock import patch
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def test_calendar_and_subject_migration_preserve_lessons(
    teacher_uuid_legacy_database_url,
):
    from schedule_service.domain.subject import Subject
    from schedule_service.infrastructure.lesson_repository import (
        SqlAlchemyLessonRepository,
    )
    from schedule_service.infrastructure.subject_repository import (
        SqlAlchemySubjectRepository,
    )
    from schedule_service.set_subject_names import SubjectNamesInput, set_subject_names

    value = teacher_uuid_legacy_database_url

    def migrate(revision, direction="upgrade"):
        with patch.dict(os.environ, {"DATABASE_URL": value}):
            getattr(command, direction)(Config("alembic.ini"), revision)

    migrate("a92d16c7e503")

    async def insert():
        engine = create_async_engine(value, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                for id, start, end in [
                    (1, "2026-10-18T18:00:00Z", "2026-10-18T19:00:00Z"),
                    (2, "2026-10-18T18:30:00Z", "2026-10-18T19:30:00Z"),
                    (3, "2026-10-24T19:00:00Z", "2026-10-24T20:00:00Z"),
                ]:
                    await connection.execute(
                        text(
                            "INSERT INTO scheduled_lessons(id,class_id,teacher_id,subject_id,starts_at,ends_at,status) VALUES (:id,7,:teacher,3,:start,:end,'canceled')"
                        ),
                        {
                            "id": id,
                            "teacher": UUID(int=1),
                            "start": datetime.fromisoformat(start),
                            "end": datetime.fromisoformat(end),
                        },
                    )
        finally:
            await engine.dispose()

    asyncio.run(insert())
    migrate("head")

    async def check():
        engine = create_async_engine(value, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as session, session.begin():
                lessons = await SqlAlchemyLessonRepository(
                    session
                ).list_calendar_lessons(
                    class_id=7,
                    teacher_id=None,
                    starts_at_from=datetime.fromisoformat("2026-10-19T00:00:00+05:00"),
                    starts_at_until=datetime.fromisoformat("2026-10-25T00:00:00+05:00"),
                )
                assert [row.id for row in lessons] == [2]
                subjects = SqlAlchemySubjectRepository(session)
                assert await subjects.get_many([3, 999]) == [Subject(id=3, name=None)]
                await subjects.set_name(Subject(id=3, name="Математика"))
                with pytest.raises(ValueError, match="overwrite"):
                    await subjects.set_name(Subject(id=3, name="Физика"))
            with patch.dict(os.environ, {"DATABASE_URL": value}):
                with pytest.raises(ValueError, match="Non-demo"):
                    await set_subject_names(
                        SubjectNamesInput(
                            subjects=[{"id": 3, "name": "Математика"}],
                            allowed_teacher_ids=[UUID(int=2)],
                        )
                    )
                await set_subject_names(
                    SubjectNamesInput(
                        subjects=[{"id": 3, "name": "Математика"}],
                        allowed_teacher_ids=[UUID(int=1)],
                    )
                )
            async with sessions() as session:
                assert (await SqlAlchemySubjectRepository(session).get_many([3]))[
                    0
                ].name == "Математика"
                assert (
                    await session.scalar(text("SELECT count(*) FROM scheduled_lessons"))
                    == 3
                )
        finally:
            await engine.dispose()

    asyncio.run(check())
    migrate("a92d16c7e503", "downgrade")
    migrate("head")
