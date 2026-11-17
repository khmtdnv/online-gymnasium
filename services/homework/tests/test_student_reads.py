"""Права текущего класса и сроки проверяются независимо от HTTP/ORM."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from homework_service.application.ports.errors import OwnerLookupUnavailableError
from homework_service.application.ports.schedule_reader import LessonInfo
from homework_service.domain.homework import Homework

STUDENT = UUID(int=1)
NOW = datetime(2026, 10, 18, tzinfo=UTC)


def homework(id=1, **changes):
    values = {
        "id": id,
        "issued_lesson_id": 11 + id,
        "class_id": 7,
        "subject_id": 3,
        "author_id": UUID(int=2),
        "description": "Задача",
        "due_lesson_id": None,
        "manual_due_datetime": NOW - timedelta(days=1),
        "created_at": NOW - timedelta(days=30),
    }
    return Homework(**(values | changes))


def lesson(id=22, **changes):
    return LessonInfo(
        **(
            {
                "id": id,
                "class_id": 7,
                "subject_id": 3,
                "teacher_id": UUID(int=2),
                "starts_at": NOW + timedelta(days=3),
                "ends_at": NOW + timedelta(days=3, hours=1),
                "status": "planned",
                "version": 1,
            }
            | changes
        )
    )


def handlers(rows, *, class_id=7, lessons=None, failure=None):
    from homework_service.application.student_reads import (
        GetStudentHomeworkHandler,
        ListStudentHomeworkHandler,
    )

    events = []
    state = {"class_id": class_id}

    async def current(student_id):
        assert student_id == STUDENT
        events.append("journal")
        if failure:
            raise failure
        return state["class_id"]

    async def list_for_class(class_id, limit, offset):
        events.append((class_id, limit, offset))
        return sorted(
            [row for row in rows if row.class_id == class_id],
            key=lambda row: (row.created_at, row.id),
            reverse=True,
        )[offset : offset + limit]

    async def get_by_id(id):
        events.append("get")
        return next((row for row in rows if row.id == id), None)

    async def list_files(ids):
        return {}

    @asynccontextmanager
    async def factory():
        events.append("open")
        yield SimpleNamespace(
            homeworks=SimpleNamespace(
                list_for_class=list_for_class, get_by_id=get_by_id
            ),
            files=SimpleNamespace(list_for_homeworks=list_files),
        )
        events.append("closed")

    async def get_lessons(ids):
        assert events[-1] == "closed"  # Не держим свою транзакцию во время HTTP.
        events.append(ids)
        return lessons or {}

    readers = (
        factory,
        SimpleNamespace(get_current_class_id=current),
        SimpleNamespace(get_lessons=get_lessons),
    )
    return (
        ListStudentHomeworkHandler(*readers),
        GetStudentHomeworkHandler(*readers),
        state,
        events,
    )


def test_list_filters_class_orders_and_does_not_restrict_by_join_date():
    from homework_service.application.student_reads import ListStudentHomeworkQuery

    first, _, _, events = handlers([homework(1), homework(2), homework(3, class_id=8)])
    result = asyncio.run(
        first.handle(ListStudentHomeworkQuery(student_id=STUDENT, limit=1, offset=1))
    )
    assert [item.id for item in result] == [1]
    assert result[0].final_due_datetime == NOW - timedelta(days=1)
    assert result[0].due_status == "manual"
    assert events == ["journal", "open", (7, 1, 1), "closed"]


def test_transfer_closes_direct_old_id_on_next_request():
    from homework_service.application.ports.errors import HomeworkNotFoundError
    from homework_service.application.student_reads import GetStudentHomeworkQuery

    _, one, state, _ = handlers([homework()])
    query = GetStudentHomeworkQuery(student_id=STUDENT, homework_id=1)
    assert asyncio.run(one.handle(query)).id == 1
    state["class_id"] = 8
    with pytest.raises(HomeworkNotFoundError):
        asyncio.run(one.handle(query))


@pytest.mark.parametrize("class_id", [None, 8])
def test_no_current_class_or_foreign_assignment_never_calls_schedule(class_id):
    from homework_service.application.ports.errors import HomeworkNotFoundError
    from homework_service.application.student_reads import (
        GetStudentHomeworkQuery,
        ListStudentHomeworkQuery,
    )

    many, one, _, events = handlers(
        [homework(manual_due_datetime=None, due_lesson_id=22)], class_id=class_id
    )
    assert asyncio.run(many.handle(ListStudentHomeworkQuery(student_id=STUDENT))) == []
    with pytest.raises(HomeworkNotFoundError):
        asyncio.run(
            one.handle(GetStudentHomeworkQuery(student_id=STUDENT, homework_id=1))
        )
    assert not any(isinstance(event, list) for event in events)


@pytest.mark.parametrize("method", ["list", "get"])
def test_journal_failure_is_not_confirmed_absence(method):
    from homework_service.application.student_reads import (
        GetStudentHomeworkQuery,
        ListStudentHomeworkQuery,
    )

    many, one, _, _ = handlers([], failure=OwnerLookupUnavailableError())
    with pytest.raises(OwnerLookupUnavailableError):
        asyncio.run(
            many.handle(ListStudentHomeworkQuery(student_id=STUDENT))
            if method == "list"
            else one.handle(GetStudentHomeworkQuery(student_id=STUDENT, homework_id=1))
        )


@pytest.mark.parametrize("status", ["planned", "canceled"])
def test_mixed_page_resolves_unique_ids_once_and_keeps_reference(status):
    from homework_service.application.student_reads import ListStudentHomeworkQuery

    moved = lesson(status=status)
    many, _, _, events = handlers(
        [
            homework(),
            homework(2, manual_due_datetime=None, due_lesson_id=22),
            homework(3, manual_due_datetime=None, due_lesson_id=22),
        ],
        lessons={22: moved},
    )
    result = asyncio.run(many.handle(ListStudentHomeworkQuery(student_id=STUDENT)))
    assert sum(isinstance(event, list) for event in events) == 1
    assert events[-1] == [22]
    assert result[0].due_lesson_id == 22
    assert result[0].final_due_datetime == (
        moved.starts_at if status == "planned" else None
    )
    assert result[0].due_status == (
        "lesson" if status == "planned" else "lesson_cancelled"
    )


@pytest.mark.parametrize("changed", [{}, {"class_id": 8}, {"subject_id": 4}])
def test_missing_or_incompatible_lesson_fails_whole_page(changed):
    from homework_service.application.student_reads import ListStudentHomeworkQuery

    lessons = {} if not changed else {22: lesson(**changed)}
    many, _, _, _ = handlers(
        [homework(manual_due_datetime=None, due_lesson_id=22)], lessons=lessons
    )
    with pytest.raises(OwnerLookupUnavailableError):
        asyncio.run(many.handle(ListStudentHomeworkQuery(student_id=STUDENT)))


def test_past_linked_deadline_is_returned_not_rejected():
    from homework_service.application.student_reads import GetStudentHomeworkQuery

    old = lesson(
        starts_at=NOW - timedelta(days=2), ends_at=NOW - timedelta(days=2, hours=-1)
    )
    _, one, _, _ = handlers(
        [homework(manual_due_datetime=None, due_lesson_id=22)], lessons={22: old}
    )
    result = asyncio.run(
        one.handle(GetStudentHomeworkQuery(student_id=STUDENT, homework_id=1))
    )
    assert result.final_due_datetime == old.starts_at
