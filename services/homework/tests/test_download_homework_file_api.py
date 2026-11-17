"""GET/HEAD не открывают объект до допуска и закрывают поток при любом исходе."""

import asyncio
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from homework_service.app import create_app
from homework_service.application.ports.errors import (
    HomeworkFileNotReadyError,
    HomeworkNotFoundError,
)
from homework_service.config import HomeworkSettings
from homework_service.domain.homework_file import HomeworkFile
from tests.test_homework_files import file_input


class Storage:
    def __init__(self, *, missing=False, data=b"x" * 100000):
        self.missing = missing
        self.data = data
        self.streams = []

    @contextmanager
    def open(self, key):
        assert key == "homework/private"
        if self.missing:
            raise OSError("secret storage details")
        stream = BytesIO(self.data)
        self.streams.append(stream)
        try:
            yield stream
        finally:
            stream.close()

    def close(self):
        pass


def metadata():
    return HomeworkFile(
        id=8,
        homework_id=1,
        **file_input(file_name='Задачи "1".pdf', size_bytes=100000),
        upload_status="ready",
        storage_key="homework/private",
    )


def app(monkeypatch, storage, *, error=None):
    import homework_service.app as module

    monkeypatch.setattr(module, "create_file_storage", lambda settings: storage)
    handler = SimpleNamespace(
        handle=AsyncMock(return_value=metadata(), side_effect=error)
    )
    return create_app(
        HomeworkSettings(
            database_url="unused", gateway_service_token="gw", _env_file=None
        ),
        AsyncMock(),
        get_homework_file_handler=handler,
    ), handler


HEADERS = {
    "Authorization": "Bearer gw",
    "X-User-ID": "00000000-0000-0000-0000-000000000001",
    "X-User-Role": "student",
}
PATH = "/internal/homework/1/files/8"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_download_headers_bytes_and_storage_lifetime(monkeypatch, method):
    storage = Storage()
    application, handler = app(monkeypatch, storage)
    with TestClient(application) as client:
        response = client.request(method, PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.content == (storage.data if method == "GET" else b"")
    assert response.headers["content-length"] == "100000"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers[
        "content-disposition"
    ] == "attachment; filename*=UTF-8''" + quote('Задачи "1".pdf', safe="")
    assert storage.streams and all(stream.closed for stream in storage.streams)
    query = handler.handle.await_args.args[0]
    assert query.role == "student" and query.homework_id == 1 and query.file_id == 8


@pytest.mark.parametrize(
    "error,status,code",
    [
        (HomeworkNotFoundError(), 404, "homework_not_found"),
        (HomeworkFileNotReadyError(), 409, "homework_file_not_ready"),
    ],
)
def test_errors_do_not_open_storage(monkeypatch, error, status, code):
    storage = Storage()
    application, _ = app(monkeypatch, storage, error=error)
    with TestClient(application) as client:
        response = client.get(PATH, headers=HEADERS)
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert storage.streams == []


def test_missing_object_returns_safe_503_before_headers(monkeypatch):
    application, _ = app(monkeypatch, Storage(missing=True))
    with TestClient(application) as client:
        response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 503
    assert "secret" not in response.text


def test_eager_storage_open_failure_also_returns_safe_503(monkeypatch):
    storage = Storage()

    def fail(key):
        raise OSError("secret storage details")

    storage.open = fail
    application, _ = app(monkeypatch, storage)
    with TestClient(application) as client:
        response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 503 and "secret" not in response.text


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 401),
        (HEADERS | {"Authorization": "Bearer wrong"}, 401),
        (HEADERS | {"X-User-Role": "admin"}, 422),
    ],
)
def test_internal_credentials_and_role_are_required(monkeypatch, headers, status):
    storage = Storage()
    application, handler = app(monkeypatch, storage)
    with TestClient(application) as client:
        response = client.get(PATH, headers=headers)
    assert response.status_code == status
    handler.handle.assert_not_awaited()
    assert storage.streams == []


@pytest.mark.parametrize("spec", ["2.0", "2.4"])
def test_asgi_disconnect_closes_object_even_when_background_tasks_cannot_run(spec):
    import anyio
    from anyio import CapacityLimiter
    from starlette.requests import ClientDisconnect

    from homework_service.api.file_download import FileDownloadResponse

    storage = Storage()

    async def run():
        disconnected = anyio.Event()

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                if spec == "2.4":
                    raise OSError("connection closed")
                disconnected.set()
                await anyio.sleep_forever()

        response = FileDownloadResponse(metadata(), storage, CapacityLimiter(4))
        try:
            await response(
                {"type": "http", "method": "GET", "asgi": {"spec_version": spec}},
                receive,
                send,
            )
        except ClientDisconnect:
            assert spec == "2.4"

    asyncio.run(run())
    assert storage.streams and all(stream.closed for stream in storage.streams)


def test_head_disconnect_is_not_rewritten_into_a_second_http_error():
    from anyio import CapacityLimiter

    from homework_service.api.file_download import FileDownloadResponse

    storage = Storage()

    async def run():
        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("connection closed")

        with pytest.raises(OSError, match="connection closed"):
            await FileDownloadResponse(metadata(), storage, CapacityLimiter(4))(
                {"type": "http", "method": "HEAD"}, receive, send
            )

    asyncio.run(run())
    assert storage.streams and storage.streams[0].closed
