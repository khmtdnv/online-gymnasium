import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient

from gateway_service.api.dependencies import (
    get_login_handler,
    get_logout_handler,
    get_refresh_handler,
)
from gateway_service.api.security import check_auth_origin
from gateway_service.app import create_app
from gateway_service.config import GatewaySettings


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        "null",
        "http://localhost:8081",
        "https://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8080.evil.example",
        "http://localhost:8080/documents",
    ],
)
def test_auth_origin_rejects_missing_or_non_matching_source(origin: str | None) -> None:
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(public_origin="http://localhost:8080")
        )
    )
    headers = [] if origin is None else [(b"origin", origin.encode("ascii"))]
    request = Request({"type": "http", "app": app, "headers": headers})

    with pytest.raises(HTTPException) as error:
        check_auth_origin(request)

    assert error.value.status_code == 403
    assert error.value.detail == "Origin not allowed"


@pytest.mark.parametrize("origin", ["http://localhost:8080", "https://school.example"])
def test_auth_origin_accepts_exact_configured_source(origin: str) -> None:
    app = SimpleNamespace(
        state=SimpleNamespace(settings=SimpleNamespace(public_origin=origin))
    )
    request = Request(
        {"type": "http", "app": app, "headers": [(b"origin", origin.encode("ascii"))]}
    )

    assert check_auth_origin(request) is None


@pytest.mark.parametrize("endpoint", ["login", "refresh", "logout"])
@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        "null",
        "http://localhost:8081",
        "https://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8080.evil.example",
        "http://localhost:8080/documents",
    ],
)
def test_auth_post_rejects_untrusted_origin_before_handler(
    endpoint: str, origin: str | None
) -> None:
    settings = GatewaySettings(
        database_url="postgresql+asyncpg://gateway:password@localhost/gateway",
        jwt_secret="test-signing-secret-for-hs256-32-bytes",
        backoffice_service_token="test-backoffice-token",
        public_origin="http://localhost:8080",
        _env_file=None,
    )
    handler = SimpleNamespace(
        handle=AsyncMock(
            return_value=SimpleNamespace(access_token="access", refresh_token="refresh")
        )
    )
    app = create_app(settings, AsyncMock(), Mock(), Mock(), Mock())
    factory = {
        "login": get_login_handler,
        "refresh": get_refresh_handler,
        "logout": get_logout_handler,
    }[endpoint]
    app.dependency_overrides[factory] = lambda: handler

    async def request_auth():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            client.cookies.set("refresh_token", "old-refresh", path="/api/v1/auth")
            headers = {} if origin is None else {"Origin": origin}
            response = await client.post(
                f"/api/v1/auth/{endpoint}",
                headers=headers,
                json={"email": "student@example.com", "password": "secret"},
            )
            return response, client.cookies.get("refresh_token")

    response, remaining_cookie = asyncio.run(request_auth())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "set-cookie" not in response.headers
    assert remaining_cookie == "old-refresh"
    handler.handle.assert_not_awaited()


@pytest.mark.parametrize("endpoint", ["login", "refresh", "logout"])
@pytest.mark.parametrize("origin", ["http://localhost:8080", "https://school.example"])
def test_auth_post_accepts_configured_origin(endpoint: str, origin: str) -> None:
    settings = GatewaySettings(
        database_url="postgresql+asyncpg://gateway:password@localhost/gateway",
        jwt_secret="test-signing-secret-for-hs256-32-bytes",
        backoffice_service_token="test-backoffice-token",
        public_origin=origin,
        _env_file=None,
    )
    handler = SimpleNamespace(
        handle=AsyncMock(
            return_value=SimpleNamespace(access_token="access", refresh_token="refresh")
        )
    )
    app = create_app(settings, AsyncMock(), Mock(), Mock(), Mock())
    factory = {
        "login": get_login_handler,
        "refresh": get_refresh_handler,
        "logout": get_logout_handler,
    }[endpoint]
    app.dependency_overrides[factory] = lambda: handler

    async def request_auth():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            client.cookies.set("refresh_token", "old-refresh", path="/api/v1/auth")
            return await client.post(
                f"/api/v1/auth/{endpoint}",
                headers={"Origin": origin},
                json={"email": "student@example.com", "password": "secret"},
            )

    response = asyncio.run(request_auth())

    assert response.status_code == (204 if endpoint == "logout" else 200)
    if endpoint == "logout":
        assert response.content == b""
        assert "Max-Age=0" in response.headers["set-cookie"]
    else:
        assert response.json() == {"access_token": "access"}
        assert response.cookies.get("refresh_token") == "refresh"
    handler.handle.assert_awaited_once()
