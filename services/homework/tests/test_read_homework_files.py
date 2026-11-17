"""Чтения добавляют только публичные метаданные доступных заданий одним пакетом."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkNotFoundError,
)
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
from homework_service.domain.homework_file import HomeworkFile
from tests.test_homework_files import file_input
from tests.test_student_reads import homework, lesson


def build(*, empty=False, current_class=7, assigned=True, failure=None):
    rows = (
        []
        if empty
        else [
            homework(
                2, issued_lesson_id=10, due_lesson_id=11, manual_due_datetime=None
            ),
            homework(1, issued_lesson_id=11),
        ]
    )
    files = [
        HomeworkFile(id=8, homework_id=1, **file_input()),
        HomeworkFile(
            id=9,
            homework_id=1,
            **file_input(),
            upload_status="ready",
            storage_key="homework/private-first",
        ),
        HomeworkFile(
            id=10,
            homework_id=2,
            **file_input(),
            upload_status="ready",
            storage_key="homework/private-second",
        ),
    ]
    state = {"active": False, "batches": []}

    async def list_files(ids):
        assert state["active"], "read metadata in the local read transaction"
        state["batches"].append(ids)
        if failure:
            raise failure
        return {id: [file for file in files if file.homework_id == id] for id in ids}

    async def list_for_class(class_id, limit, offset):
        return [row for row in rows if row.class_id == class_id][
            offset : offset + limit
        ]

    async def list_for_lesson(lesson_id):
        return rows

    async def get_by_id(id):
        return next((row for row in rows if row.id == id), None)

    @asynccontextmanager
    async def factory():
        state["active"] = True
        try:
            yield SimpleNamespace(
                homeworks=SimpleNamespace(
                    list_for_class=list_for_class,
                    list_for_lesson=list_for_lesson,
                    get_by_id=get_by_id,
                ),
                files=SimpleNamespace(list_for_homeworks=list_files),
            )
        finally:
            state["active"] = False

    async def current(student_id):
        return current_class

    async def is_assigned(teacher_id, class_id):
        return assigned

    async def get_lesson(id):
        assert not state["active"]
        return lesson(id=id)

    async def get_lessons(ids):
        assert not state["active"], "close SQL transaction before owner HTTP"
        return {id: lesson(id=id) for id in ids}

    async def get_next_lesson(id):
        assert not state["active"]

    journal = SimpleNamespace(
        get_current_class_id=current, is_teacher_assigned=is_assigned
    )
    schedule = SimpleNamespace(
        get_lesson=get_lesson, get_lessons=get_lessons, get_next_lesson=get_next_lesson
    )
    return factory, journal, schedule, state


@pytest.mark.parametrize("kind", ["list", "get", "teacher"])
def test_reads_include_pending_and_ready_without_private_fields_and_without_n_plus_one(
    kind,
):
    factory, journal, schedule, state = build()
    if kind == "list":
        result = asyncio.run(
            ListStudentHomeworkHandler(factory, journal, schedule).handle(
                ListStudentHomeworkQuery(student_id=UUID(int=1))
            )
        )
        assert [[file.id for file in row.files] for row in result] == [[10], [8, 9]]
    elif kind == "get":
        result = [
            asyncio.run(
                GetStudentHomeworkHandler(factory, journal, schedule).handle(
                    GetStudentHomeworkQuery(student_id=UUID(int=1), homework_id=1)
                )
            )
        ]
        assert [file.id for file in result[0].files] == [8, 9]
    else:
        card = asyncio.run(
            GetTeacherLessonHandler(factory, schedule, journal).handle(
                GetTeacherLessonQuery(teacher_id=UUID(int=2), lesson_id=11)
            )
        )
        assert [file.id for file in card.homework_for_lesson[0].files] == [10]
        assert [file.id for file in card.homework_from_lesson[0].files] == [8, 9]
        result = card.homework_for_lesson + card.homework_from_lesson
    assert state["batches"] == ([[1]] if kind == "get" else [[2, 1]])
    first = next(row for row in result if row.id == 1)
    assert [file.upload_status for file in first.files] == ["pending", "ready"]
    for row in result:
        payload = row.model_dump(mode="json")
        for file in payload["files"]:
            assert set(file) == {
                "id",
                "homework_id",
                "file_name",
                "size_bytes",
                "content_type",
                "upload_status",
            }
            assert file["homework_id"] == row.id
        assert "private-first" not in row.model_dump_json()


@pytest.mark.parametrize("kind", ["list", "teacher"])
def test_empty_reads_do_not_query_file_metadata(kind):
    factory, journal, schedule, state = build(empty=True)
    if kind == "list":
        assert (
            asyncio.run(
                ListStudentHomeworkHandler(factory, journal, schedule).handle(
                    ListStudentHomeworkQuery(student_id=UUID(int=1))
                )
            )
            == []
        )
    else:
        result = asyncio.run(
            GetTeacherLessonHandler(factory, schedule, journal).handle(
                GetTeacherLessonQuery(teacher_id=UUID(int=2), lesson_id=11)
            )
        )
        assert result.homework_for_lesson == result.homework_from_lesson == []
    assert state["batches"] == []


def test_foreign_homework_is_rejected_before_its_metadata_is_read():
    factory, journal, schedule, state = build(current_class=8)
    with pytest.raises(HomeworkNotFoundError):
        asyncio.run(
            GetStudentHomeworkHandler(factory, journal, schedule).handle(
                GetStudentHomeworkQuery(student_id=UUID(int=1), homework_id=1)
            )
        )
    assert state["batches"] == []


def test_removed_teacher_assignment_does_not_read_metadata():
    factory, journal, schedule, state = build(assigned=False)
    with pytest.raises(HomeworkAccessDeniedError):
        asyncio.run(
            GetTeacherLessonHandler(factory, schedule, journal).handle(
                GetTeacherLessonQuery(teacher_id=UUID(int=2), lesson_id=11)
            )
        )
    assert state["batches"] == []


def test_metadata_failure_is_not_presented_as_homework_without_files():
    factory, journal, schedule, _ = build(failure=OSError("metadata unavailable"))
    with pytest.raises(OSError, match="metadata unavailable"):
        asyncio.run(
            ListStudentHomeworkHandler(factory, journal, schedule).handle(
                ListStudentHomeworkQuery(student_id=UUID(int=1))
            )
        )
