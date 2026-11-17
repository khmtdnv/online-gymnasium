"""Школьная неделя и доверенный класс личного календаря."""

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID


def test_personal_calendar_has_six_days_and_batches_names():
    from gateway_service.application.my_schedule import (
        GetMyScheduleHandler,
        GetMyScheduleQuery,
    )
    from gateway_service.application.teacher_lessons import LessonInfo

    lesson = LessonInfo(
        id=1,
        class_id=7,
        subject_id=1,
        teacher_id=UUID(int=1),
        starts_at=datetime.fromisoformat("2026-10-19T00:30:00+05:00"),
        ends_at=datetime.fromisoformat("2026-10-19T01:15:00+05:00"),
        status="planned",
        version=1,
    )
    journal = SimpleNamespace(
        get_current_class_id=AsyncMock(return_value=7),
        get_class_names=AsyncMock(return_value={7: "7А"}),
    )
    schedule = SimpleNamespace(
        list_calendar_lessons=AsyncMock(return_value=[lesson]),
        get_subject_names=AsyncMock(return_value={1: "Математика"}),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(
                get_by_ids=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            id=UUID(int=1),
                            last_name="Иванов",
                            first_name="Иван",
                            middle_name="Иванович",
                        )
                    ]
                )
            )
        )

    async def run():
        query = GetMyScheduleQuery(
            user_id=UUID(int=2), role="student", week_start=date(2026, 10, 19)
        )
        result = await GetMyScheduleHandler(uow, journal, schedule).handle(query)
        assert len(result.days) == 6 and str(result.days[-1].date) == "2026-10-24"
        assert result.days[0].lessons[0].subject_name == "Математика"
        assert not result.days[1].lessons
        args = schedule.list_calendar_lessons.await_args.kwargs
        assert args["class_id"] == 7 and args["teacher_id"] is None
        assert args["starts_at_from"] == datetime.fromisoformat("2026-10-18T19:00:00Z")
        assert args["starts_at_until"] == datetime.fromisoformat("2026-10-24T19:00:00Z")
        journal.get_current_class_id.return_value = None
        result = await GetMyScheduleHandler(uow, journal, schedule).handle(query)
        assert not result.has_class and all(not day.lessons for day in result.days)

    asyncio.run(run())
