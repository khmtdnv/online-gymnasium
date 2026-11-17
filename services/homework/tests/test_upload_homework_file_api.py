"""HTTP-загрузка закрывает spool и не пропускает неподтверждённого Gateway."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from homework_service.app import create_app
from homework_service.application.homework_files import HomeworkFileResult
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.config import HomeworkSettings

PATH = "/internal/homework/1/files/8"
TEACHER = UUID(int=2)
HEADERS = {"Authorization": "Bearer gw", "X-Teacher-ID": str(TEACHER)}
SAVED = {
    "id": 8,
    "homework_id": 1,
    "file_name": "Задачи.txt",
    "size_bytes": 6,
    "content_type": "text/plain",
    "upload_status": "ready",
}


def app(error=None):
    seen = []

    async def handle(command, stream):
        seen.append((command, stream, stream.read()))
        if error:
            raise error
        return HomeworkFileResult(**SAVED)

    handler = SimpleNamespace(handle=AsyncMock(side_effect=handle))
    application = create_app(
        HomeworkSettings(
            database_url="unused", gateway_service_token="gw", _env_file=None
        ),
        AsyncMock(),
        upload_homework_file_handler=handler,
    )
    return application, handler, seen


def test_upload_and_ready_retry_close_the_received_stream():
    application, handler, seen = app()
    with TestClient(application) as client:
        for _ in range(2):
            response = client.put(
                PATH, headers=HEADERS, files={"file": ("Задачи.txt", b"answer")}
            )
            assert response.status_code == 200, response.text
            assert response.json() == SAVED
    assert handler.handle.await_count == 2
    assert all(stream.closed and body == b"answer" for _, stream, body in seen)
    command = seen[0][0]
    assert (command.teacher_id, command.homework_id, command.file_id) == (TEACHER, 1, 8)


@pytest.mark.parametrize(
    "error,status,code",
    [
        (HomeworkNotFoundError(), 404, "homework_not_found"),
        (HomeworkAccessDeniedError(), 403, "access_denied"),
        (ValueError("secret bytes"), 422, "invalid_homework_file"),
        (OSError("secret storage"), 503, "service_unavailable"),
        (OwnerLookupUnavailableError(), 503, "service_unavailable"),
    ],
)
def test_upload_errors_are_safe_and_close_the_stream(error, status, code):
    application, _, seen = app(error)
    with TestClient(application) as client:
        response = client.put(
            PATH, headers=HEADERS, files={"file": ("x.txt", b"answer")}
        )
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert "secret" not in response.text
    assert seen[0][1].closed


def test_upload_requires_service_token_before_body_parsing():
    application, handler, _ = app()
    with TestClient(application) as client:
        response = client.put(
            PATH, headers={"X-Teacher-ID": str(TEACHER)}, content=b"bad"
        )
    assert response.status_code == 401
    handler.handle.assert_not_awaited()


def test_upload_rejects_additional_parts_before_handler():
    application, handler, _ = app()
    with TestClient(application) as client:
        response = client.put(
            PATH,
            headers=HEADERS,
            files=[("file", ("x.txt", b"x")), ("file", ("y.txt", b"y"))],
        )
    assert response.status_code == 422
    handler.handle.assert_not_awaited()
