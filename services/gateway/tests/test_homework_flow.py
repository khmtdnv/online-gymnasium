"""Оба настоящих ASGI API и handler; владельцы и хранилища подменены локально."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
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

TEACHER = UUID("75ef34f4-2588-41b1-b41e-cbd058c6025c")
NOW = datetime(2026, 10, 17, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    "scenario",
    [
        "linked",
        "manual",
        "foreign",
        "unavailable",
        "unassigned",
        "canceled",
        "past",
        "missing",
    ],
)
def test_gateway_homework_flow(monkeypatch, scenario):
    # Только тест знает расположение соседнего сервиса; runtime зависимости нет.
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "homework" / "src")
    )
    from homework_service.app import create_app as create_homework
    from homework_service.application.homework import CreateHomeworkHandler
    from homework_service.application.ports.errors import (
        HomeworkAlreadyExistsError,
        OwnerLookupUnavailableError,
    )
    from homework_service.application.ports.schedule_reader import LessonInfo
    from homework_service.config import HomeworkSettings

    saved = []

    class Storage:
        async def add(self, homework):
            if saved:
                raise HomeworkAlreadyExistsError
            return replace(homework, id=1, created_at=NOW)

    @asynccontextmanager
    async def homework_uow():
        pending = []

        async def add(homework):
            result = await Storage().add(homework)
            pending.append(result)
            return result

        yield SimpleNamespace(homeworks=SimpleNamespace(add=add))
        saved.extend(pending)

    async def get_lesson(lesson_id):
        if scenario == "unavailable":
            raise OwnerLookupUnavailableError("secret")
        if scenario == "missing":
            return None
        return LessonInfo(
            id=lesson_id,
            class_id=7,
            subject_id=3,
            teacher_id=UUID(int=999) if scenario == "foreign" else TEACHER,
            starts_at=NOW + timedelta(days=0 if lesson_id == 11 else 1),
            ends_at=NOW + timedelta(days=0 if lesson_id == 11 else 1, hours=1),
            status="canceled" if scenario == "canceled" else "planned",
            version=1,
        )

    async def is_assigned(teacher_id, class_id):
        assert teacher_id == TEACHER and class_id == 7
        return scenario != "unassigned"

    handler = CreateHomeworkHandler(
        homework_uow,
        SimpleNamespace(get_lesson=get_lesson),
        SimpleNamespace(is_teacher_assigned=is_assigned),
        lambda: NOW,
    )
    homework = create_homework(
        HomeworkSettings(
            database_url="test",
            gateway_service_token="service-test",
            _env_file=None,
        ),
        AsyncMock(),
        create_homework_handler=handler,
    )
    settings = GatewaySettings(
        database_url="test",
        jwt_secret="x" * 32,
        backoffice_service_token="test",
        _env_file=None,
    )
    user = User(
        id=TEACHER,
        email="teacher@example.com",
        role=Role.TEACHER,
        is_active=True,
        first_name="Иван",
        last_name="Петров",
        password_hash="x",
    )

    async def get_user(user_id):
        return user if user_id == TEACHER else None

    @asynccontextmanager
    async def gateway_uow():
        yield SimpleNamespace(users=SimpleNamespace(get_by_id=get_user))

    tokens = PyJwtTokenService(settings)

    async def run():
        async with (
            homework.router.lifespan_context(homework),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=homework), base_url="http://homework"
            ) as internal,
        ):
            gateway = create_gateway(
                settings,
                AsyncMock(),
                gateway_uow,
                Mock(),
                tokens,
                homework_client=HomeworkClient(internal, "service-test"),
            )
            async with (
                gateway.router.lifespan_context(gateway),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=gateway),
                    base_url="http://gateway",
                ) as public,
            ):
                body = {"description": "Решить задачу", "due_lesson_id": 12}
                if scenario in ("manual", "past"):
                    body = {
                        "description": "Решить задачу",
                        "manual_due_datetime": (
                            NOW + timedelta(days=1 if scenario == "manual" else -1)
                        ).isoformat(),
                    }
                headers = {
                    "Authorization": f"Bearer {tokens.issue_access(user)}",
                    "X-Teacher-ID": str(UUID(int=999)),
                }
                first = await public.post(
                    "/api/v1/lessons/11/homework", json=body, headers=headers
                )
                if scenario in ("linked", "manual"):
                    assert first.status_code == 201, first.text
                    assert first.json()["author_id"] == str(TEACHER)
                    assert first.json()["class_id"] == 7
                    assert first.json()["subject_id"] == 3
                    second = await public.post(
                        "/api/v1/lessons/11/homework", json=body, headers=headers
                    )
                    assert second.status_code == 409
                else:
                    expected = {
                        "foreign": 403,
                        "unavailable": 503,
                        "unassigned": 403,
                        "canceled": 403,
                        "past": 422,
                        "missing": 404,
                    }[scenario]
                    assert first.status_code == expected, first.text
                    assert "secret" not in first.text

    asyncio.run(run())
    assert len(saved) == (1 if scenario in ("linked", "manual") else 0)
