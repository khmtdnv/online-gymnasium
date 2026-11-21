"""Административное расписание: справочники и операции с уроками."""

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

LESSON = {
    "id": 11,
    "class_id": 7,
    "teacher_id": str(UUID(int=5)),
    "subject_id": 2,
    "starts_at": "2026-11-23T04:00:00Z",
    "ends_at": "2026-11-23T04:45:00Z",
    "status": "scheduled",
    "version": 3,
}


def make_admin_app(role=Role.ADMIN):
    settings = GatewaySettings(
        database_url="test",
        jwt_secret="x" * 32,
        backoffice_service_token="test",
        _env_file=None,
    )
    user = User(
        id=UUID(int=1),
        email="admin@example.com",
        role=role,
        is_active=True,
        first_name="Анна",
        last_name="Сидорова",
        password_hash="x",
    )

    async def get_by_id(id):
        return user if id == user.id else None

    teacher = SimpleNamespace(
        id=UUID(int=5),
        email="teacher01@demo.og.test",
        role=Role.TEACHER,
        is_active=True,
        first_name="Иван",
        last_name="Иванов",
        middle_name="Иванович",
    )

    async def search_users(q, role, active_only, limit):
        return [teacher]

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(
            users=SimpleNamespace(get_by_id=get_by_id, search_users=search_users)
        )

    tokens = PyJwtTokenService(settings)
    app = create_app(
        settings, AsyncMock(), factory, Mock(), tokens, homework_client=AsyncMock()
    )
    schedule = AsyncMock()
    schedule.admin_list_lessons.return_value = [dict(LESSON)]
    schedule.admin_create_lesson.return_value = (201, dict(LESSON))
    schedule.admin_update_lesson.return_value = (200, dict(LESSON))
    schedule.admin_cancel_lesson.return_value = (200, dict(LESSON))
    schedule.list_subjects.return_value = [{"id": 2, "name": "Русский язык"}]
    app.state.schedule_client = schedule

    journal = AsyncMock()
    journal.list_classes.return_value = [
        SimpleNamespace(
            id=7, name="7А", study_year=2026, created_at="2026-09-01T00:00:00Z"
        )
    ]
    app.state.journal_client = journal
    return app, tokens.issue_access(user), schedule, journal


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("role", [Role.TEACHER, Role.STUDENT, Role.PARENT])
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/schedule/lessons?class_id=7&date=2026-11-23",
        "/api/v1/schedule/directory",
        "/api/v1/schedule/teachers?q=ива",
    ],
)
def test_admin_gate(role, path):
    app, token, _, _ = make_admin_app(role)
    with TestClient(app) as client:
        response = client.get(path, headers=auth(token))
    assert response.status_code == 403


def test_list_lessons_maps_rows():
    app, token, schedule, _ = make_admin_app()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/schedule/lessons?class_id=7&date=2026-11-23", headers=auth(token)
        )
    assert response.status_code == 200
    assert response.json() == [LESSON]
    schedule.admin_list_lessons.assert_awaited_once_with(7, "2026-11-23")


def test_list_lessons_requires_class_and_date():
    app, token, _, _ = make_admin_app()
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/schedule/lessons?class_id=7", headers=auth(token)
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/schedule/lessons?class_id=0&date=2026-11-23",
                headers=auth(token),
            ).status_code
            == 422
        )


def test_create_lesson_requires_idempotency_key():
    app, token, _, _ = make_admin_app()
    body = {
        "class_id": 7,
        "teacher_id": str(UUID(int=5)),
        "subject_id": 2,
        "starts_at": "2026-11-23T04:00:00Z",
        "ends_at": "2026-11-23T04:45:00Z",
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/schedule/lessons", json=body, headers=auth(token)
        )
    assert response.status_code == 400


def test_create_lesson_forwards_key_and_body():
    app, token, schedule, _ = make_admin_app()
    body = {
        "class_id": 7,
        "teacher_id": str(UUID(int=5)),
        "subject_id": 2,
        "starts_at": "2026-11-23T04:00:00Z",
        "ends_at": "2026-11-23T04:45:00Z",
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/schedule/lessons",
            json=body,
            headers={**auth(token), "Idempotency-Key": "abc-123"},
        )
    assert response.status_code == 201 and response.json() == LESSON
    args = schedule.admin_create_lesson.await_args
    assert args.args[1] == "abc-123" and args.args[0]["class_id"] == 7


def test_create_lesson_conflict_becomes_409():
    app, token, schedule, _ = make_admin_app()
    schedule.admin_create_lesson.return_value = (409, {"detail": "teacher busy"})
    body = {
        "class_id": 7,
        "teacher_id": str(UUID(int=5)),
        "subject_id": 2,
        "starts_at": "2026-11-23T04:00:00Z",
        "ends_at": "2026-11-23T04:45:00Z",
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/schedule/lessons",
            json=body,
            headers={**auth(token), "Idempotency-Key": "abc-123"},
        )
    assert response.status_code == 409


def test_update_lesson_forwards_version_conflict():
    app, token, schedule, _ = make_admin_app()
    schedule.admin_update_lesson.return_value = (409, {"detail": "version mismatch"})
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/schedule/lessons/11",
            json={
                "starts_at": "2026-11-23T05:00:00Z",
                "ends_at": "2026-11-23T05:45:00Z",
                "expected_version": 2,
            },
            headers=auth(token),
        )
    assert response.status_code == 409


def test_update_lesson_ok():
    app, token, schedule, _ = make_admin_app()
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/schedule/lessons/11",
            json={
                "starts_at": "2026-11-23T05:00:00Z",
                "ends_at": "2026-11-23T05:45:00Z",
                "expected_version": 3,
            },
            headers=auth(token),
        )
    assert response.status_code == 200 and response.json()["version"] == 3
    schedule.admin_update_lesson.assert_awaited_once()


def test_cancel_lesson_forwards_body():
    app, token, schedule, _ = make_admin_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/schedule/lessons/11/cancel",
            json={"expected_version": 3},
            headers=auth(token),
        )
    assert response.status_code == 200
    schedule.admin_cancel_lesson.assert_awaited_once_with(11, {"expected_version": 3})


def test_directory_merges_classes_and_subjects():
    app, token, _, journal = make_admin_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/schedule/directory", headers=auth(token))
    assert response.status_code == 200
    data = response.json()
    assert data["classes"] == [{"id": 7, "name": "7А"}]
    assert data["subjects"] == [{"id": 2, "name": "Русский язык"}]
    journal.list_classes.assert_awaited()


def test_directory_without_journal_is_503():
    app, token, _, _ = make_admin_app()
    app.state.journal_client = None
    with TestClient(app) as client:
        response = client.get("/api/v1/schedule/directory", headers=auth(token))
    assert response.status_code == 503


def test_teachers_search_returns_full_name():
    app, token, _, _ = make_admin_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/schedule/teachers?q=иван", headers=auth(token))
    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["full_name"] == "Иванов Иван Иванович"
    assert rows[0]["email"] == "teacher01@demo.og.test"


def test_teachers_search_rejects_short_query():
    app, token, _, _ = make_admin_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/schedule/teachers?q=и", headers=auth(token))
    assert response.status_code == 422
