"""Закрытое чтение ДЗ не принимает ученика из query и требует Gateway."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from homework_service.app import create_app
from homework_service.application.ports.errors import OwnerLookupUnavailableError
from homework_service.config import HomeworkSettings

HEADERS = {"Authorization": "Bearer gw", "X-Student-ID": str(UUID(int=1))}


def app(handlers=True):
    many, one = AsyncMock(), AsyncMock()
    many.handle.return_value = []
    kwargs = (
        {"list_student_homework_handler": many, "get_student_homework_handler": one}
        if handlers
        else {}
    )
    return (
        create_app(
            HomeworkSettings(
                database_url="test", gateway_service_token="gw", _env_file=None
            ),
            AsyncMock(),
            **kwargs,
        ),
        many,
        one,
    )


def test_list_uses_trusted_header_and_validated_pagination():
    application, many, _ = app()
    with TestClient(application) as client:
        response = client.get("/internal/homework?limit=2&offset=1", headers=HEADERS)
        assert response.status_code == 200 and response.json() == []
        assert "/internal/homework" not in client.get("/openapi.json").json()["paths"]
    query = many.handle.await_args.args[0]
    assert (query.student_id, query.limit, query.offset) == (UUID(int=1), 2, 1)


@pytest.mark.parametrize(
    "path",
    [
        "/internal/homework?limit=0",
        "/internal/homework?limit=101",
        "/internal/homework?offset=-1",
        "/internal/homework?offset=2147483648",
        "/internal/homework?student_id=other",
        "/internal/homework/0",
    ],
)
def test_bad_parameters_never_call_handler(path):
    application, many, one = app()
    with TestClient(application) as client:
        assert client.get(path, headers=HEADERS).status_code == 422
    many.handle.assert_not_awaited()
    one.handle.assert_not_awaited()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Student-ID": str(UUID(int=1))},
        {"Authorization": "Bearer bad", "X-Student-ID": str(UUID(int=1))},
    ],
)
def test_missing_credentials_cannot_read(headers):
    application, many, _ = app()
    with TestClient(application) as client:
        assert client.get("/internal/homework", headers=headers).status_code == 401
    many.handle.assert_not_awaited()


def test_no_handlers_is_unavailable_not_empty():
    application, _, _ = app(handlers=False)
    with TestClient(application) as client:
        assert client.get("/internal/homework", headers=HEADERS).status_code == 503
        assert client.get("/health/live").status_code == 200


@pytest.mark.parametrize("path", ["/internal/homework", "/internal/homework/1"])
def test_unknown_owner_result_is_unavailable(path):
    application, many, one = app()
    many.handle.side_effect = one.handle.side_effect = OwnerLookupUnavailableError(
        "secret"
    )
    with TestClient(application) as client:
        response = client.get(path, headers=HEADERS)
    assert response.status_code == 503
    assert "secret" not in response.text


def test_absent_or_foreign_id_has_safe_404():
    from homework_service.application.ports.errors import HomeworkNotFoundError

    application, _, one = app()
    one.handle.side_effect = HomeworkNotFoundError
    with TestClient(application) as client:
        response = client.get("/internal/homework/1", headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "homework_not_found"
