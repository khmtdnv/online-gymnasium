"""Публичные чтения используют текущий teacher, не входящий actor-заголовок."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_student_homework_api import make_app

from gateway_service.domain.user import Role


@pytest.mark.parametrize(
    "role,active,with_token,status",
    [
        (Role.TEACHER, True, False, 401),
        (Role.TEACHER, False, True, 401),
        (Role.STUDENT, True, True, 403),
        (Role.PARENT, True, True, 403),
        (Role.ADMIN, True, True, 403),
    ],
)
@pytest.mark.parametrize(
    "path",
    ["/api/v1/lessons?date_from=2026-10-19&date_to=2026-10-25", "/api/v1/lessons/11"],
)
def test_teacher_gate(path, role, active, with_token, status):
    app, token, _ = make_app(role, active)
    app.state.schedule_client = AsyncMock()
    with TestClient(app) as client:
        response = client.get(
            path, headers={"Authorization": f"Bearer {token}"} if with_token else {}
        )
    assert response.status_code == status


def test_list_uses_current_uuid_not_external_header():
    app, token, _ = make_app(Role.TEACHER)
    schedule = AsyncMock()
    schedule.list_teacher_lessons.return_value = []
    app.state.schedule_client = schedule
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/lessons?date_from=2026-10-19&date_to=2026-10-25",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Teacher-ID": str(UUID(int=99)),
            },
        )
    assert response.status_code == 200 and response.json() == []
    assert schedule.list_teacher_lessons.await_args.kwargs["teacher_id"] == UUID(int=1)


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?date_from=2026-10-19",
        "?date_from=2026-10-19&date_to=2026-10-26",
        "?date_from=2026-10-19&date_to=2026-10-25&teacher_id=bad",
    ],
)
def test_invalid_public_query(query):
    app, token, _ = make_app(Role.TEACHER)
    app.state.schedule_client = AsyncMock()
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/lessons" + query, headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 422
        )
