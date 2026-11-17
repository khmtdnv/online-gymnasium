"""Контракт закрытого создания: доверенный автор и безопасные отказы."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from homework_service.app import create_app
from homework_service.application.homework import HomeworkResult
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkAlreadyExistsError,
    InvalidHomeworkDataError,
    LessonNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.config import HomeworkSettings

TEACHER = "75ef34f4-2588-41b1-b41e-cbd058c6025c"
PATH = "/internal/lessons/11/homework"
HEADERS = {"Authorization": "Bearer gateway-test", "X-Teacher-ID": TEACHER}
RESULT = {
    "id": 1,
    "issued_lesson_id": 11,
    "class_id": 7,
    "subject_id": 3,
    "author_id": TEACHER,
    "description": "Решить задачу",
    "due_lesson_id": 12,
    "manual_due_datetime": None,
    "created_at": "2026-10-17T10:00:00Z",
}


def make_app(handler, **settings):
    return create_app(
        HomeworkSettings(
            database_url="test",
            gateway_service_token="gateway-test",
            _env_file=None,
            **settings,
        ),
        AsyncMock(),
        create_homework_handler=handler,
    )


def test_create_passes_expected_file_metadata_without_bytes():
    from tests.test_homework_files import file_input

    handler = AsyncMock()
    handler.handle.return_value = HomeworkResult.model_validate(
        {
            **RESULT,
            "files": [
                {
                    "id": 8,
                    "homework_id": 1,
                    "file_name": "Задачи.pdf",
                    "size_bytes": 1024,
                    "content_type": "application/pdf",
                    "upload_status": "pending",
                }
            ],
        }
    )
    with TestClient(make_app(handler)) as client:
        response = client.post(
            PATH,
            headers=HEADERS,
            json={
                "description": "Решить задачу",
                "due_lesson_id": 12,
                "files": [file_input()],
            },
        )
    assert response.status_code == 201
    assert response.json()["files"][0]["upload_status"] == "pending"
    assert handler.handle.await_args.args[0].files[0].content_sha256 == "a" * 64


@pytest.mark.parametrize(
    "due",
    [
        {"due_lesson_id": 12},
        {"manual_due_datetime": "2026-10-20T10:00:00+00:00"},
    ],
)
def test_create_returns_saved_result_with_trusted_teacher(due):
    saved = (
        {**RESULT, "due_lesson_id": None, **due}
        if "manual_due_datetime" in due
        else RESULT
    )
    handler = AsyncMock()
    handler.handle.return_value = HomeworkResult.model_validate(saved)
    with TestClient(make_app(handler)) as client:
        response = client.post(
            PATH, headers=HEADERS, json={"description": "  Решить задачу  ", **due}
        )
        assert response.status_code == 201
        assert response.json()["author_id"] == TEACHER
        assert PATH not in client.get("/openapi.json").json()["paths"]
    command = handler.handle.await_args.args[0]
    assert command.teacher_id == UUID(TEACHER)
    assert command.issued_lesson_id == 11
    assert command.description == "Решить задачу"


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic gateway-test"])
def test_invalid_service_credentials_never_call_handler(authorization):
    handler = AsyncMock()
    headers = {"X-Teacher-ID": TEACHER}
    if authorization:
        headers["Authorization"] = authorization
    with TestClient(make_app(handler)) as client:
        response = client.post(
            PATH, headers=headers, json={"description": "x", "due_lesson_id": 12}
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_service_credentials"
    handler.handle.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"description": "x"},
        {
            "description": "x",
            "due_lesson_id": 12,
            "manual_due_datetime": "2026-10-20T10:00:00Z",
        },
        {"description": "x", "manual_due_datetime": "2026-10-20T10:00:00"},
        {"description": "x", "manual_due_datetime": 1900000000},
        {"description": "x", "manual_due_datetime": "1900000000"},
        {"description": " ", "due_lesson_id": 12},
        {"description": "x", "due_lesson_id": True},
        {"description": "x", "due_lesson_id": 12, "author_id": TEACHER},
    ],
)
def test_invalid_body_is_rejected_before_handler(payload):
    handler = AsyncMock()
    with TestClient(make_app(handler)) as client:
        assert client.post(PATH, headers=HEADERS, json=payload).status_code == 422
    handler.handle.assert_not_awaited()


@pytest.mark.parametrize("teacher", [None, "not-uuid"])
def test_missing_or_invalid_teacher_is_rejected(teacher):
    handler = AsyncMock()
    headers = {"Authorization": "Bearer gateway-test"}
    if teacher:
        headers["X-Teacher-ID"] = teacher
    with TestClient(make_app(handler)) as client:
        assert (
            client.post(
                PATH, headers=headers, json={"description": "x", "due_lesson_id": 12}
            ).status_code
            == 422
        )
    handler.handle.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (HomeworkAccessDeniedError(), 403, "access_denied"),
        (LessonNotFoundError(), 404, "lesson_not_found"),
        (HomeworkAlreadyExistsError(), 409, "homework_already_exists"),
        (InvalidHomeworkDataError(), 422, "invalid_homework_data"),
        (OwnerLookupUnavailableError("secret"), 503, "service_unavailable"),
        (
            OperationalError("secret", {}, Exception("secret")),
            503,
            "service_unavailable",
        ),
        (ConnectionRefusedError("secret"), 503, "service_unavailable"),
    ],
)
def test_errors_have_safe_machine_codes(error, status, code):
    handler = AsyncMock()
    handler.handle.side_effect = error
    with TestClient(make_app(handler)) as client:
        response = client.post(
            PATH, headers=HEADERS, json={"description": "x", "due_lesson_id": 12}
        )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "secret" not in response.text


def test_unconfigured_creation_fails_closed_but_health_survives():
    with TestClient(
        create_app(HomeworkSettings(database_url="test", _env_file=None), AsyncMock())
    ) as client:
        assert client.get("/health/live").status_code == 200
        response = client.post(
            PATH, headers=HEADERS, json={"description": "x", "due_lesson_id": 12}
        )
        assert response.status_code == 503


@pytest.mark.parametrize("lesson_id", [0, -1, 2147483648, "banana"])
def test_invalid_lesson_path_never_calls_handler(lesson_id):
    handler = AsyncMock()
    with TestClient(make_app(handler)) as client:
        response = client.post(
            f"/internal/lessons/{lesson_id}/homework",
            headers=HEADERS,
            json={"description": "x", "due_lesson_id": 12},
        )
    assert response.status_code == 422
    handler.handle.assert_not_awaited()
