"""Проверки единого формата ошибок Journal."""

import asyncio
import json
import logging
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from journal_service.app import _error_response, create_app
from journal_service.application.ports.errors import (
    DuplicateClassError,
    InvalidClassDataError,
)
from journal_service.config import JournalSettings


def test_invalid_internal_result_is_server_error_not_input_error() -> None:
    """Ошибка результата обработчика не должна превращаться в клиентский 422."""
    from datetime import UTC, datetime

    from journal_service.api.dependencies import get_create_class_handler
    from journal_service.application.classes import ClassResult

    class BrokenHandler:
        async def handle(self, command):
            return ClassResult(
                id="internal-secret",
                name="7А",
                study_year=2026,
                created_at=datetime(2026, 10, 14, tzinfo=UTC),
            )

    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    app = create_app(settings, Mock())
    app.dependency_overrides[get_create_class_handler] = lambda: BrokenHandler()

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/internal/classes",
                headers={"Authorization": "Bearer test-token"},
                json={"name": "7А", "study_year": 2026},
            )

    response = asyncio.run(request())
    assert response.status_code == 500
    assert "internal-secret" not in response.text
    assert response.json()["error"]["code"] == "internal_error"


@pytest.mark.parametrize(
    "headers",
    [
        None,
        {"WWW-Authenticate": "Bearer"},
        {"Retry-After": "60", "X-Request-ID": "old"},
    ],
)
def test_error_response_preserves_headers_and_current_request_id(
    headers: dict[str, str] | None,
) -> None:
    """Сохраняет чужие заголовки, но ID берёт из состояния текущего запроса."""
    request = Request({"type": "http"})
    request.state.request_id = "test-request-id"
    original = None if headers is None else headers.copy()

    response = _error_response(
        request,
        status_code=401,
        code="authentication_error",
        message="Invalid service token",
        headers=headers,
    )

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/json"
    assert json.loads(response.body) == {
        "error": {
            "code": "authentication_error",
            "message": "Invalid service token",
            "request_id": "test-request-id",
        }
    }
    assert response.headers["x-request-id"] == "test-request-id"
    for name, value in (headers or {}).items():
        if name != "X-Request-ID":
            assert response.headers[name] == value
    assert headers == original


@pytest.mark.parametrize(
    ("status_code", "detail", "expected_code", "expected_message"),
    [
        (401, "Invalid token", "authentication_error", "Invalid token"),
        (403, "Access denied", "forbidden", "Access denied"),
        (404, "Missing class", "not_found", "Missing class"),
        (409, "Already exists", "conflict", "Already exists"),
        (422, "Invalid data", "validation_error", "Invalid data"),
        (400, "Bad request", "http_error", "Bad request"),
        (503, "Database password: secret", "http_error", "Request failed"),
        (400, {"internal": "secret"}, "http_error", "Request failed"),
    ],
)
def test_http_error_has_safe_envelope_and_preserves_headers(
    status_code: int,
    detail: str | dict[str, str],
    expected_code: str,
    expected_message: str,
) -> None:
    """Проверяет коды, безопасное сообщение и заголовки через HTTP-приложение."""
    factory = Mock()
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    app = create_app(settings, factory)

    @app.get("/probe")
    async def probe():
        raise HTTPException(
            status_code=status_code,
            detail=detail,
            headers={"Retry-After": "60", "WWW-Authenticate": "Bearer"},
        )

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/probe")

    response = asyncio.run(request())
    request_id = response.headers["x-request-id"]
    assert UUID(request_id).version == 4
    assert response.status_code == status_code
    assert response.json() == {
        "error": {
            "code": expected_code,
            "message": expected_message,
            "request_id": request_id,
        }
    }
    assert response.headers["retry-after"] == "60"
    assert response.headers["www-authenticate"] == "Bearer"
    factory.assert_not_called()


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_code"),
    [
        ("/missing", 404, "not_found"),
        ("/internal/classes", 401, "authentication_error"),
        ("/starlette-error", 403, "forbidden"),
    ],
)
def test_framework_and_dependency_http_errors_use_same_envelope(
    path: str, expected_status: int, expected_code: str
) -> None:
    """Одинаково обрабатывает ошибки FastAPI, Starlette и отсутствующий URL."""
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    app = create_app(settings, Mock())

    @app.get("/starlette-error")
    async def probe():
        raise StarletteHTTPException(status_code=403, detail="Access denied")

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path)

    response = asyncio.run(request())
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    if expected_status == 401:
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/internal/classes?limit=secret-input", None),
        ("GET", "/internal/classes?offset=-1", None),
        ("POST", "/internal/classes", '{"name":"secret-input"}'),
        (
            "POST",
            "/internal/classes",
            '{"name":"secret-input","study_year":"2026"}',
        ),
        ("POST", "/internal/classes", '{"name":"secret-input"'),
    ],
)
def test_request_validation_error_has_safe_envelope_without_input(
    method: str, path: str, body: str | None
) -> None:
    """Возвращает единый 422 для параметров, тела и повреждённого JSON."""
    factory = Mock()
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    app = create_app(settings, factory)

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(
                method,
                path,
                content=body,
                headers={
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json",
                },
            )

    response = asyncio.run(request())
    request_id = response.headers["x-request-id"]
    assert UUID(request_id).version == 4
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "Invalid request data",
            "request_id": request_id,
        }
    }
    assert "secret-input" not in response.text
    factory.assert_not_called()


@pytest.mark.parametrize(
    ("error_type", "expected_status", "expected_code", "expected_message"),
    [
        (DuplicateClassError, 409, "conflict", "Class already exists"),
        (InvalidClassDataError, 422, "validation_error", "Invalid class data"),
    ],
)
def test_application_error_returns_expected_safe_http_response(
    error_type: type[Exception],
    expected_status: int,
    expected_code: str,
    expected_message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Переводит прикладные ошибки в согласованные ответы без деталей исключения."""
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    app = create_app(settings, Mock())

    @app.get("/probe")
    async def probe():
        raise error_type("private-error-details")

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            return await client.get("/probe")

    response = asyncio.run(request())
    assert response.status_code == expected_status
    request_id = response.headers["x-request-id"]
    assert UUID(request_id).version == 4
    assert response.json() == {
        "error": {
            "code": expected_code,
            "message": expected_message,
            "request_id": request_id,
        }
    }
    assert "private-error-details" not in response.text
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_unexpected_error_returns_safe_json_and_logs_traceback(
    error_type: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    """Связывает безопасный ответ 500 с серверным traceback через request_id."""
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    app = create_app(settings, Mock())

    @app.get("/probe")
    async def probe():
        raise error_type("private-error-details")

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            return await client.get("/probe")

    with caplog.at_level(logging.ERROR, logger="journal_service.app"):
        response = asyncio.run(request())

    assert response.status_code == 500
    request_id = response.headers["x-request-id"]
    assert UUID(request_id).version == 4
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
            "request_id": request_id,
        }
    }
    assert "private-error-details" not in response.text
    records = [
        record for record in caplog.records if record.name == "journal_service.app"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.ERROR
    assert record.request_id == request_id
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], error_type)
    assert record.exc_info[2] is not None
    assert "private-error-details" in caplog.text
