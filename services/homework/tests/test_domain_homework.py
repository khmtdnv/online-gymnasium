"""Локальные инварианты ДЗ не зависят от HTTP или базы."""

from datetime import UTC, datetime
from uuid import UUID

import pytest


def data(**changes):
    return {
        "issued_lesson_id": 11,
        "class_id": 7,
        "subject_id": 3,
        "author_id": UUID("11111111-1111-4111-8111-111111111111"),
        "description": "  Решить задачи 1–3  ",
        "due_lesson_id": 12,
        **changes,
    }


def test_normalizes_description_and_preserves_lesson_due():
    from homework_service.domain.homework import Homework

    item = Homework(**data())
    assert item.description == "Решить задачи 1–3"
    assert item.manual_due_datetime is None
    assert item.id is None and item.created_at is None


def test_accepts_aware_manual_due():
    from homework_service.domain.homework import Homework

    due = datetime(2026, 11, 1, tzinfo=UTC)
    assert (
        Homework(
            **data(due_lesson_id=None, manual_due_datetime=due)
        ).manual_due_datetime
        == due
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"description": "  "},
        {"description": "a" * 10001},
        {"due_lesson_id": None},
        {"manual_due_datetime": datetime(2026, 11, 1, tzinfo=UTC)},
        {
            "due_lesson_id": None,
            "manual_due_datetime": datetime(2026, 11, 1, tzinfo=UTC).replace(
                tzinfo=None
            ),
        },
        {"class_id": True},
        {"issued_lesson_id": 0},
        {"subject_id": -1},
        {"due_lesson_id": 2147483648},
        {"author_id": "not-a-uuid"},
        {"id": 0},
        {"created_at": datetime(2026, 11, 1, tzinfo=UTC).replace(tzinfo=None)},
    ],
)
def test_rejects_invalid_local_data(changes):
    from homework_service.domain.homework import Homework

    with pytest.raises(ValueError):
        Homework(**data(**changes))


def test_accepts_maximum_description():
    from homework_service.domain.homework import Homework

    assert len(Homework(**data(description="я" * 10000)).description) == 10000
