"""Входные DTO проверяют значения, а не актуальность внешних прав."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError


def command_data(**changes):
    return {
        "teacher_id": UUID(int=1),
        "issued_lesson_id": 11,
        "description": "  Решить задачи 1–3  ",
        "due_lesson_id": 12,
        **changes,
    }


def test_command_normalizes_and_freezes():
    from homework_service.application.homework import CreateHomeworkCommand

    command = CreateHomeworkCommand(**command_data())
    assert command.description == "Решить задачи 1–3"
    with pytest.raises(ValidationError):
        command.description = "changed"


@pytest.mark.parametrize(
    "changes",
    [
        {"issued_lesson_id": True},
        {"issued_lesson_id": "11"},
        {"issued_lesson_id": 0},
        {"issued_lesson_id": 2147483648},
        {"due_lesson_id": False},
        {"due_lesson_id": None},
        {"manual_due_datetime": datetime(2026, 11, 2, tzinfo=UTC)},
        {
            "due_lesson_id": None,
            "manual_due_datetime": datetime(2026, 11, 2, tzinfo=UTC).replace(
                tzinfo=None
            ),
        },
        {"description": " "},
        {"description": "x" * 10001},
        {"teacher_id": "bad"},
        {"class_id": 7},
        {"author_id": str(UUID(int=2))},
    ],
)
def test_invalid_command_is_rejected(changes):
    from homework_service.application.homework import CreateHomeworkCommand

    with pytest.raises(ValidationError):
        CreateHomeworkCommand(**command_data(**changes))


def test_manual_due_and_maximum_description():
    from homework_service.application.homework import CreateHomeworkCommand

    due = datetime(2026, 11, 2, tzinfo=UTC)
    command = CreateHomeworkCommand(
        **command_data(
            due_lesson_id=None, manual_due_datetime=due, description="я" * 10000
        )
    )
    assert command.manual_due_datetime == due and len(command.description) == 10000


def test_result_requires_persisted_server_fields():
    from homework_service.application.homework import HomeworkResult
    from homework_service.domain.homework import Homework
    from tests.test_domain_homework import data

    with pytest.raises(ValueError):
        HomeworkResult.from_homework(Homework(**data()))
    result = HomeworkResult.from_homework(
        Homework(**data(id=4, created_at=datetime(2026, 11, 1, tzinfo=UTC)))
    )
    assert result.id == 4 and result.class_id == 7
