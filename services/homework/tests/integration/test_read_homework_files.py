"""Настоящая PostgreSQL: три чтения возвращают файлы одним пакетным запросом."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from homework_service.application.homework_files import HomeworkFileInput
from homework_service.application.student_reads import (
    GetStudentHomeworkHandler,
    GetStudentHomeworkQuery,
    ListStudentHomeworkHandler,
    ListStudentHomeworkQuery,
)
from homework_service.application.teacher_lessons import (
    GetTeacherLessonHandler,
    GetTeacherLessonQuery,
)
from homework_service.domain.homework import Homework
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_domain_homework import data
from tests.test_homework_files import file_input
from tests.test_student_reads import lesson

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("kind", ["list", "get", "teacher"])
def test_read_metadata_from_postgres_uses_one_select_and_keeps_states(engine, kind):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().lower().startswith("select")
            and "from homework_files" in statement.lower()
        ):
            statements.append(statement)

    async def current(student_id):
        return 7

    async def assigned(teacher_id, class_id):
        return True

    async def get_lesson(id):
        return lesson(id=id)

    async def get_lessons(ids):
        return {id: lesson(id=id) for id in ids}

    async def get_next_lesson(id):
        return None

    def uow_factory():
        return SqlAlchemyUnitOfWork(factory)

    async def run():
        async with uow_factory() as uow:
            first = await uow.homeworks.add(
                Homework(
                    **data(
                        author_id=UUID(int=2),
                        due_lesson_id=None,
                        manual_due_datetime=datetime(2030, 1, 1, tzinfo=UTC),
                    )
                )
            )
            second = await uow.homeworks.add(
                Homework(
                    **data(
                        issued_lesson_id=10,
                        due_lesson_id=11,
                        author_id=UUID(int=2),
                    )
                )
            )
            files = await uow.files.add_files(
                first.id, [HomeworkFileInput(**file_input())] * 2
            )
            await uow.files.add_files(second.id, [HomeworkFileInput(**file_input())])
            started_at = await uow.files.get_current_time()
            await uow.files.mark_ready(
                files[1].id, "homework/private-test-object", started_at
            )
        journal = SimpleNamespace(
            get_current_class_id=current, is_teacher_assigned=assigned
        )
        schedule = SimpleNamespace(
            get_lesson=get_lesson,
            get_lessons=get_lessons,
            get_next_lesson=get_next_lesson,
        )
        event.listen(engine.sync_engine, "before_cursor_execute", record)
        try:
            if kind == "list":
                result = await ListStudentHomeworkHandler(
                    uow_factory, journal, schedule
                ).handle(ListStudentHomeworkQuery(student_id=UUID(int=1)))
                assert sorted(len(row.files) for row in result) == [1, 2]
            elif kind == "get":
                result = [
                    await GetStudentHomeworkHandler(
                        uow_factory, journal, schedule
                    ).handle(
                        GetStudentHomeworkQuery(
                            student_id=UUID(int=1), homework_id=first.id
                        )
                    )
                ]
            else:
                card = await GetTeacherLessonHandler(
                    uow_factory, schedule, journal
                ).handle(GetTeacherLessonQuery(teacher_id=UUID(int=2), lesson_id=11))
                assert len(card.homework_for_lesson[0].files) == 1
                result = card.homework_from_lesson
            row = next(row for row in result if row.id == first.id)
            assert [file.upload_status for file in row.files] == ["pending", "ready"]
            assert [file.id for file in row.files] == [1, 2]
            assert "storage_key" not in row.model_dump_json()
            assert "content_sha256" not in row.model_dump_json()
            assert len(statements) == 1
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record)

    asyncio.run(run())
