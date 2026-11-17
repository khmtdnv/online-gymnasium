"""Роль и UUID ученика берутся только из настоящей цепочки аутентификации."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from gateway_service.app import create_app
from gateway_service.config import GatewaySettings
from gateway_service.domain.user import Role, User
from gateway_service.infrastructure.token_service import PyJwtTokenService


def make_app(role=Role.STUDENT, active=True):
    settings = GatewaySettings(
        database_url="test",
        jwt_secret="x" * 32,
        backoffice_service_token="test",
        _env_file=None,
    )
    user = User(
        id=UUID(int=1),
        email="student@example.com",
        role=role,
        is_active=active,
        first_name="Иван",
        last_name="Петров",
        password_hash="x",
    )

    async def get_by_id(id):
        return user if id == user.id else None

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(users=SimpleNamespace(get_by_id=get_by_id))

    tokens = PyJwtTokenService(settings)
    homework = AsyncMock()
    homework.list_student_homework.return_value = []
    return (
        create_app(
            settings, AsyncMock(), factory, Mock(), tokens, homework_client=homework
        ),
        tokens.issue_access(user),
        homework,
    )


def test_active_student_list_ignores_external_student_header():
    app, token, homework = make_app()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/homework?limit=2&offset=1",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Student-ID": str(UUID(int=9)),
            },
        )
    assert response.status_code == 200 and response.json() == []
    assert homework.list_student_homework.await_args.kwargs == {
        "student_id": UUID(int=1),
        "limit": 2,
        "offset": 1,
    }


@pytest.mark.parametrize("path", ["/api/v1/homework", "/api/v1/homework/1"])
@pytest.mark.parametrize(
    ("role", "active", "token_present", "status"),
    [
        (Role.STUDENT, True, False, 401),
        (Role.STUDENT, False, True, 401),
        (Role.TEACHER, True, True, 403),
        (Role.PARENT, True, True, 403),
        (Role.ADMIN, True, True, 403),
    ],
)
def test_authentication_and_role_gate_both_reads(
    path, role, active, token_present, status
):
    app, token, homework = make_app(role, active)
    with TestClient(app) as client:
        response = client.get(
            path, headers={"Authorization": f"Bearer {token}"} if token_present else {}
        )
    assert response.status_code == status
    homework.list_student_homework.assert_not_awaited()
    homework.get_student_homework.assert_not_awaited()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/homework?student_id=other",
        "/api/v1/homework?limit=0",
        "/api/v1/homework?offset=-1",
        "/api/v1/homework/0",
    ],
)
def test_bad_query_cannot_choose_another_user(path):
    app, token, homework = make_app()
    with TestClient(app) as client:
        response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 422
    homework.list_student_homework.assert_not_awaited()


def test_not_found_is_gateway_error_envelope():
    from gateway_service.application.homework import HomeworkRequestError

    app, token, homework = make_app()
    homework.get_student_homework.side_effect = HomeworkRequestError(
        404, "homework_not_found"
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/homework/1", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Homework not found"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
