"""Учебные acceptance-тесты: тело handle намеренно оставлено ученику."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from homework_service.application.homework import (
    CreateHomeworkCommand,
    CreateHomeworkHandler,
)
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkAlreadyExistsError,
    InvalidHomeworkDataError,
    LessonNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.application.ports.schedule_reader import LessonInfo

pytestmark = pytest.mark.learning
NOW = datetime(2026, 11, 1, 9, tzinfo=UTC)
TEACHER = UUID(int=1)


def lesson(**changes):
    values = {
        "id": 11,
        "class_id": 7,
        "subject_id": 3,
        "teacher_id": TEACHER,
        "starts_at": NOW + timedelta(hours=1),
        "ends_at": NOW + timedelta(hours=2),
        "status": "planned",
        "version": 1,
    }
    return LessonInfo(**(values | changes))


class Schedule:
    def __init__(self, source, due, unavailable=False):
        self.source, self.due, self.unavailable = source, due, unavailable

    async def get_lesson(self, lesson_id):
        if self.unavailable:
            raise OwnerLookupUnavailableError
        if lesson_id == 11:
            return self.source
        if lesson_id == 12:
            return self.due
        raise AssertionError("Unexpected lookup ID")


class Journal:
    def __init__(self, assigned=True, unavailable=False):
        self.assigned, self.unavailable = assigned, unavailable

    async def is_teacher_assigned(self, teacher_id, class_id):
        assert (teacher_id, class_id) == (TEACHER, 7)
        if self.unavailable:
            raise OwnerLookupUnavailableError
        return self.assigned


class MemoryStorage:
    def __init__(self, duplicate=False):
        self.saved = []
        self.pending = []
        self.duplicate = duplicate

    async def add(self, homework):
        if self.duplicate:
            raise HomeworkAlreadyExistsError
        saved = replace(homework, id=51, created_at=NOW)
        self.pending.append(saved)
        return saved

    async def get_by_issued_lesson_id(self, id):
        assert id == 11
        return lesson() if self.duplicate else None

    async def __aenter__(self):
        self.pending = []
        self.homeworks = self
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.saved.extend(self.pending)
        self.pending = []


def setup(
    *,
    source=None,
    due=None,
    assigned=True,
    duplicate=False,
    schedule_down=False,
    journal_down=False,
):
    storage = MemoryStorage(duplicate)
    handler = CreateHomeworkHandler(
        lambda: storage,
        Schedule(source, due, schedule_down),
        Journal(assigned, journal_down),
        lambda: NOW,
    )
    return handler, storage


def command(**changes):
    return CreateHomeworkCommand(
        **(
            {
                "teacher_id": TEACHER,
                "issued_lesson_id": 11,
                "description": "  Решить задачи 1–3  ",
                "manual_due_datetime": NOW + timedelta(days=2),
            }
            | changes
        )
    )


@pytest.mark.parametrize("linked", [False, True])
def test_create_persists_checked_owner_fields_and_one_due_mode(linked):
    due = lesson(
        id=12,
        starts_at=NOW + timedelta(days=1),
        ends_at=NOW + timedelta(days=1, hours=1),
    )
    handler, storage = setup(source=lesson(), due=due)
    request = (
        command(manual_due_datetime=None, due_lesson_id=12) if linked else command()
    )
    result = asyncio.run(handler.handle(request))
    assert result.id == 51
    assert (result.class_id, result.subject_id, result.author_id) == (7, 3, TEACHER)
    assert result.description == "Решить задачи 1–3"
    assert result.issued_lesson_id == 11
    assert result.due_lesson_id == (12 if linked else None)
    assert result.manual_due_datetime == (None if linked else NOW + timedelta(days=2))
    assert result.created_at == NOW
    assert len(storage.saved) == 1  # result must be returned after UoW commit


@pytest.mark.parametrize(
    "source,assigned,error",
    [
        (None, True, LessonNotFoundError),
        (lesson(teacher_id=UUID(int=2)), True, HomeworkAccessDeniedError),
        (lesson(status="canceled"), True, HomeworkAccessDeniedError),
        (lesson(), False, HomeworkAccessDeniedError),
    ],
)
def test_forbidden_or_missing_source_does_not_write(source, assigned, error):
    handler, storage = setup(source=source, assigned=assigned)
    with pytest.raises(error):
        asyncio.run(handler.handle(command()))
    assert storage.saved == []


@pytest.mark.parametrize(
    "due,error",
    [
        (None, LessonNotFoundError),
        (lesson(id=12, class_id=8), InvalidHomeworkDataError),
        (lesson(id=12, subject_id=4), InvalidHomeworkDataError),
        (lesson(id=12, status="canceled"), InvalidHomeworkDataError),
        (lesson(id=12), InvalidHomeworkDataError),
        (
            lesson(id=12, starts_at=NOW - timedelta(hours=1), ends_at=NOW),
            InvalidHomeworkDataError,
        ),
    ],
)
def test_invalid_linked_due_does_not_write(due, error):
    handler, storage = setup(source=lesson(), due=due)
    with pytest.raises(error):
        asyncio.run(handler.handle(command(manual_due_datetime=None, due_lesson_id=12)))
    assert storage.saved == []


@pytest.mark.parametrize(
    "due",
    [
        NOW - timedelta(seconds=1),
        NOW,
        NOW + timedelta(minutes=30),
        NOW + timedelta(hours=1),
    ],
)
def test_manual_due_must_be_after_now_and_issued_start(due):
    handler, storage = setup(source=lesson())
    with pytest.raises(InvalidHomeworkDataError):
        asyncio.run(handler.handle(command(manual_due_datetime=due)))
    assert storage.saved == []


@pytest.mark.parametrize("owner", ["schedule", "journal"])
def test_owner_failure_does_not_create_homework(owner):
    handler, storage = setup(
        source=lesson(),
        schedule_down=owner == "schedule",
        journal_down=owner == "journal",
    )
    with pytest.raises(OwnerLookupUnavailableError):
        asyncio.run(handler.handle(command()))
    assert storage.saved == []


def test_duplicate_issued_lesson_is_conflict_not_update():
    handler, storage = setup(source=lesson(), duplicate=True)
    with pytest.raises(HomeworkAlreadyExistsError):
        asyncio.run(handler.handle(command()))
    assert storage.saved == []


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("seconds_before_now", [1, 0])
def test_due_after_past_lesson_still_must_be_strictly_after_now(
    linked, seconds_before_now
):
    source = lesson(
        starts_at=NOW - timedelta(hours=3), ends_at=NOW - timedelta(hours=2)
    )
    due_time = NOW - timedelta(seconds=seconds_before_now)
    due_lesson = lesson(
        id=12, starts_at=due_time, ends_at=due_time + timedelta(hours=1)
    )
    handler, storage = setup(source=source, due=due_lesson)
    request = (
        command(manual_due_datetime=None, due_lesson_id=12)
        if linked
        else command(manual_due_datetime=due_time)
    )
    with pytest.raises(InvalidHomeworkDataError):
        asyncio.run(handler.handle(request))
    assert storage.saved == []
