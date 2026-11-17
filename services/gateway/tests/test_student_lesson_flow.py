"""Связанные ASGI API: личная карточка и повторная проверка класса после перевода."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
from fastapi import FastAPI


def test_student_view_uses_own_class_and_refuses_after_transfer(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "homework" / "src")
    )
    from fastapi.responses import JSONResponse
    from homework_service.api.errors import HomeworkHTTPError
    from homework_service.api.student_lessons import router as source_router
    from homework_service.application.ports.schedule_reader import LessonInfo
    from homework_service.application.student_lessons import GetStudentLessonHandler
    from homework_service.config import HomeworkSettings

    from gateway_service.api.my_schedule import router
    from gateway_service.api.security import get_authenticated_user
    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.domain.user import Role
    from gateway_service.infrastructure.homework_client import HomeworkClient

    lesson = LessonInfo(
        id=1,
        class_id=7,
        subject_id=1,
        teacher_id=UUID(int=1),
        starts_at=datetime(2026, 10, 21, 4, tzinfo=UTC),
        ends_at=datetime(2026, 10, 21, 5, tzinfo=UTC),
        status="planned",
        version=1,
    )
    journal = SimpleNamespace(
        get_current_class_id=AsyncMock(return_value=7),
        get_class_names=AsyncMock(return_value={7: "7А"}),
    )
    schedule = SimpleNamespace(
        get_lesson=AsyncMock(return_value=lesson),
        get_next_lesson=AsyncMock(return_value=None),
        get_subject_names=AsyncMock(return_value={1: "Математика"}),
        list_calendar_lessons=AsyncMock(return_value=[]),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            homeworks=SimpleNamespace(list_for_lesson=AsyncMock(return_value=[])),
            files=SimpleNamespace(list_for_homeworks=AsyncMock(return_value={})),
            users=SimpleNamespace(get_by_ids=AsyncMock(return_value=[])),
        )

    source = FastAPI()
    source.state.settings = HomeworkSettings(
        database_url="unused", gateway_service_token="gateway", _env_file=None
    )
    source.state.get_student_lesson_handler = GetStudentLessonHandler(
        uow, schedule, journal
    )
    source.include_router(source_router)

    @source.exception_handler(HomeworkHTTPError)
    async def handle_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.detail}},
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=source), base_url="http://homework"
        ) as http:
            app = FastAPI()
            app.state.homework_client = HomeworkClient(http, "gateway")
            app.state.journal_client = journal
            app.state.schedule_client = schedule
            app.state.uow_factory = uow
            app.include_router(router)
            user = GetCurrentUserResult(
                id=UUID(int=2), email="student@example.com", role=Role.STUDENT
            )
            app.dependency_overrides[get_authenticated_user] = lambda: user
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                path = "/api/v1/my-schedule/lessons/1"
                response = await client.get(
                    path, headers={"X-Student-ID": str(UUID(int=99))}
                )
                assert response.status_code == 200
                assert response.json()["lesson"]["subject_name"] == "Математика"
                assert response.headers["cache-control"] == "private, no-store"
                assert (
                    await client.get(
                        "/api/v1/my-schedule?week_start=2026-10-19&class_id=8"
                    )
                ).status_code == 422
                journal.get_current_class_id.return_value = 8
                assert (await client.get(path)).status_code == 404
                user = user.model_copy(update={"role": Role.PARENT})
                assert (await client.get(path)).status_code == 403

    asyncio.run(run())
