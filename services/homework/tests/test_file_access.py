"""Роль teacher не заменяет текущее право на исходный урок и назначение классу."""

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest

from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    OwnerLookupUnavailableError,
)
from homework_service.domain.homework import Homework
from tests.test_create_homework import NOW, TEACHER, lesson
from tests.test_domain_homework import data


@pytest.mark.parametrize(
    "scenario,error",
    [
        ("valid", None),
        ("canceled", None),
        ("missing", HomeworkAccessDeniedError),
        ("foreign", HomeworkAccessDeniedError),
        ("unassigned", HomeworkAccessDeniedError),
        ("incompatible", OwnerLookupUnavailableError),
        ("down", OwnerLookupUnavailableError),
    ],
)
def test_upload_requires_current_teacher_and_assignment(scenario, error):
    from homework_service.application.file_access import check_teacher_access

    homework = Homework(
        **data(id=51, issued_lesson_id=11, author_id=TEACHER, created_at=NOW)
    )

    async def get_lesson(lesson_id):
        assert lesson_id == 11
        if scenario == "down":
            raise OwnerLookupUnavailableError
        if scenario == "missing":
            return None
        return lesson(
            teacher_id=UUID(int=999) if scenario == "foreign" else TEACHER,
            status="canceled" if scenario == "canceled" else "planned",
            class_id=999 if scenario == "incompatible" else homework.class_id,
        )

    async def assigned(teacher_id, class_id):
        assert teacher_id == TEACHER and class_id == homework.class_id
        return scenario != "unassigned"

    async def run():
        await check_teacher_access(
            TEACHER,
            homework,
            SimpleNamespace(get_lesson=get_lesson),
            SimpleNamespace(is_teacher_assigned=assigned),
        )

    if error is None:
        asyncio.run(run())
    else:
        with pytest.raises(error):
            asyncio.run(run())
