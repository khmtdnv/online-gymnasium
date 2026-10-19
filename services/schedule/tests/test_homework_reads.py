"""Закрытые чтения уроков для Homework не используют пользовательский actor."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError


def lesson(**changes):
    from schedule_service.domain.lesson import Lesson

    return Lesson(
        id=11,
        class_id=7,
        teacher_id=UUID(int=1),
        subject_id=3,
        starts_at=datetime(2026, 11, 1, 10, tzinfo=UTC),
        ends_at=datetime(2026, 11, 1, 11, tzinfo=UTC),
        **changes,
    )


def request(
    path="/internal/lessons/11",
    *,
    token="homework-only",
    found=True,
    next_lesson=None,
    failure=None,
):
    from schedule_service.api.homework_reads import router

    app = FastAPI()
    app.state.settings = SimpleNamespace(homework_service_token="homework-only")
    repo = SimpleNamespace(
        get=AsyncMock(return_value=lesson() if found else None, side_effect=failure),
        get_next_lesson=AsyncMock(return_value=next_lesson, side_effect=failure),
    )
    uow = SimpleNamespace(lessons=repo)

    class Context:
        async def __aenter__(self):
            return uow

        async def __aexit__(self, *args):
            return None

    app.state.uow_factory = Context
    app.include_router(router)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"X-Actor-ID": str(UUID(int=2)), "X-Actor-Role": "teacher"}
            if token is not None:
                headers["Authorization"] = f"Bearer {token}"
            return await client.get(path, headers=headers)

    return asyncio.run(run())


def test_get_returns_real_lesson_and_missing_is_404():
    assert request().json()["teacher_id"] == "00000000-0000-0000-0000-000000000001"
    assert request(found=False).status_code == 404


def test_no_next_candidate_is_null_not_missing_source():
    assert request("/internal/lessons/11/next").json() is None
    assert request("/internal/lessons/11/next", found=False).status_code == 404


@pytest.mark.parametrize("token", [None, "bad", "backoffice"])
def test_untrusted_actor_headers_do_not_grant_access(token):
    assert request(token=token).status_code == 401


@pytest.mark.parametrize(
    "failure",
    [
        OperationalError("SELECT", {}, RuntimeError("secret")),
        ConnectionRefusedError("secret"),
        TimeoutError("secret"),
    ],
)
@pytest.mark.parametrize("path", ["/internal/lessons/11", "/internal/lessons/11/next"])
def test_database_failure_is_not_successful_empty_response(failure, path):
    response = request(path, failure=failure)
    assert response.status_code == 503
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "path", ["/internal/lessons/0", "/internal/lessons/2147483648/next"]
)
def test_invalid_lesson_id_is_rejected(path):
    assert request(path).status_code == 422


def test_repository_next_query_filters_and_orders():
    from sqlalchemy.dialects import postgresql

    from schedule_service.infrastructure.lesson_repository import (
        SqlAlchemyLessonRepository,
    )

    seen = []

    async def scalar(stmt):
        seen.append(
            stmt.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )

    assert (
        asyncio.run(
            SqlAlchemyLessonRepository(SimpleNamespace(scalar=scalar)).get_next_lesson(
                class_id=7, subject_id=3, after=datetime(2026, 11, 1, 10, tzinfo=UTC)
            )
        )
        is None
    )
    sql = str(seen[0])
    assert "class_id = 7" in sql and "subject_id = 3" in sql
    assert "status = 'planned'" in sql and "starts_at >" in sql
    assert "ORDER BY scheduled_lessons.starts_at, scheduled_lessons.id" in sql
    assert "LIMIT 1" in sql
