"""Проверки распознавания сервиса по Bearer-токену без обращения к БД."""

import asyncio
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI

from journal_service.api import dependencies
from journal_service.api.security import RequireServicePermission
from journal_service.config import JournalSettings


def make_app() -> tuple[FastAPI, list[str]]:
    """Собирает проверочную ручку с настоящей зависимостью аутентификации."""
    authenticate = getattr(dependencies, "get_authenticated_service", None)
    assert callable(authenticate), (
        "Добавь get_authenticated_service в api/dependencies.py"
    )
    principal_type = getattr(dependencies, "ServicePrincipal", None)
    assert principal_type is not None, "Добавь ServicePrincipal в api/dependencies.py"

    app = FastAPI()
    app.state.settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-journal-service-token",
        _env_file=None,
    )
    calls: list[str] = []

    @app.get("/protected")
    def protected(service: Annotated[principal_type, Depends(authenticate)]):
        calls.append(service.service_name)
        assert isinstance(service.permissions, frozenset)
        return {
            "service_name": service.service_name,
            "permissions": sorted(service.permissions),
        }

    return app, calls


def request_protected(
    app: FastAPI, headers: list[tuple[bytes, bytes]]
) -> httpx.Response:
    """Выполняет HTTP-запрос внутри процесса, без запуска сервера."""

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/protected", headers=headers)

    return asyncio.run(request())


@pytest.mark.parametrize("scheme", ["Bearer", "bearer"])
def test_valid_token_identifies_backoffice(scheme: str) -> None:
    """Распознаёт Backoffice и возвращает права, а не секретный токен."""
    app, calls = make_app()

    response = request_protected(
        app,
        [(b"authorization", f"{scheme} test-journal-service-token".encode())],
    )

    assert response.status_code == 200
    assert response.json() == {
        "service_name": "backoffice",
        "permissions": [
            "class-periods:write",
            "classes:read",
            "classes:write",
            "student-current-class:read",
            "teacher-classes:read",
            "teacher-classes:write",
        ],
    }
    assert calls == ["backoffice"]


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"authorization", b"")],
        [(b"authorization", b"Bearer")],
        [(b"authorization", b"Bearer ")],
        [(b"authorization", b"Bearer wrong-token")],
        [(b"authorization", b"Basic test-journal-service-token")],
        [(b"authorization", b"Bearer \xff")],
        [(b"x-backoffice-service-token", b"test-journal-service-token")],
    ],
)
def test_invalid_credentials_do_not_execute_route(
    headers: list[tuple[bytes, bytes]],
) -> None:
    """Отклоняет неподходящие данные с 401 и Bearer challenge до вызова ручки."""
    app, calls = make_app()

    response = request_protected(app, headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert calls == []


@pytest.mark.parametrize(
    ("permissions", "required", "expected_status"),
    [
        (frozenset({"classes:read"}), "classes:read", 200),
        (frozenset({"classes:read"}), "classes:write", 403),
        (frozenset({"classes:write"}), "classes:read", 403),
        (frozenset(), "classes:read", 403),
        (frozenset({"classes:read", "classes:write"}), "classes:write", 200),
    ],
)
def test_permission_dependency_checks_required_permission(
    permissions: frozenset[str], required: str, expected_status: int
) -> None:
    """Проверяет права через HTTP с подменой только распознанного сервиса."""
    app, _ = make_app()
    calls = []
    app.dependency_overrides[dependencies.get_authenticated_service] = lambda: (
        dependencies.ServicePrincipal(
            service_name="test-service", permissions=permissions
        )
    )

    @app.get("/permission", dependencies=[Depends(RequireServicePermission(required))])
    async def protected_by_permission():
        calls.append("executed")
        return {"status": "ok"}

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/permission")

    response = asyncio.run(request())

    assert response.status_code == expected_status
    assert calls == (["executed"] if expected_status == 200 else [])
    if expected_status == 403:
        assert response.json() == {"detail": "Insufficient service permissions"}


@pytest.mark.parametrize("token", [None, "wrong-token", "test-journal-service-token"])
def test_permission_dependency_authenticates_before_authorizing(
    token: str | None,
) -> None:
    """Возвращает 401 для неверных credentials и 403 для отсутствующего права."""
    app, _ = make_app()
    calls = []

    @app.get(
        "/permission",
        dependencies=[Depends(RequireServicePermission("classes:delete"))],
    )
    async def protected_by_permission():
        calls.append("executed")
        return {"status": "ok"}

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {} if token is None else {"Authorization": f"Bearer {token}"}
            return await client.get("/permission", headers=headers)

    response = asyncio.run(request())

    assert response.status_code == (
        403 if token == "test-journal-service-token" else 401
    )
    assert calls == []
    if response.status_code == 401:
        assert response.headers["www-authenticate"] == "Bearer"
