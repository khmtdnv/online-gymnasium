"""Закрытый API карточки не доверяет одному заголовку преподавателя."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from homework_service.app import create_app
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    LessonNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.config import HomeworkSettings


def request(token="gateway-only", error=None):
    handler = SimpleNamespace(handle=AsyncMock(side_effect=error))
    app = create_app(
        HomeworkSettings(
            _env_file=None,
            database_url="postgresql+asyncpg://unused",
            gateway_service_token="gateway-only",
        ),
        SimpleNamespace(dispose=AsyncMock()),
        get_teacher_lesson_handler=handler,
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(
                "/internal/teacher-lessons/11",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Teacher-ID": str(UUID(int=2)),
                },
            )

    return asyncio.run(run()), handler, app


def test_actor_header_does_not_replace_service_credentials():
    response, handler, app = request(token="bad")
    assert response.status_code == 401
    handler.handle.assert_not_awaited()
    assert "/internal/teacher-lessons/{lesson_id}" not in app.openapi()["paths"]


@pytest.mark.parametrize(
    "error,status",
    [
        (HomeworkAccessDeniedError(), 403),
        (LessonNotFoundError(), 404),
        (OwnerLookupUnavailableError("secret"), 503),
    ],
)
def test_safe_card_errors(error, status):
    response, _, _ = request(error=error)
    assert response.status_code == status
    assert "secret" not in response.text
