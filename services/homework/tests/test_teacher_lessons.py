"""Карточка проверяет доступ до чтения своих заданий."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    LessonNotFoundError,
    OwnerLookupUnavailableError,
)
from tests.test_student_reads import NOW, homework, lesson


def handler(
    rows=(),
    *,
    found=True,
    assigned=True,
    teacher=None,
    status="planned",
    next_lesson=None,
):
    from homework_service.application.teacher_lessons import GetTeacherLessonHandler

    events = []

    @asynccontextmanager
    async def uow():
        events.append("open")
        yield SimpleNamespace(
            homeworks=SimpleNamespace(
                list_for_lesson=AsyncMock(return_value=list(rows))
            ),
            files=SimpleNamespace(list_for_homeworks=AsyncMock(return_value={})),
        )
        events.append("closed")

    async def get_lessons(ids):
        assert events[-1] == "closed"
        return {id: lesson(id=id) for id in ids}

    schedule = SimpleNamespace(
        get_lesson=AsyncMock(
            return_value=lesson(id=11, teacher_id=teacher or UUID(int=2), status=status)
            if found
            else None
        ),
        get_next_lesson=AsyncMock(return_value=next_lesson),
        get_lessons=get_lessons,
    )
    journal = SimpleNamespace(is_teacher_assigned=AsyncMock(return_value=assigned))
    return GetTeacherLessonHandler(uow, schedule, journal), events, schedule, journal


def run(handler):
    from homework_service.application.teacher_lessons import GetTeacherLessonQuery

    return asyncio.run(
        handler.handle(GetTeacherLessonQuery(teacher_id=UUID(int=2), lesson_id=11))
    )


def test_card_splits_groups_and_keeps_manual_only_in_from():
    rows = [
        homework(2, issued_lesson_id=11),
        homework(1, issued_lesson_id=10, due_lesson_id=11, manual_due_datetime=None),
    ]
    value, events, _, _ = handler(rows)
    result = run(value)
    assert [row.id for row in result.homework_for_lesson] == [1]
    assert [row.id for row in result.homework_from_lesson] == [2]
    assert result.homework_from_lesson[0].due_status == "manual"
    assert result.lesson.id == 11 and result.next_lesson is None
    assert events == ["open", "closed"]


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"found": False}, LessonNotFoundError),
        ({"assigned": False}, HomeworkAccessDeniedError),
        ({"teacher": UUID(int=99)}, HomeworkAccessDeniedError),
    ],
)
def test_access_denied_before_database(kwargs, error):
    value, events, _, _ = handler(**kwargs)
    with pytest.raises(error):
        run(value)
    assert events == []


def test_cancelled_source_readable_without_next_lookup():
    value, _, schedule, _ = handler(status="canceled")
    assert run(value).next_lesson is None
    schedule.get_next_lesson.assert_not_awaited()


def test_next_lesson_can_have_another_teacher():
    value, _, _, _ = handler(
        next_lesson=lesson(
            id=22,
            teacher_id=UUID(int=3),
            starts_at=NOW + timedelta(days=4),
            ends_at=NOW + timedelta(days=4, hours=1),
        )
    )
    assert run(value).next_lesson.teacher_id == UUID(int=3)


def test_incompatible_saved_reference_is_not_hidden():
    value, _, _, _ = handler([homework(1, issued_lesson_id=11, class_id=8)])
    with pytest.raises(OwnerLookupUnavailableError):
        run(value)


@pytest.mark.parametrize("status", ["planned", "canceled"])
def test_cancellation_between_owner_reads_does_not_return_inconsistent_card(status):
    value, _, schedule, _ = handler(
        [homework(1, issued_lesson_id=10, due_lesson_id=11, manual_due_datetime=None)],
        status=status,
    )

    async def get_lessons(ids):
        return {
            11: lesson(id=11, status="canceled" if status == "planned" else "planned")
        }

    schedule.get_lessons = get_lessons
    with pytest.raises(OwnerLookupUnavailableError):
        run(value)


@pytest.mark.parametrize("missing", [False, True])
def test_deadlines_are_loaded_in_complete_batches_of_100(missing):
    from homework_service.application.student_reads import _resolve_deadlines

    rows = [
        homework(id=id, due_lesson_id=1000 + id, manual_due_datetime=None)
        for id in range(1, 102)
    ]
    calls = []

    async def get_lessons(ids):
        calls.append(ids)
        return {} if missing and len(calls) == 2 else {id: lesson(id=id) for id in ids}

    async def check():
        return await _resolve_deadlines(rows, SimpleNamespace(get_lessons=get_lessons))

    if missing:
        with pytest.raises(OwnerLookupUnavailableError):
            asyncio.run(check())
    else:
        assert len(asyncio.run(check())) == 101
    assert [len(ids) for ids in calls] == [100, 1]
