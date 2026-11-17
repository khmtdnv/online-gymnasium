"""Карточка ученика не допускает чтение бывшего или чужого класса."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest


def test_student_lesson_checks_current_class_and_does_not_match_manual_date():
    from homework_service.application.ports.errors import HomeworkNotFoundError
    from homework_service.application.ports.schedule_reader import LessonInfo
    from homework_service.application.student_lessons import (
        GetStudentLessonHandler,
        GetStudentLessonQuery,
    )

    lesson = LessonInfo(
        id=1,
        class_id=7,
        subject_id=1,
        teacher_id=UUID(int=1),
        starts_at=datetime(2026, 10, 21, 9, tzinfo=UTC),
        ends_at=datetime(2026, 10, 21, 10, tzinfo=UTC),
        status="planned",
        version=1,
    )
    journal = SimpleNamespace(get_current_class_id=AsyncMock(return_value=7))
    schedule = SimpleNamespace(
        get_lesson=AsyncMock(return_value=lesson),
        get_next_lesson=AsyncMock(return_value=None),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            homeworks=SimpleNamespace(list_for_lesson=AsyncMock(return_value=[])),
            files=SimpleNamespace(list_for_homeworks=AsyncMock(return_value={})),
        )

    async def run():
        handler = GetStudentLessonHandler(uow, schedule, journal)
        query = GetStudentLessonQuery(student_id=UUID(int=2), lesson_id=1)
        result = await handler.handle(query)
        assert result.lesson.id == 1 and result.homework_for_lesson == []
        journal.get_current_class_id.return_value = 8
        with pytest.raises(HomeworkNotFoundError):
            await handler.handle(query)

    asyncio.run(run())
