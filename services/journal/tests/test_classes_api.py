"""Проверки HTTP-контракта классов без подключения к базе данных."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from journal_service.api.classes import router
from journal_service.api.dependencies import (
    ServicePrincipal,
    get_authenticated_service,
    get_create_class_handler,
    get_list_classes_handler,
)
from journal_service.application.classes import (
    ClassResult,
    CreateClassCommand,
    ListClassesQuery,
)
from journal_service.config import JournalSettings


def make_app() -> tuple[FastAPI, Mock]:
    """Подключает настоящий роутер, подменяя только прикладной обработчик."""
    app = FastAPI()
    app.state.settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    handler = Mock()
    handler.handle = AsyncMock(
        return_value=ClassResult(
            id=10,
            name="7А",
            study_year=2026,
            created_at=datetime(2026, 10, 11, tzinfo=UTC),
        )
    )
    app.dependency_overrides[get_create_class_handler] = lambda: handler
    app.include_router(router)
    return app, handler


def post_class(app: FastAPI, payload: dict, token: str | None = "test-token"):
    """Отправляет JSON в ручку создания класса внутри процесса."""

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {} if token is None else {"Authorization": f"Bearer {token}"}
            return await client.post("/internal/classes", json=payload, headers=headers)

    return asyncio.run(request())


def test_create_class_passes_command_and_returns_saved_class() -> None:
    """Передаёт команду и возвращает результат с 201 и JSON-датой."""
    app, handler = make_app()

    response = post_class(app, {"name": "7А", "study_year": 2026})

    assert response.status_code == 201
    assert response.json() == {
        "id": 10,
        "name": "7А",
        "study_year": 2026,
        "created_at": "2026-10-11T00:00:00Z",
    }
    handler.handle.assert_awaited_once_with(
        CreateClassCommand(name="7А", study_year=2026)
    )


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_create_class_rejects_unauthenticated_service(token: str | None) -> None:
    """Не вызывает обработчик без правильного Bearer-токена."""
    app, handler = make_app()

    response = post_class(app, {"name": "7А", "study_year": 2026}, token)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    handler.handle.assert_not_awaited()


def test_create_class_rejects_read_only_service() -> None:
    """Не разрешает создание сервису, у которого есть только право чтения."""
    app, handler = make_app()
    app.dependency_overrides[get_authenticated_service] = lambda: ServicePrincipal(
        service_name="read-only-test-client", permissions=frozenset({"classes:read"})
    )

    response = post_class(app, {"name": "7А", "study_year": 2026})

    assert response.status_code == 403
    handler.handle.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "7А", "study_year": "2026"},
        {"name": "7А", "study_year": 2026.0},
        {"name": "7А", "study_year": True},
        {"name": "7А"},
        {"study_year": 2026},
    ],
)
def test_create_class_rejects_invalid_request_structure(payload: dict) -> None:
    """Отклоняет отсутствующие поля и нецелочисленный год до обработчика."""
    app, handler = make_app()

    response = post_class(app, payload)

    assert response.status_code == 422
    handler.handle.assert_not_awaited()


def test_internal_classes_are_hidden_from_openapi() -> None:
    """Не публикует внутреннюю ручку в OpenAPI."""
    app, _ = make_app()

    assert "/internal/classes" not in app.openapi()["paths"]


def get_classes(app: FastAPI, params: dict, token: str | None = "test-token"):
    """Запрашивает список классов с параметрами фильтра и пагинации."""

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {} if token is None else {"Authorization": f"Bearer {token}"}
            return await client.get("/internal/classes", params=params, headers=headers)

    return asyncio.run(request())


def make_list_app(returned_ids: list[int]) -> tuple[FastAPI, Mock]:
    """Подменяет обработчик списка, сохраняя реальные HTTP-проверки."""
    app, _ = make_app()
    handler = Mock()
    handler.handle = AsyncMock(
        return_value=[
            ClassResult(
                id=class_id,
                name=f"Класс {class_id}",
                study_year=2026,
                created_at=datetime(2026, 10, 11, tzinfo=UTC),
            )
            for class_id in returned_ids
        ]
    )
    app.dependency_overrides[get_list_classes_handler] = lambda: handler
    return app, handler


@pytest.mark.parametrize(
    ("params", "returned_ids", "expected_query"),
    [
        ({}, [10, 20], ListClassesQuery()),
        (
            {"study_year": 2026, "limit": 1, "offset": 2},
            [20],
            ListClassesQuery(study_year=2026, limit=1, offset=2),
        ),
        ({}, [], ListClassesQuery()),
    ],
)
def test_list_classes_returns_page_and_passes_query(
    params: dict, returned_ids: list[int], expected_query: ListClassesQuery
) -> None:
    """Сохраняет поля и порядок результатов, включая пустой список."""
    app, handler = make_list_app(returned_ids)

    response = get_classes(app, params)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": class_id,
            "name": f"Класс {class_id}",
            "study_year": 2026,
            "created_at": "2026-10-11T00:00:00Z",
        }
        for class_id in returned_ids
    ]
    handler.handle.assert_awaited_once_with(expected_query)


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": 2**63},
        {"study_year": 1899},
        {"study_year": 9999},
        {"study_year": "wrong"},
        {"limit": "wrong"},
        {"offset": "wrong"},
    ],
)
def test_list_classes_rejects_invalid_query(params: dict) -> None:
    """Отклоняет неверные параметры до вызова прикладного обработчика."""
    app, handler = make_list_app([])

    response = get_classes(app, params)

    assert response.status_code == 422
    handler.handle.assert_not_awaited()


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_list_classes_requires_authentication(token: str | None) -> None:
    """Не допускает чтение без правильного токена."""
    app, handler = make_list_app([])

    response = get_classes(app, {}, token)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    handler.handle.assert_not_awaited()


@pytest.mark.parametrize("permissions", [frozenset(), frozenset({"classes:read"})])
def test_list_classes_requires_read_permission(permissions: frozenset[str]) -> None:
    """Допускает read-only сервис, но отклоняет сервис без права чтения."""
    app, handler = make_list_app([])
    app.dependency_overrides[get_authenticated_service] = lambda: ServicePrincipal(
        service_name="test-client", permissions=permissions
    )

    response = get_classes(app, {})

    assert response.status_code == (200 if "classes:read" in permissions else 403)
    assert handler.handle.await_count == (1 if "classes:read" in permissions else 0)
