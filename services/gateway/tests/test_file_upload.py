"""Parser не оставляет временные файлы при повреждённом теле или отмене."""

import asyncio

import anyio
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gateway_service.api.file_upload import read_upload


def app(seen):
    application = FastAPI()

    @application.put("/upload")
    async def upload(request: Request):
        async with read_upload(request) as file:
            seen.append(file.file)
            return {"size": file.size, "on_disk": file.file._rolled}

    return application


def test_gateway_spools_ten_mebibytes_and_closes_after_response():
    seen = []
    with TestClient(app(seen)) as client:
        response = client.put("/upload", files={"file": ("x.txt", b"x" * 10485760)})
    assert response.status_code == 200
    assert response.json() == {"size": 10485760, "on_disk": True}
    assert seen[0].closed


@pytest.mark.parametrize(
    "body",
    [
        b'--example\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n\r\npartial',
        b'--wrong\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n\r\nx\r\n--wrong--\r\n',
    ],
)
def test_invalid_boundary_is_422_and_closes_partial_spool(monkeypatch, body):
    import starlette.formparsers as parsers

    created = []
    spool = parsers.SpooledTemporaryFile

    def make_spool(*args, **kwargs):
        file = spool(*args, **kwargs)
        created.append(file)
        return file

    monkeypatch.setattr(parsers, "SpooledTemporaryFile", make_spool)
    with TestClient(app([])) as client:
        response = client.put(
            "/upload",
            content=body,
            headers={"Content-Type": "multipart/form-data; boundary=example"},
        )
    assert response.status_code == 422
    assert all(file.closed for file in created)


def test_cancelling_consumer_still_closes_spool():
    body = b'--example\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n\r\nx\r\n--example--\r\n'
    seen = []

    async def run():
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(
            {
                "type": "http",
                "headers": [
                    (b"content-type", b"multipart/form-data; boundary=example")
                ],
            },
            receive,
        )
        with anyio.CancelScope() as scope:
            async with read_upload(request) as file:
                seen.append(file.file)
                scope.cancel()
                await anyio.sleep_forever()

    asyncio.run(run())
    assert seen[0].closed
