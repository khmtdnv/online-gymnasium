import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import jwt
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient, Response

from gateway_service.api.security import RequireRoles
from gateway_service.app import create_app
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.config import GatewaySettings
from gateway_service.domain.user import Role, User
from gateway_service.infrastructure.token_service import PyJwtTokenService


@pytest.fixture
def settings() -> GatewaySettings:
    return GatewaySettings(
        database_url="postgresql+asyncpg://gateway:password@localhost/gateway",
        jwt_secret="test-signing-secret-for-hs256-32-bytes",
        backoffice_service_token="test-backoffice-token",
        _env_file=None,
    )


@pytest.fixture
def user() -> User:
    return User(
        id=UUID("75ef34f4-2588-41b1-b41e-cbd058c6025c"),
        email="teacher@example.com",
        role=Role.TEACHER,
        password_hash="stored-hash",
        is_active=True,
        first_name="Тестовый",
        last_name="Пользователь",
    )


def protected_app(
    settings: GatewaySettings,
    user: User | None,
    allowed_roles: tuple[Role, ...] = (Role.TEACHER,),
) -> tuple[FastAPI, list[UUID]]:
    """Собирает тестовую ручку с настоящей цепочкой проверок и памятью вместо БД."""

    async def get_by_id(user_id: UUID) -> User | None:
        return user if user is not None and user.id == user_id else None

    @asynccontextmanager
    async def uow_factory():
        yield SimpleNamespace(users=SimpleNamespace(get_by_id=get_by_id))

    app = create_app(
        settings, AsyncMock(), uow_factory, Mock(), PyJwtTokenService(settings)
    )
    reached: list[UUID] = []
    require_roles = RequireRoles(allowed_roles=allowed_roles)

    @app.get("/test/protected")
    async def protected(
        current_user: Annotated[GetCurrentUserResult, Depends(require_roles)],
    ) -> GetCurrentUserResult:
        reached.append(current_user.id)
        return current_user

    return app, reached


def request_protected(app: FastAPI, authorization: str | None) -> Response:
    async def request() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {} if authorization is None else {"Authorization": authorization}
            return await client.get("/test/protected", headers=headers)

    return asyncio.run(request())


def assert_authentication_error(response: Response, reached: list[UUID]) -> None:
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_error"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert reached == []


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.TEACHER, 200),
        (Role.STUDENT, 403),
        (Role.PARENT, 403),
        (Role.ADMIN, 403),
    ],
)
def test_teacher_only_route_enforces_current_user_role(
    settings: GatewaySettings, user: User, role: Role, expected_status: int
) -> None:
    user = replace(user, role=role)
    app, reached = protected_app(settings, user)
    token = PyJwtTokenService(settings).issue_access(user)

    response = request_protected(app, f"Bearer {token}")

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json() == {
            "id": str(user.id),
            "email": "teacher@example.com",
            "role": "teacher",
            "first_name": "Тестовый",
            "last_name": "Пользователь",
            "middle_name": "",
        }
        assert reached == [user.id]
    else:
        assert response.json()["error"]["code"] == "forbidden"
        assert (
            response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
        )
        assert "WWW-Authenticate" not in response.headers
        assert reached == []


@pytest.mark.parametrize("role", [Role.TEACHER, Role.ADMIN])
def test_route_allows_each_explicitly_configured_role(
    settings: GatewaySettings, user: User, role: Role
) -> None:
    user = replace(user, role=role)
    app, reached = protected_app(settings, user, (Role.TEACHER, Role.ADMIN))
    token = PyJwtTokenService(settings).issue_access(user)

    response = request_protected(app, f"Bearer {token}")

    assert response.status_code == 200
    assert response.json()["role"] == role.value
    assert reached == [user.id]


@pytest.mark.parametrize("authorization", [None, "Basic credentials", "Bearer"])
def test_role_protected_route_requires_bearer_credentials(
    settings: GatewaySettings, user: User, authorization: str | None
) -> None:
    app, reached = protected_app(settings, user)

    response = request_protected(app, authorization)

    assert_authentication_error(response, reached)


@pytest.mark.parametrize("invalid_token", ["malformed", "refresh", "expired", "forged"])
def test_role_protected_route_rejects_invalid_access_token(
    settings: GatewaySettings, user: User, invalid_token: str
) -> None:
    app, reached = protected_app(settings, user)
    token_service = PyJwtTokenService(settings)
    if invalid_token == "malformed":
        token = "not-a-jwt"
    elif invalid_token == "refresh":
        token = token_service.issue_refresh(user).token
    else:
        expires_at = datetime.now(UTC) + timedelta(minutes=5)
        if invalid_token == "expired":
            expires_at = datetime.now(UTC) - timedelta(minutes=5)
        token = jwt.encode(
            {
                "sub": str(user.id),
                "role": "teacher",
                "type": "access",
                "exp": expires_at,
            },
            settings.jwt_secret
            if invalid_token == "expired"
            else "another-signing-secret-for-hs256-32-bytes",
            algorithm="HS256",
        )

    response = request_protected(app, f"Bearer {token}")

    assert_authentication_error(response, reached)


@pytest.mark.parametrize("unavailable_user", ["missing", "inactive"])
def test_valid_access_token_does_not_grant_access_to_unavailable_user(
    settings: GatewaySettings, user: User, unavailable_user: str
) -> None:
    stored_user = (
        None if unavailable_user == "missing" else replace(user, is_active=False)
    )
    app, reached = protected_app(settings, stored_user)
    token = PyJwtTokenService(settings).issue_access(user)

    response = request_protected(app, f"Bearer {token}")

    assert_authentication_error(response, reached)


@pytest.mark.parametrize(
    ("token_role", "current_role", "expected_status"),
    [(Role.TEACHER, Role.STUDENT, 403), (Role.STUDENT, Role.TEACHER, 200)],
)
def test_role_check_uses_database_role_instead_of_old_jwt_role(
    settings: GatewaySettings,
    user: User,
    token_role: Role,
    current_role: Role,
    expected_status: int,
) -> None:
    token = PyJwtTokenService(settings).issue_access(replace(user, role=token_role))
    app, reached = protected_app(settings, replace(user, role=current_role))

    response = request_protected(app, f"Bearer {token}")

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["role"] == "teacher"
        assert reached == [user.id]
    else:
        assert response.json()["error"]["code"] == "forbidden"
        assert reached == []


def test_empty_allowed_roles_deny_authenticated_user(
    settings: GatewaySettings, user: User
) -> None:
    app, reached = protected_app(settings, user, ())
    token = PyJwtTokenService(settings).issue_access(user)

    response = request_protected(app, f"Bearer {token}")

    assert response.status_code == 403
    assert reached == []
