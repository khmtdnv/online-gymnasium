"""Контракт защищённой ручки чтения пользователей Journal."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from gateway_service.app import create_app
from gateway_service.config import GatewaySettings
from gateway_service.domain.user import Role, User

USER_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
PATH = f"/internal/users/{USER_ID}"
AUTH = {"Authorization": "Bearer journal-only-test-token"}


def make_app(user=None, *, secret="journal-only-test-token", error=None):
    settings = GatewaySettings(
        database_url="postgresql+asyncpg://gateway:test@localhost/gateway",
        jwt_secret="test-signing-secret-for-hs256-32-bytes",
        backoffice_service_token="backoffice-only-test-token",
        journal_service_token=secret,
        _env_file=None,
    )
    users = SimpleNamespace(get_by_id=AsyncMock(return_value=user, side_effect=error))
    uow = AsyncMock()
    uow.__aenter__.return_value = SimpleNamespace(users=users)
    uow.__aexit__.return_value = False
    factory = Mock(return_value=uow)
    return create_app(settings, AsyncMock(), factory, Mock(), Mock()), factory


def get(app, *, headers=AUTH, path=PATH):
    async def send():
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            return await client.get(path, headers=headers)

    return asyncio.run(send())


def test_internal_user_response_has_only_three_fields() -> None:
    user = User(
        USER_ID,
        "private@example.com",
        Role.STUDENT,
        "private-hash",
        True,
        first_name="Тестовый",
        last_name="Пользователь",
    )
    app, _ = make_app(user)
    response = get(app)
    assert response.status_code == 200
    assert response.json() == {"id": str(USER_ID), "role": "student", "is_active": True}


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("active", [True, False])
def test_internal_lookup_accepts_each_role_and_inactive_user(role, active) -> None:
    app, _ = make_app(
        User(
            USER_ID,
            "private@example.com",
            role,
            "private-hash",
            active,
            first_name="Тестовый",
            last_name="Пользователь",
        )
    )
    response = get(app)
    assert response.status_code == 200
    assert response.json()["role"] == role.value
    assert response.json()["is_active"] is active


def test_missing_user_returns_404() -> None:
    app, _ = make_app()
    response = get(app)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_lookup_is_hidden_from_openapi() -> None:
    app, _ = make_app()
    assert get(app).status_code == 404
    assert "/internal/users/{user_id}" not in app.openapi()["paths"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer backoffice-only-test-token"},
        {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"},
        {"X-Backoffice-Service-Token": "backoffice-only-test-token"},
    ],
)
def test_service_auth_rejects_other_credentials_before_uow(headers) -> None:
    app, factory = make_app()
    response = get(app, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "authentication_error"
    factory.assert_not_called()


@pytest.mark.parametrize("secret", [None, ""])
def test_unconfigured_service_access_is_closed(secret) -> None:
    app, factory = make_app(secret=secret)
    response = get(app)
    assert response.status_code == 503
    assert "token" not in response.json()["error"]["message"].lower()
    factory.assert_not_called()


def test_invalid_uuid_does_not_open_uow() -> None:
    app, factory = make_app()
    response = get(app, path="/internal/users/not-a-uuid")
    assert response.status_code == 422
    factory.assert_not_called()


def test_repository_error_is_sanitized() -> None:
    app, _ = make_app(error=RuntimeError("database-password-private"))
    response = get(app)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "database-password-private" not in response.text


def test_settings_keep_existing_required_fields_only(monkeypatch) -> None:
    monkeypatch.delenv("JOURNAL_SERVICE_TOKEN", raising=False)
    app, _ = make_app(secret=None)
    assert app.state.settings.journal_service_token is None
    assert get(app, path="/health/live", headers={}).status_code == 200


def test_settings_read_separate_journal_secret(monkeypatch) -> None:
    monkeypatch.setenv("JOURNAL_SERVICE_TOKEN", "separate-test-secret")
    settings = GatewaySettings(
        database_url="postgresql+asyncpg://gateway:test@localhost/gateway",
        jwt_secret="test-signing-secret-for-hs256-32-bytes",
        backoffice_service_token="backoffice-only-test-token",
        _env_file=None,
    )
    assert settings.journal_service_token == "separate-test-secret"
