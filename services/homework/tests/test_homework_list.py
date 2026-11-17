"""Период и состояние фильтруются до пагинации, не только в первой странице."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError


def test_list_filters_and_sorts_all_matches_before_page():
    from homework_service.application.homework_list import (
        ListMyHomeworkHandler,
        ListMyHomeworkQuery,
    )
    from homework_service.domain.homework import Homework

    moment = datetime(2026, 10, 21, tzinfo=UTC)
    rows = [
        (
            Homework(
                id=i,
                issued_lesson_id=i,
                class_id=7,
                subject_id=1,
                author_id=UUID(int=1),
                description="Задание",
                manual_due_datetime=moment + timedelta(minutes=60 - i),
                created_at=moment,
            ),
            SimpleNamespace(status="returned", grade=None),
        )
        for i in range(1, 52)
    ]
    journal = SimpleNamespace(get_current_class_id=AsyncMock(return_value=7))
    schedule = SimpleNamespace(list_calendar_lessons=AsyncMock(return_value=[]))

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            homeworks=SimpleNamespace(list_for_period=AsyncMock(return_value=rows)),
            files=SimpleNamespace(list_for_homeworks=AsyncMock(return_value={})),
        )

    async def run():
        handler = ListMyHomeworkHandler(uow, journal, schedule)
        query = ListMyHomeworkQuery(
            student_id=UUID(int=2),
            date_from=date(2026, 10, 19),
            date_to=date(2026, 10, 25),
            state="returned",
            limit=50,
            offset=50,
        )
        result = await handler.handle(query)
        assert result.total == 51 and [row.id for row in result.items] == [1]
        assert result.items[0].latest_answer_status == "returned"
        rows.extend([rows[0]] * 950)
        with pytest.raises(ValueError, match="period"):
            await handler.handle(query)
        journal.get_current_class_id.return_value = None
        assert (await handler.handle(query)).items == []
        with pytest.raises(ValidationError):
            ListMyHomeworkQuery(**(query.model_dump() | {"date_to": date(2026, 12, 1)}))

    asyncio.run(run())


def test_deadline_uses_lesson_start_not_overlap_with_selected_school_day():
    """Урок с началом вчера не становится сегодняшним сроком из-за полуночи."""
    from homework_service.application.homework_list import (
        ListMyHomeworkHandler,
        ListMyHomeworkQuery,
    )
    from homework_service.application.ports.schedule_reader import LessonInfo

    start = datetime(2026, 10, 20, 19, tzinfo=UTC)  # 21 октября, 00:00 школы.
    lessons = [
        LessonInfo(
            id=i,
            class_id=7,
            subject_id=1,
            teacher_id=UUID(int=1),
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            status="planned",
            version=1,
        )
        for i, starts_at in ((1, start - timedelta(minutes=30)), (2, start))
    ]
    repository = SimpleNamespace(list_for_period=AsyncMock(return_value=[]))

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(homeworks=repository)

    async def run():
        handler = ListMyHomeworkHandler(
            uow,
            SimpleNamespace(get_current_class_id=AsyncMock(return_value=7)),
            SimpleNamespace(list_calendar_lessons=AsyncMock(return_value=lessons)),
        )
        await handler.handle(
            ListMyHomeworkQuery(
                student_id=UUID(int=2),
                date_from=date(2026, 10, 21),
                date_to=date(2026, 10, 21),
            )
        )
        assert repository.list_for_period.call_args.kwargs["due_lesson_ids"] == [2]

    asyncio.run(run())
