"""Gateway→Homework с настоящими handlers/readers и подставными HTTP владельцами."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest

from gateway_service.app import create_app as create_gateway
from gateway_service.config import GatewaySettings
from gateway_service.domain.user import Role, User
from gateway_service.infrastructure.homework_client import HomeworkClient
from gateway_service.infrastructure.token_service import PyJwtTokenService

STUDENT = UUID(int=1)
NOW = datetime(2026, 10, 18, tzinfo=UTC)


@pytest.mark.parametrize(
    "scenario",
    [
        "normal",
        "moved",
        "cancelled",
        "journal_fail",
        "schedule_fail",
        "foreign_period",
        "no_period",
        "empty",
    ],
)
def test_student_reads_through_both_services_and_authoritative_http(
    monkeypatch, scenario
):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "homework" / "src")
    )
    from homework_service.app import create_app as create_homework
    from homework_service.application.student_reads import (
        GetStudentHomeworkHandler,
        ListStudentHomeworkHandler,
    )
    from homework_service.config import HomeworkSettings
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.journal_client import HttpJournalReader
    from homework_service.infrastructure.schedule_client import HttpScheduleReader

    rows = [
        Homework(
            id=i,
            issued_lesson_id=10 + i,
            class_id=8 if i == 3 else 7,
            subject_id=3,
            author_id=UUID(int=2),
            description="Задача",
            created_at=NOW - timedelta(days=30),
            manual_due_datetime=None if i == 2 else NOW - timedelta(days=1),
            due_lesson_id=22 if i == 2 else None,
        )
        for i in [1, 2, 3]
    ]
    state = {"class_id": 7}
    calls = {"journal": 0, "schedule": 0}

    async def list_for_class(class_id, limit, offset):
        return sorted(
            [row for row in rows if row.class_id == class_id],
            key=lambda row: (row.created_at, row.id),
            reverse=True,
        )[offset : offset + limit]

    async def get_by_id(id):
        return next((row for row in rows if row.id == id), None)

    @asynccontextmanager
    async def homework_uow():
        yield SimpleNamespace(
            homeworks=SimpleNamespace(
                list_for_class=list_for_class, get_by_id=get_by_id
            )
        )

    def journal_response(request):
        calls["journal"] += 1
        assert request.headers["Authorization"] == "Bearer journal-token"
        assert request.url.path == f"/internal/students/{STUDENT}/current-class-period"
        if scenario == "journal_fail":
            return httpx.Response(503, json={"detail": "secret"})
        if scenario == "no_period":
            return httpx.Response(404, json={})
        return httpx.Response(
            200,
            json={
                "id": 1,
                "student_id": str(UUID(int=9))
                if scenario == "foreign_period"
                else str(STUDENT),
                "class_id": state["class_id"],
                "joined_at": NOW.isoformat(),
                "left_at": None,
            },
        )

    def schedule_response(request):
        calls["schedule"] += 1
        assert request.headers["Authorization"] == "Bearer schedule-token"
        assert request.url.path == "/internal/lessons/lookup"
        assert json.loads(request.content) == {"lesson_ids": [22]}
        if scenario == "schedule_fail":
            raise httpx.ConnectTimeout("secret", request=request)
        start = NOW + timedelta(days=5 if scenario == "moved" else 2)
        return httpx.Response(
            200,
            json=[
                {
                    "id": 22,
                    "class_id": 7,
                    "subject_id": 3,
                    "teacher_id": str(UUID(int=2)),
                    "starts_at": start.isoformat(),
                    "ends_at": (start + timedelta(hours=1)).isoformat(),
                    "status": "canceled" if scenario == "cancelled" else "planned",
                    "version": 2,
                }
            ],
        )

    settings = GatewaySettings(
        database_url="test",
        jwt_secret="x" * 32,
        backoffice_service_token="test",
        _env_file=None,
    )
    user = User(
        id=STUDENT,
        email="student@example.com",
        role=Role.STUDENT,
        first_name="Иван",
        last_name="Петров",
        password_hash="x",
        is_active=True,
    )

    async def get_user(id):
        return user if id == STUDENT else None

    @asynccontextmanager
    async def gateway_uow():
        yield SimpleNamespace(users=SimpleNamespace(get_by_id=get_user))

    tokens = PyJwtTokenService(settings)

    async def run():
        async with (
            httpx.AsyncClient(
                base_url="http://journal",
                transport=httpx.MockTransport(journal_response),
            ) as journal,
            httpx.AsyncClient(
                base_url="http://schedule",
                transport=httpx.MockTransport(schedule_response),
            ) as schedule,
        ):
            readers = (
                homework_uow,
                HttpJournalReader(journal, "journal-token"),
                HttpScheduleReader(schedule, "schedule-token"),
            )
            homework = create_homework(
                HomeworkSettings(
                    database_url="test", gateway_service_token="gw", _env_file=None
                ),
                AsyncMock(),
                list_student_homework_handler=ListStudentHomeworkHandler(*readers),
                get_student_homework_handler=GetStudentHomeworkHandler(*readers),
            )
            async with (
                homework.router.lifespan_context(homework),
                httpx.AsyncClient(
                    base_url="http://homework",
                    transport=httpx.ASGITransport(app=homework),
                ) as internal,
            ):
                gateway = create_gateway(
                    settings,
                    AsyncMock(),
                    gateway_uow,
                    Mock(),
                    tokens,
                    homework_client=HomeworkClient(internal, "gw"),
                )
                async with (
                    gateway.router.lifespan_context(gateway),
                    httpx.AsyncClient(
                        base_url="http://gateway",
                        transport=httpx.ASGITransport(app=gateway),
                    ) as public,
                ):
                    headers = {
                        "Authorization": f"Bearer {tokens.issue_access(user)}",
                        "X-Student-ID": str(UUID(int=9)),
                    }
                    path = (
                        "/api/v1/homework?offset=99"
                        if scenario == "empty"
                        else "/api/v1/homework"
                    )
                    response = await public.get(path, headers=headers)
                    if scenario in ("journal_fail", "schedule_fail", "foreign_period"):
                        assert response.status_code == 503, response.text
                        assert "secret" not in response.text
                        return
                    assert response.status_code == 200, response.text
                    if scenario in ("empty", "no_period"):
                        assert response.json() == []
                        assert calls["schedule"] == 0
                        if scenario == "no_period":
                            assert (
                                await public.get("/api/v1/homework/1", headers=headers)
                            ).status_code == 404
                        return
                    data = response.json()
                    assert [row["id"] for row in data] == [2, 1]
                    assert calls["schedule"] == 1
                    assert data[1]["due_status"] == "manual"
                    if scenario == "cancelled":
                        assert data[0]["due_status"] == "lesson_cancelled"
                        assert data[0]["final_due_datetime"] is None
                    else:
                        expected = NOW + timedelta(days=5 if scenario == "moved" else 2)
                        assert (
                            datetime.fromisoformat(data[0]["final_due_datetime"])
                            == expected
                        )
                    assert (
                        await public.get("/api/v1/homework/1", headers=headers)
                    ).status_code == 200
                    before = calls["schedule"]
                    state["class_id"] = 8
                    assert (
                        await public.get("/api/v1/homework/2", headers=headers)
                    ).status_code == 404
                    after = await public.get("/api/v1/homework", headers=headers)
                    assert [row["id"] for row in after.json()] == [3]
                    assert calls["schedule"] == before

    asyncio.run(run())
