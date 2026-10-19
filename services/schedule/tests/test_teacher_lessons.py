"""Собственное расписание требует отдельного служебного доступа."""

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError


@pytest.mark.parametrize("days", [1, 7])
def test_query_accepts_one_week(days):
    from schedule_service.application.teacher_lessons import ListTeacherLessonsQuery

    query = ListTeacherLessonsQuery(
        teacher_id=UUID(int=1),
        date_from=date(2026, 10, 19),
        date_to=date(2026, 10, 18 + days),
    )
    assert query.teacher_id == UUID(int=1)


@pytest.mark.parametrize("last", [date(2026, 10, 18), date(2026, 10, 26), date.max])
def test_query_rejects_invalid_range(last):
    from schedule_service.application.teacher_lessons import ListTeacherLessonsQuery

    with pytest.raises(ValidationError):
        ListTeacherLessonsQuery(
            teacher_id=UUID(int=1),
            date_from=date(2026, 10, 19),
            date_to=last,
        )


def request(
    *, token="gateway-only", configured="gateway-only", params=None, failure=None
):
    from schedule_service.api.teacher_lessons import router

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        gateway_service_token=configured, homework_service_token="homework-only"
    )
    repository = SimpleNamespace(
        list_for_teacher=AsyncMock(return_value=[], side_effect=failure)
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(lessons=repository)

    app.state.uow_factory = uow
    app.include_router(router)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"X-Teacher-ID": str(UUID(int=1))}
            if token is not None:
                headers["Authorization"] = f"Bearer {token}"
            return await client.get(
                "/internal/teacher-lessons",
                headers=headers,
                params=params or {"date_from": "2026-10-19", "date_to": "2026-10-25"},
            )

    return asyncio.run(run()), repository, app


def test_list_passes_trusted_identity_and_dates():
    response, repository, app = request()
    assert response.status_code == 200
    assert response.json() == []
    repository.list_for_teacher.assert_awaited_once_with(
        teacher_id=UUID(int=1), date_from=date(2026, 10, 19), date_to=date(2026, 10, 25)
    )
    assert "/internal/teacher-lessons" not in app.openapi()["paths"]


@pytest.mark.parametrize("token", [None, "bad", "homework-only"])
def test_wrong_credentials_do_not_reach_repository(token):
    response, repository, _ = request(token=token)
    assert response.status_code == 401
    repository.list_for_teacher.assert_not_awaited()


@pytest.mark.parametrize("configured", [None, "homework-only"])
def test_partial_or_shared_credentials_fail_closed(configured):
    assert request(configured=configured)[0].status_code == 503


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-10-19"},
        {"date_from": "2026-10-19", "date_to": "2026-10-26"},
        {
            "date_from": "2026-10-19",
            "date_to": "2026-10-25",
            "teacher_id": str(UUID(int=2)),
        },
    ],
)
def test_invalid_dates_and_extra_query_rejected(params):
    assert request(params=params)[0].status_code == 422


def test_database_failure_is_safe_503():
    response, _, _ = request(failure=ConnectionRefusedError("secret"))
    assert response.status_code == 503
    assert "secret" not in response.text
