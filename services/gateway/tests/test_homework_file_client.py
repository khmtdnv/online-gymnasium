"""Файловая пересылка ограничена и проверяет результат владельца."""

import asyncio
import json
from io import BytesIO

import httpx
import pytest
from test_homework_api import TEACHER

from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkUnavailableError,
)
from gateway_service.infrastructure.homework_file_client import HomeworkFileClient

SAVED = {
    "id": 8,
    "homework_id": 1,
    "file_name": "Задачи.txt",
    "size_bytes": 6,
    "content_type": "text/plain",
    "upload_status": "ready",
}


def run_upload(transport):
    async def run():
        async with httpx.AsyncClient(
            base_url="http://homework", transport=httpx.MockTransport(transport)
        ) as http:
            return await HomeworkFileClient(http, "gw").upload_file(
                teacher_id=TEACHER,
                homework_id=1,
                file_id=8,
                stream=BytesIO(b"answer"),
                file_name="Задачи.txt",
            )

    return asyncio.run(run())


def test_upload_forwards_multipart_with_only_trusted_identity():
    def transport(request):
        assert request.method == "PUT"
        assert request.url.path == "/internal/homework/1/files/8"
        assert request.headers["Authorization"] == "Bearer gw"
        assert request.headers["X-Teacher-ID"] == str(TEACHER)
        assert request.headers["Content-Type"].startswith(
            "multipart/form-data; boundary="
        )
        assert b' name="file";' in request.content and b"answer" in request.content
        return httpx.Response(200, json=SAVED)

    result = run_upload(transport)
    assert result.model_dump() == SAVED


@pytest.mark.parametrize(
    "payload",
    [
        SAVED | {"id": 9},
        SAVED | {"homework_id": 2},
        SAVED | {"upload_status": "pending"},
        SAVED | {"file_name": "other.txt"},
        SAVED | {"storage_key": "private"},
        SAVED | {"size_bytes": 7},
    ],
)
def test_upload_does_not_accept_a_foreign_or_incomplete_result(payload):
    with pytest.raises(HomeworkUnavailableError):
        run_upload(lambda request: httpx.Response(200, json=payload))


@pytest.mark.parametrize("status", [201, 204, 301, 307, 401, 500, 503])
def test_upload_unexpected_status_is_unavailable_without_redirect_or_retry(status):
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Location": "http://untrusted"},
            json={"error": {"code": "private"}},
        )

    with pytest.raises(HomeworkUnavailableError):
        run_upload(transport)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,code",
    [
        (403, "access_denied"),
        (404, "homework_not_found"),
        (422, "invalid_homework_file"),
    ],
)
def test_upload_preserves_only_known_owner_rejections(status, code):
    with pytest.raises(HomeworkRequestError) as caught:
        run_upload(
            lambda request: httpx.Response(status, json={"error": {"code": code}})
        )
    assert (caught.value.status_code, caught.value.code) == (status, code)


def test_upload_timeout_after_sending_is_unknown_and_not_retried():
    calls = []

    def transport(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret after put")

    with pytest.raises(HomeworkUnavailableError):
        run_upload(transport)
    assert len(calls) == 1


def test_upload_bounds_the_json_response():
    payload = json.dumps(SAVED).encode() + b" " * 10000
    with pytest.raises(HomeworkUnavailableError):
        run_upload(lambda request: httpx.Response(200, content=payload))


def test_cancelled_upload_closes_upstream_response_under_shield():
    import anyio

    closed = []

    async def run():
        with anyio.CancelScope() as scope:

            class Stream(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield b"{"
                    scope.cancel()
                    await anyio.sleep_forever()

                async def aclose(self):
                    await anyio.lowlevel.checkpoint()
                    closed.append(True)

            async with httpx.AsyncClient(
                base_url="http://homework",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, stream=Stream())
                ),
            ) as http:
                await HomeworkFileClient(http, "gw").upload_file(
                    teacher_id=TEACHER,
                    homework_id=1,
                    file_id=8,
                    stream=BytesIO(b"answer"),
                    file_name="Задачи.txt",
                )

    asyncio.run(run())
    assert closed == [True]
