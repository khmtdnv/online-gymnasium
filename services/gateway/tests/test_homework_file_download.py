"""Gateway формирует доверенный контекст и не копирует произвольные заголовки."""

from urllib.parse import quote

import httpx
import pytest
from fastapi.testclient import TestClient
from test_homework_api import TEACHER, make_app

from gateway_service.domain.user import Role

PATH = "/api/v1/homework/1/files/8"
DATA = b"x" * 100000
HEADERS = {
    "Content-Type": "application/pdf",
    "Content-Length": str(len(DATA)),
    "Content-Disposition": "attachment; filename*=UTF-8''"
    + quote("Задачи.pdf", safe=""),
    "Set-Cookie": "danger=1",
    "Location": "https://untrusted.example",
}


class Stream(httpx.AsyncByteStream):
    def __init__(self, data=DATA):
        self.data = data
        self.closed = False

    async def __aiter__(self):
        for offset in range(0, len(self.data), 65536):
            yield self.data[offset : offset + 65536]

    async def aclose(self):
        self.closed = True


def prepared(
    *,
    role=Role.TEACHER,
    status=200,
    error=None,
    headers=None,
    stream=None,
    failure=False,
):
    from gateway_service.infrastructure.homework_file_client import HomeworkFileClient

    calls = []
    stream = stream or Stream()

    def respond(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer service-file"
        assert request.headers["X-User-ID"] == str(TEACHER)
        assert request.headers["X-User-Role"] == role.value
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.url.path == "/internal/homework/1/files/8"
        if failure:
            raise httpx.ReadTimeout("secret connection details", request=request)
        if status != 200:
            return httpx.Response(
                status,
                json=error or {},
                headers={"Location": "https://untrusted.example"},
            )
        return httpx.Response(200, headers=headers or HEADERS, stream=stream)

    http = httpx.AsyncClient(
        base_url="http://homework", transport=httpx.MockTransport(respond)
    )
    app, token, _ = make_app(role=role)
    file_client = HomeworkFileClient(http, "service-file")
    app.state.homework_file_client = file_client
    app.state.injected_homework_file_client = file_client
    return app, token, stream, calls


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("role", [Role.STUDENT, Role.TEACHER])
def test_download_stream_and_trusted_identity_ignore_spoofed_headers(method, role):
    app, token, stream, calls = prepared(role=role)
    with TestClient(app) as client:
        response = client.request(
            method,
            PATH,
            headers={
                "Authorization": f"Bearer {token}",
                "X-User-ID": "00000000-0000-0000-0000-000000000099",
                "X-User-Role": "admin",
            },
        )
    assert response.status_code == 200
    assert response.content == (DATA if method == "GET" else b"")
    assert response.headers["content-length"] == str(len(DATA))
    assert response.headers["content-disposition"] == HEADERS["Content-Disposition"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "set-cookie" not in response.headers and "location" not in response.headers
    assert len(calls) == 1 and stream.closed


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (409, "homework_file_not_ready", 409),
        (404, "homework_not_found", 404),
        (403, "access_denied", 403),
        (401, "invalid_service_credentials", 503),
        (302, "redirect", 503),
        (500, "secret", 503),
        (404, "other_error", 503),
    ],
)
def test_only_known_owner_errors_are_forwarded(status, code, expected):
    app, token, _, calls = prepared(
        status=status, error={"error": {"code": code, "message": "secret"}}
    )
    with TestClient(app) as client:
        response = client.get(PATH, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == expected
    if status == 409:
        assert response.json()["error"]["code"] == "homework_file_not_ready"
    assert "secret" not in response.text and len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"Content-Length": "0"},
        {"Content-Length": "10485761"},
        {"Content-Type": "text/html"},
        {"Content-Encoding": "gzip"},
        {"Content-Disposition": "attachment; filename*=UTF-8''..%2Ftask.pdf"},
    ],
)
def test_untrusted_download_headers_close_upstream_and_return_503(changes):
    app, token, stream, _ = prepared(headers=HEADERS | changes)
    with TestClient(app) as client:
        response = client.get(PATH, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503 and stream.closed


def test_parent_is_forbidden_and_missing_jwt_is_unauthorized_without_owner_call():
    app, token, _, calls = prepared(role=Role.PARENT)
    with TestClient(app) as client:
        assert (
            client.get(PATH, headers={"Authorization": f"Bearer {token}"}).status_code
            == 403
        )
        assert client.get(PATH).status_code == 401
    assert calls == []


def test_owner_timeout_before_headers_is_safe_503_without_retry():
    app, token, _, calls = prepared(failure=True)
    with TestClient(app) as client:
        response = client.get(PATH, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503 and "secret" not in response.text
    assert len(calls) == 1


def test_oversized_owner_error_body_is_not_forwarded_as_a_business_error():
    app, token, _, _ = prepared(
        status=404,
        error={"error": {"code": "homework_not_found", "message": "x" * 9000}},
    )
    with TestClient(app) as client:
        response = client.get(PATH, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503


def test_late_upstream_failure_is_not_converted_to_a_second_http_response():
    import asyncio

    from gateway_service.api.homework_files import FileDownloadResponse
    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.application.homework import HomeworkUnavailableError

    app, _, stream, _ = prepared(stream=Stream(DATA[:65536]))
    messages = []

    async def run():
        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        user = GetCurrentUserResult(
            id=TEACHER, email="teacher@example.com", role=Role.TEACHER
        )
        with pytest.raises(HomeworkUnavailableError):
            await FileDownloadResponse(app.state.homework_file_client, user, 1, 8)(
                {"type": "http", "method": "GET", "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )

    asyncio.run(run())
    assert [
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    ] == [200]
    assert stream.closed


def test_public_openapi_has_no_duplicate_download_operation_ids():
    import warnings

    app, _, _, _ = prepared()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app.openapi()
    assert not [
        item for item in caught if "Duplicate Operation ID" in str(item.message)
    ]


@pytest.mark.parametrize("spec", ["2.0", "2.4"])
def test_gateway_disconnect_closes_the_owner_response(spec):
    import asyncio

    import anyio
    from starlette.requests import ClientDisconnect

    from gateway_service.api.homework_files import FileDownloadResponse
    from gateway_service.application.auth import GetCurrentUserResult

    app, _, stream, _ = prepared()

    async def run():
        disconnected = anyio.Event()

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                if spec == "2.4":
                    raise OSError("closed")
                disconnected.set()
                await anyio.sleep_forever()

        user = GetCurrentUserResult(
            id=TEACHER, email="teacher@example.com", role=Role.TEACHER
        )
        try:
            await FileDownloadResponse(app.state.homework_file_client, user, 1, 8)(
                {"type": "http", "method": "GET", "asgi": {"spec_version": spec}},
                receive,
                send,
            )
        except ClientDisconnect:
            assert spec == "2.4"

    asyncio.run(run())
    assert stream.closed
