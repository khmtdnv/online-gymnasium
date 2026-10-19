"""Проверки сборки HTTP-приложения Journal."""

import asyncio
from unittest.mock import Mock
from uuid import UUID

import httpx

from journal_service.app import create_app
from journal_service.config import JournalSettings


def make_settings() -> JournalSettings:
    """Создаёт тестовые настройки без чтения локальных секретов."""
    return JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        app_name="Test Journal",
        _env_file=None,
    )


def test_create_app_stores_dependencies_without_opening_transaction() -> None:
    """Сохраняет переданные зависимости, не создавая транзакцию при сборке."""
    settings = make_settings()
    factory = Mock()

    app = create_app(settings, factory)

    assert app.title == "Test Journal"
    assert app.state.settings is settings
    assert app.state.uow_factory is factory
    factory.assert_not_called()


def test_request_id_matches_state_and_is_unique_for_each_request() -> None:
    """Создаёт отдельный UUID и передаёт один и тот же ID в state и ответ."""
    app = create_app(make_settings(), Mock())

    from fastapi import Request

    @app.get("/probe")
    async def probe(request: Request):
        return {"request_id": request.state.request_id}

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/probe"), await client.get("/probe")

    first, second = asyncio.run(request())

    for response in (first, second):
        request_id = response.headers["x-request-id"]
        assert UUID(request_id).version == 4
        assert response.json()["request_id"] == request_id
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_request_id_replaces_existing_response_header() -> None:
    """Не допускает двух противоречащих ID запроса в одном ответе."""
    app = create_app(make_settings(), Mock())

    from fastapi import Request, Response

    @app.get("/probe")
    async def probe(request: Request, response: Response):
        response.headers["X-Request-ID"] = "old-value"
        return {"request_id": request.state.request_id}

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/probe")

    response = asyncio.run(request())

    assert response.headers.get_list("x-request-id") == [response.json()["request_id"]]


def test_request_id_is_present_on_handled_http_errors() -> None:
    """Добавляет ID к ответам аутентификации и отсутствующего маршрута."""
    app = create_app(make_settings(), Mock())

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/internal/classes"), await client.get("/missing")

    unauthorized, missing = asyncio.run(request())

    assert unauthorized.status_code == 401
    assert missing.status_code == 404
    for response in (unauthorized, missing):
        assert UUID(response.headers["x-request-id"]).version == 4


def test_created_apps_do_not_share_state() -> None:
    """Собирает независимые приложения с разными фабриками."""
    first_factory = Mock()
    second_factory = Mock()

    first = create_app(make_settings(), first_factory)
    second = create_app(make_settings(), second_factory)

    assert first is not second
    assert first.state.uow_factory is first_factory
    assert second.state.uow_factory is second_factory


def test_create_app_connects_classes_router_with_authentication() -> None:
    """Подключает настоящую ручку и не открывает UoW для запроса без токена."""
    factory = Mock()
    app = create_app(make_settings(), factory)

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/internal/classes")

    response = asyncio.run(request())

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    factory.assert_not_called()
