"""Публичный upload проверяет роль до чтения тела и закрывает временный файл."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from test_homework_api import TEACHER, make_app
from test_homework_file_client import SAVED

from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkUnavailableError,
)
from gateway_service.application.homework_files import HomeworkFileResult
from gateway_service.domain.user import Role

PATH = "/api/v1/homework/1/files/8"


def setup(*, role=Role.TEACHER, error=None):
    application, token, _ = make_app(role=role)
    streams = []

    async def upload(**kwargs):
        streams.append(kwargs["stream"])
        assert kwargs["teacher_id"] == TEACHER
        assert kwargs["homework_id"] == 1 and kwargs["file_id"] == 8
        assert kwargs["file_name"] == "Задачи.txt"
        assert kwargs["stream"].read() == b"answer"
        if error:
            raise error
        return HomeworkFileResult(**SAVED)

    client = SimpleNamespace(upload_file=AsyncMock(side_effect=upload))
    application.state.homework_file_client = client
    application.state.injected_homework_file_client = client
    return application, token, client, streams


def test_upload_uses_authenticated_identity_not_browser_headers():
    application, token, upstream, streams = setup()
    with TestClient(application) as client:
        response = client.put(
            PATH,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Teacher-ID": "fake",
                "X-User-Role": "admin",
            },
            files={"file": ("Задачи.txt", b"answer")},
        )
    assert response.status_code == 200, response.text
    assert response.json() == SAVED
    upstream.upload_file.assert_awaited_once()
    assert streams[0].closed


@pytest.mark.parametrize(
    "role,with_token,status",
    [
        (Role.STUDENT, True, 403),
        (Role.PARENT, True, 403),
        (Role.ADMIN, True, 403),
        (Role.TEACHER, False, 401),
    ],
)
def test_upload_authentication_precedes_parsing(role, with_token, status):
    application, token, upstream, _ = setup(role=role)
    with TestClient(application) as client:
        response = client.put(
            PATH,
            headers={"Authorization": f"Bearer {token}"} if with_token else {},
            content=b"invalid",
        )
    assert response.status_code == status
    upstream.upload_file.assert_not_awaited()


@pytest.mark.parametrize(
    "files,data,status",
    [
        ({"file": ("Задачи.txt", b"")}, None, 422),
        ({"file": ("Задачи.txt", b"x" * 10485761)}, None, 413),
        ([("file", ("x.txt", b"x")), ("file", ("y.txt", b"y"))], None, 422),
        ({"file": ("Задачи.txt", b"answer")}, {"extra": "value"}, 422),
    ],
)
def test_upload_limits_before_forwarding(files, data, status):
    application, token, upstream, _ = setup()
    with TestClient(application) as client:
        response = client.put(
            PATH, headers={"Authorization": f"Bearer {token}"}, files=files, data=data
        )
    assert response.status_code == status
    upstream.upload_file.assert_not_awaited()


def test_upload_limits_actual_body_without_content_length():
    application, token, upstream, _ = setup()
    with TestClient(application) as client:
        response = client.put(
            PATH,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "multipart/form-data; boundary=example",
            },
            content=iter([b"x" * (11 * 1024 * 1024 + 1)]),
        )
    assert response.status_code == 413
    upstream.upload_file.assert_not_awaited()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (
            HomeworkRequestError(422, "invalid_homework_file"),
            422,
            "invalid_homework_file",
        ),
        (HomeworkRequestError(403, "access_denied"), 403, "access_denied"),
        (HomeworkUnavailableError("secret"), 503, "http_error"),
    ],
)
def test_upload_error_closes_spool_and_preserves_safe_code(error, status, code):
    application, token, _, streams = setup(error=error)
    with TestClient(application) as client:
        response = client.put(
            PATH,
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("Задачи.txt", b"answer")},
        )
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert "secret" not in response.text
    assert streams[0].closed
