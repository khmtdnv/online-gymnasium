"""Проверки доступности Journal и освобождения ресурсов приложения."""

import asyncio
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from journal_service.app import create_app
from journal_service.config import JournalSettings


def make_settings() -> JournalSettings:
    """Создаёт настройки без чтения локальных секретов."""
    return JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )


def test_live_does_not_check_database_and_ready_checks_each_request() -> None:
    """Разделяет жизнь HTTP-процесса и фактическую готовность зависимости."""
    checks = []

    async def check():
        checks.append("database checked")

    app = create_app(make_settings(), Mock(), readiness_check=check)
    assert checks == []

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            live = await client.get("/health/live")
            assert checks == []
            ready = await client.get("/health/ready")
            second_ready = await client.get("/health/ready")
            return live, ready, second_ready

    for response in asyncio.run(request()):
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["x-request-id"]
    assert len(checks) == 2


@pytest.mark.parametrize("error_type", [OSError, SQLAlchemyError, TimeoutError])
def test_unavailable_database_returns_safe_503_but_live_still_works(
    error_type: type[Exception],
) -> None:
    """Не раскрывает детали сбоя БД и не путает readiness с liveness."""

    async def check():
        raise error_type("private-database-details")

    app = create_app(make_settings(), Mock(), readiness_check=check)

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/health/ready"), await client.get("/health/live")

    ready, live = asyncio.run(request())
    assert ready.status_code == 503
    assert ready.json()["error"]["request_id"] == ready.headers["x-request-id"]
    assert "private-database-details" not in ready.text
    assert live.status_code == 200


def test_ready_without_configured_check_is_not_successful() -> None:
    """Не заявляет готовность, если проверка зависимости не подключена."""
    app = create_app(make_settings(), Mock())

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/health/ready")

    assert asyncio.run(request()).status_code == 503


def test_ready_limits_wait_for_database() -> None:
    """Прерывает зависшую проверку и освобождает её контекст при отмене."""
    events = []

    async def check():
        try:
            await asyncio.Event().wait()
        finally:
            events.append("cancelled")

    app = create_app(make_settings(), Mock(), readiness_check=check)

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with asyncio.timeout(5):
                return await client.get("/health/ready")

    response = asyncio.run(request())
    assert response.status_code == 503
    assert events == ["cancelled"]


@pytest.mark.parametrize("interrupted", [False, True])
def test_lifespan_closes_resources_once_after_requests(interrupted: bool) -> None:
    """Освобождает ресурсы при обычном выходе и при исключении внутри lifespan."""
    events = []

    async def close():
        events.append("closed")

    app = create_app(make_settings(), Mock(), close_resources=close)
    assert events == []

    async def run():
        async with app.router.lifespan_context(app):
            assert events == []
            events.append("running")
            if interrupted:
                raise RuntimeError("interrupted")

    if interrupted:
        with pytest.raises(RuntimeError, match="interrupted"):
            asyncio.run(run())
    else:
        asyncio.run(run())
    assert events == ["running", "closed"]
