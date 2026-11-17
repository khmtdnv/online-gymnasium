"""Проверяет владельца HTTP-клиента Gateway и очистку ресурсов Journal."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import httpx
import pytest

from journal_service.app import create_app
from journal_service.config import JournalSettings

STUDENT = UUID("aaaaaaaa-0000-4000-8000-000000000001")
CLIENT_TYPE = httpx.AsyncClient


def settings(**kwargs):
    """Создаёт настройки без локальных файлов и переменных интеграции."""
    return JournalSettings(
        database_url="postgresql+asyncpg://unused/test",
        backoffice_service_token="test-token",
        gateway_base_url="http://gateway:8000",
        gateway_service_token="journal-reader-token",
        _env_file=None,
        **kwargs,
    )


@pytest.mark.parametrize("failure_at", [None, "body", "cleanup", "client_close"])
def test_owned_client_closes_and_database_cleanup_always_runs(failure_at):
    """Не теряет закрытие engine при сбое приложения или закрытия HTTP-клиента."""
    created = []
    cleanup = AsyncMock(
        side_effect=RuntimeError("cleanup failed") if failure_at == "cleanup" else None
    )

    def reply(request):
        assert request.url == f"http://gateway:8000/internal/users/{STUDENT}"
        assert request.headers["authorization"] == "Bearer journal-reader-token"
        return httpx.Response(
            200, json={"id": str(STUDENT), "role": "student", "is_active": True}
        )

    def client_factory(**kwargs):
        client = CLIENT_TYPE(**kwargs, transport=httpx.MockTransport(reply))
        if failure_at == "client_close":
            original_close = client.aclose

            async def failing_close():
                await original_close()
                raise RuntimeError("client close failed")

            client.aclose = failing_close
        created.append(client)
        return client

    app = create_app(settings(), Mock(), close_resources=cleanup)

    async def scenario():
        with patch("httpx.AsyncClient", side_effect=client_factory):
            async with app.router.lifespan_context(app):
                user = await app.state.gateway_user_reader.get_user(STUDENT)
                assert user.id == STUDENT
                assert user.is_active is True
                assert not created[0].is_closed
                if failure_at == "body":
                    raise RuntimeError("body failed")

    if failure_at:
        with pytest.raises(RuntimeError):
            asyncio.run(scenario())
    else:
        asyncio.run(scenario())
    assert len(created) == 1
    assert created[0].is_closed
    cleanup.assert_awaited_once()
    assert app.state.gateway_user_reader is None


def test_injected_reader_is_used_but_not_closed_by_app():
    """Не создаёт лишний HTTP-клиент и не закрывает чужой reader."""
    reader = SimpleNamespace(get_user=AsyncMock(return_value=None), aclose=AsyncMock())
    app = create_app(settings(), Mock(), gateway_user_reader=reader)

    async def scenario():
        with patch("httpx.AsyncClient") as client:
            async with app.router.lifespan_context(app):
                assert app.state.gateway_user_reader is reader
            client.assert_not_called()

    asyncio.run(scenario())
    reader.aclose.assert_not_awaited()


@pytest.mark.parametrize(
    ("url", "token"),
    [
        (None, None),
        ("", "token"),
        ("http://gateway:8000", None),
        ("http://gateway:8000", ""),
    ],
)
def test_incomplete_gateway_settings_leave_old_routes_available(url, token):
    """Отсутствующая интеграция отключает запись, а не всё приложение."""
    configured = settings().model_copy(
        update={"gateway_base_url": url, "gateway_service_token": token}
    )
    factory = Mock()
    app = create_app(configured, factory)

    async def scenario():
        with patch("httpx.AsyncClient") as outgoing:
            async with app.router.lifespan_context(app):
                async with CLIENT_TYPE(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    live = await client.get("/health/live")
                    result = await client.put(
                        f"/internal/students/{STUDENT}/current-class-period",
                        headers={
                            "Authorization": "Bearer test-token",
                            "X-Actor-ID": "42",
                        },
                        json={"class_id": 10},
                    )
                outgoing.assert_not_called()
                assert live.status_code == 200
                assert result.status_code == 503
                factory.assert_not_called()

    asyncio.run(scenario())


def test_client_startup_failure_still_closes_database_resources():
    """Даже ошибка сборки клиента не должна оставить engine без dispose."""
    cleanup = AsyncMock()
    app = create_app(settings(), Mock(), close_resources=cleanup)

    async def scenario():
        with patch(
            "httpx.AsyncClient", side_effect=ValueError("invalid client config")
        ):
            async with app.router.lifespan_context(app):
                pytest.fail("Startup failure must not yield")

    with pytest.raises(ValueError):
        asyncio.run(scenario())
    cleanup.assert_awaited_once()
