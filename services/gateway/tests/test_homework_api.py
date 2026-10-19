"""Публичная выдача ДЗ использует существующую проверку JWT и пользователя."""

import json
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

TEACHER = UUID("75ef34f4-2588-41b1-b41e-cbd058c6025c")
PATH = "/api/v1/lessons/11/homework"
BODY = {"description": "Решить задачу", "due_lesson_id": 12}
SAVED = {
    "id": 1,
    "issued_lesson_id": 11,
    "class_id": 7,
    "subject_id": 3,
    "author_id": str(TEACHER),
    "description": "Решить задачу",
    "due_lesson_id": 12,
    "manual_due_datetime": None,
    "created_at": "2026-10-17T10:00:00Z",
}


def make_app(*, role=Role.TEACHER, active=True, inject=True):
    from gateway_service.application.homework import HomeworkResult

    settings = GatewaySettings(
        database_url="test",
        jwt_secret="x" * 32,
        backoffice_service_token="test",
        _env_file=None,
    )
    user = User(
        id=TEACHER,
        email="teacher@example.com",
        first_name="Иван",
        last_name="Петров",
        role=role,
        password_hash="hash",
        is_active=active,
    )

    async def get_by_id(user_id):
        return user if user_id == user.id else None

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(users=SimpleNamespace(get_by_id=get_by_id))

    token_service = PyJwtTokenService(settings)
    token = token_service.issue_access(user)
    client = AsyncMock()
    client.create_homework.return_value = HomeworkResult.model_validate_json(
        json.dumps(SAVED)
    )
    app = create_app(
        settings,
        AsyncMock(),
        factory,
        Mock(),
        token_service,
        homework_client=client if inject else None,
    )
    return app, token, client


def test_teacher_creates_homework_and_external_actor_is_not_forwarded():
    app, token, homework = make_app()
    with TestClient(app) as client:
        response = client.post(
            PATH,
            json=BODY,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Teacher-ID": "75ef34f4-2588-41b1-b41e-cbd058c6025d",
            },
        )
    assert response.status_code == 201
    assert response.json()["author_id"] == str(TEACHER)
    assert homework.create_homework.await_args.kwargs["teacher_id"] == TEACHER


@pytest.mark.parametrize(
    ("role", "active", "with_token", "status"),
    [
        (Role.TEACHER, True, False, 401),
        (Role.TEACHER, False, True, 401),
        (Role.STUDENT, True, True, 403),
        (Role.PARENT, True, True, 403),
        (Role.ADMIN, True, True, 403),
    ],
)
def test_authentication_and_role_fail_before_owner_call(
    role, active, with_token, status
):
    app, token, homework = make_app(role=role, active=active)
    with TestClient(app) as client:
        response = client.post(
            PATH,
            json=BODY,
            headers={
                "Authorization": f"Bearer {token}",
            }
            if with_token
            else {},
        )
    assert response.status_code == status
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    homework.create_homework.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {**BODY, "author_id": str(TEACHER)},
        {**BODY, "teacher_id": str(TEACHER)},
        {**BODY, "class_id": 7},
        {**BODY, "subject_id": 3},
        {"description": "x"},
        {**BODY, "manual_due_datetime": "2026-10-20T10:00:00Z"},
        {"description": "x", "manual_due_datetime": "2026-10-20T10:00:00"},
        {"description": "x", "manual_due_datetime": 1900000000},
        {"description": "x", "manual_due_datetime": "1900000000"},
    ],
)
def test_public_body_cannot_supply_owner_context(payload):
    app, token, homework = make_app()
    with TestClient(app) as client:
        response = client.post(
            PATH, json=payload, headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 422
    homework.create_homework.assert_not_awaited()


def test_unconfigured_integration_returns_safe_503():
    app, token, _ = make_app(inject=False)
    with TestClient(app) as client:
        response = client.post(
            PATH, json=BODY, headers={"Authorization": f"Bearer {token}"}
        )
        assert client.get("/health/live").status_code == 200
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Request failed"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (403, "access_denied"),
        (404, "lesson_not_found"),
        (409, "homework_already_exists"),
        (422, "invalid_homework_data"),
        (503, None),
    ],
)
def test_owner_errors_use_gateway_envelope_without_details(status, code):
    from gateway_service.application.homework import (
        HomeworkRequestError,
        HomeworkUnavailableError,
    )

    app, token, homework = make_app()
    homework.create_homework.side_effect = (
        HomeworkRequestError(status, code)
        if code
        else HomeworkUnavailableError("secret")
    )
    with TestClient(app) as client:
        response = client.post(
            PATH, json=BODY, headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == status
    assert "secret" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
