from uuid import UUID

"""Проверяет команды расписания и сохранение доменного урока в DTO порта."""

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from schedule_service.application.cancel_lesson import CancelLessonCommand
from schedule_service.application.create_lesson import CreateLessonCommand
from schedule_service.application.list_lessons import ListLessonsQuery
from schedule_service.application.ports.idempotency_repository import IdempotencyRecord
from schedule_service.application.update_lesson import UpdateLessonCommand
from schedule_service.domain.lesson import Lesson

START = datetime(2026, 10, 14, 9, tzinfo=UTC)
END = START + timedelta(hours=1)


@pytest.mark.parametrize("operation", ["create", "update"])
def test_commands_reject_cross_day_interval(operation) -> None:
    """Сохраняет прежнее правило урока в пределах одного календарного дня."""
    common = {"starts_at": START, "ends_at": END + timedelta(days=1)}
    with pytest.raises(ValidationError):
        if operation == "create":
            CreateLessonCommand(
                class_id=1, teacher_id=UUID(int=2), subject_id=3, **common
            )
        else:
            UpdateLessonCommand(lesson_id=999, expected_version=3, **common)


@pytest.mark.parametrize("value", [0, -1, True, "1"])
def test_cancel_command_rejects_invalid_id(value) -> None:
    """Неверный ID не должен попадать в запрос отмены."""
    with pytest.raises(ValidationError):
        CancelLessonCommand(lesson_id=value, expected_version=1)


@pytest.mark.parametrize("value", [0, True, "1"])
def test_cancel_command_rejects_invalid_version(value) -> None:
    """Ожидаемая версия должна быть положительным целым числом."""
    with pytest.raises(ValidationError):
        CancelLessonCommand(lesson_id=1, expected_version=value)


@pytest.mark.parametrize(
    ("start", "end"), [(START.replace(tzinfo=None), END), (END, START), (START, START)]
)
def test_create_command_rejects_invalid_interval(start, end) -> None:
    """Неправильное время отклоняется ещё до создания доменного урока."""
    with pytest.raises(ValidationError):
        CreateLessonCommand(
            class_id=1,
            teacher_id=UUID(int=2),
            subject_id=3,
            starts_at=start,
            ends_at=end,
        )


def test_create_command_preserves_idempotency_defaults() -> None:
    command = CreateLessonCommand(
        class_id=1, teacher_id=UUID(int=2), subject_id=3, starts_at=START, ends_at=END
    )
    assert command.idempotency_key is None
    assert command.request_hash is None


def test_query_rejects_datetime_instead_of_day() -> None:
    with pytest.raises(ValidationError):
        ListLessonsQuery(class_id=1, day=START)


def test_query_preserves_day() -> None:
    query = ListLessonsQuery(class_id=1, day=date(2026, 10, 14))
    assert query.day == date(2026, 10, 14)


def test_idempotency_record_keeps_the_same_domain_lesson() -> None:
    """DTO не должен незаметно реконструировать или копировать доменный объект."""
    lesson = Lesson.create(
        class_id=1, teacher_id=UUID(int=2), subject_id=3, starts_at=START, ends_at=END
    )
    record = IdempotencyRecord(request_hash="hash", lesson=lesson)
    assert record.lesson is lesson


def test_idempotency_record_rejects_dictionary_instead_of_lesson() -> None:
    """Внутренний DTO порта не разбирает произвольный словарь как домен."""
    with pytest.raises(ValidationError):
        IdempotencyRecord(request_hash="hash", lesson={"id": 1})
