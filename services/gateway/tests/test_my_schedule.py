"""Школьная неделя и доверенный класс личного календаря."""

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

SCHOOL_PERIODS_RESPONSE = {
    "timezone": "Asia/Yekaterinburg",
    "effective_from": "2026-11-30",
    "periods": [
        {"number": 1, "start_at": "09:00", "end_at": "09:45"},
        {"number": 2, "start_at": "09:55", "end_at": "10:40"},
        {"number": 3, "start_at": "11:00", "end_at": "11:45"},
        {"number": 4, "start_at": "11:55", "end_at": "12:40"},
        {"number": 5, "start_at": "13:00", "end_at": "13:45"},
        {"number": 6, "start_at": "13:55", "end_at": "14:40"},
        {"number": 7, "start_at": "15:00", "end_at": "15:45"},
    ],
}


def test_personal_calendar_has_six_days_and_batches_names():
    from gateway_service.application.my_schedule import (
        GetMyScheduleHandler,
        GetMyScheduleQuery,
    )
    from gateway_service.application.teacher_lessons import LessonInfo
    from gateway_service.infrastructure.schedule_client import SchoolPeriods

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
        get_school_periods=AsyncMock(
            return_value=SchoolPeriods.model_validate(SCHOOL_PERIODS_RESPONSE)
        ),
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
        assert [row.model_dump() for row in result.periods] == (
            SCHOOL_PERIODS_RESPONSE["periods"]
        )
        journal.get_current_class_id.return_value = None
        result = await GetMyScheduleHandler(uow, journal, schedule).handle(query)
        assert not result.has_class and all(not day.lessons for day in result.days)
        assert [row.model_dump() for row in result.periods] == (
            SCHOOL_PERIODS_RESPONSE["periods"]
        )

    asyncio.run(run())


def _make_my_schedule_app(schedule, journal, uow, user):
    from fastapi import FastAPI

    from gateway_service.api.my_schedule import router
    from gateway_service.api.security import get_authenticated_user

    app = FastAPI()
    app.state.journal_client = journal
    app.state.schedule_client = schedule
    app.state.uow_factory = uow
    app.include_router(router)
    app.dependency_overrides[get_authenticated_user] = lambda: user
    return app


def test_my_schedule_week_has_exact_periods():
    from fastapi.testclient import TestClient

    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.domain.user import Role
    from gateway_service.infrastructure.schedule_client import SchoolPeriods

    journal = SimpleNamespace(
        get_current_class_id=AsyncMock(return_value=7),
        get_class_names=AsyncMock(return_value={7: "7А"}),
    )
    schedule = SimpleNamespace(
        list_calendar_lessons=AsyncMock(return_value=[]),
        get_subject_names=AsyncMock(return_value={}),
        get_school_periods=AsyncMock(
            return_value=SchoolPeriods.model_validate(SCHOOL_PERIODS_RESPONSE)
        ),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(get_by_ids=AsyncMock(return_value=[]))
        )

    user = GetCurrentUserResult(
        id=UUID(int=2), email="student@example.com", role=Role.STUDENT
    )
    app = _make_my_schedule_app(schedule, journal, uow, user)
    with TestClient(app) as client:
        response = client.get("/api/v1/my-schedule?week_start=2026-10-19")
    assert response.status_code == 200
    data = response.json()
    assert data["timezone"] == "Asia/Yekaterinburg"
    assert data["periods"] == SCHOOL_PERIODS_RESPONSE["periods"]


def test_parent_is_denied_on_my_schedule():
    from fastapi.testclient import TestClient

    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.domain.user import Role
    from gateway_service.infrastructure.schedule_client import SchoolPeriods

    journal = SimpleNamespace(
        get_current_class_id=AsyncMock(return_value=7),
        get_class_names=AsyncMock(return_value={7: "7А"}),
    )
    schedule = SimpleNamespace(
        list_calendar_lessons=AsyncMock(return_value=[]),
        get_subject_names=AsyncMock(return_value={}),
        get_school_periods=AsyncMock(
            return_value=SchoolPeriods.model_validate(SCHOOL_PERIODS_RESPONSE)
        ),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(get_by_ids=AsyncMock(return_value=[]))
        )

    parent = GetCurrentUserResult(
        id=UUID(int=3), email="parent@example.com", role=Role.PARENT
    )
    app = _make_my_schedule_app(schedule, journal, uow, parent)
    with TestClient(app) as client:
        response = client.get("/api/v1/my-schedule?week_start=2026-10-19")
    assert response.status_code == 403


def test_corrupt_schedule_periods_is_503():
    from fastapi.testclient import TestClient

    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.application.teacher_lessons import (
        ScheduleUnavailableError,
    )
    from gateway_service.domain.user import Role

    journal = SimpleNamespace(
        get_current_class_id=AsyncMock(return_value=7),
        get_class_names=AsyncMock(return_value={7: "7А"}),
    )
    schedule = SimpleNamespace(
        list_calendar_lessons=AsyncMock(return_value=[]),
        get_subject_names=AsyncMock(return_value={}),
        get_school_periods=AsyncMock(side_effect=ScheduleUnavailableError),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(get_by_ids=AsyncMock(return_value=[]))
        )

    student = GetCurrentUserResult(
        id=UUID(int=2), email="student@example.com", role=Role.STUDENT
    )
    app = _make_my_schedule_app(schedule, journal, uow, student)
    with TestClient(app) as client:
        response = client.get("/api/v1/my-schedule?week_start=2026-10-19")
    assert response.status_code == 503
