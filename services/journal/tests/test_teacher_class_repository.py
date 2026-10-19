"""Проверяет связь и SQL чтения; настоящие ограничения PG — в integration."""

import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from asyncpg.exceptions import ForeignKeyViolationError, UniqueViolationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import EmulatedDBAPIException, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from journal_service.infrastructure.models.school_class import ClassRow

TEACHER = UUID("8df96b7a-7d30-44e7-b577-f6581300e101")


def test_assign_list_and_remove_use_exact_pair_and_preserve_other_teachers():
    from journal_service.infrastructure.models.teacher_class import TeacherClassRow
    from journal_service.infrastructure.teacher_class_repository import (
        SqlAlchemyTeacherClassRepository,
    )

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def functions(connection, _):
        connection.create_function("char_length", 1, len)
        connection.create_function("btrim", 1, lambda x: x.strip(" "))

    ClassRow.__table__.create(engine)
    TeacherClassRow.__table__.create(engine)
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    ClassRow(id=7, name="7А", study_year=2026),
                    ClassRow(id=8, name="7Б", study_year=2026),
                ]
            )
            db.flush()
            session = Mock(spec=AsyncSession)
            session.add.side_effect = db.add
            session.flush = AsyncMock(side_effect=db.flush)
            session.execute = AsyncMock(side_effect=db.execute)
            session.scalars = AsyncMock(side_effect=db.scalars)
            repository = SqlAlchemyTeacherClassRepository(session)

            async def scenario():
                await repository.add(TEACHER, 8)
                await repository.add(TEACHER, 7)
                await repository.add(UUID(int=2), 7)
                assert [
                    x.id
                    for x in await repository.list_classes_for_teacher(TEACHER, 1, 1)
                ] == [8]
                assert [
                    x.name
                    for x in await repository.list_classes_for_teacher(TEACHER, 50, 0)
                ] == ["7А", "7Б"]
                assert await repository.remove(TEACHER, 7) is True
                assert await repository.remove(TEACHER, 7) is False
                assert [
                    x.id
                    for x in await repository.list_classes_for_teacher(
                        UUID(int=2), 50, 0
                    )
                ] == [7]
                assert (
                    await repository.list_classes_for_teacher(UUID(int=3), 50, 0) == []
                )

            asyncio.run(scenario())
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "driver_type,constraint,translated",
    [
        (UniqueViolationError, "teacher_classes_pkey", True),
        (UniqueViolationError, "other_unique", False),
        (ForeignKeyViolationError, "teacher_classes_class_id_fkey", False),
    ],
)
def test_only_own_unique_violation_is_translated(driver_type, constraint, translated):
    from journal_service.application.ports.errors import TeacherAlreadyAssignedError
    from journal_service.infrastructure.teacher_class_repository import (
        SqlAlchemyTeacherClassRepository,
    )

    driver = driver_type("rejected")
    driver.constraint_name = constraint
    failure = IntegrityError("INSERT", {}, EmulatedDBAPIException("constraint", driver))
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock(side_effect=failure)
    with pytest.raises(TeacherAlreadyAssignedError if translated else IntegrityError):
        asyncio.run(SqlAlchemyTeacherClassRepository(session).add(TEACHER, 7))
