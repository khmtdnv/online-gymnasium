"""Границы multipart проверяются до обработки содержимого и закрывают spool-файлы."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def upload_app(seen):
    from homework_service.api.file_upload import read_upload

    app = FastAPI()

    @app.put("/upload")
    async def upload(request: Request):
        async with read_upload(request) as file:
            seen.append(file.file)
            return {"size": file.size, "on_disk": file.file._rolled}

    return app


def test_large_upload_is_spooled_to_disk_and_closed_after_response():
    seen = []
    with TestClient(upload_app(seen)) as client:
        response = client.put("/upload", files={"file": ("x.txt", b"x" * 10485760)})
    assert response.status_code == 200
    assert response.json() == {"size": 10485760, "on_disk": True}
    assert seen[0].closed


@pytest.mark.parametrize(
    "files,data,status",
    [
        ([("file", ("x.txt", b"x")), ("file", ("y.txt", b"y"))], None, 422),
        ({"unexpected": ("x.txt", b"x")}, None, 422),
        ({"file": ("x.txt", b"")}, None, 422),
        ({"file": ("x.txt", b"x" * 10485761)}, None, 413),
        ({"file": ("x.txt", b"x")}, {"extra": "field"}, 422),
    ],
)
def test_invalid_multipart_closes_all_opened_files(monkeypatch, files, data, status):
    import starlette.formparsers as parsers

    created = []
    real_spool = parsers.SpooledTemporaryFile

    def spool(*args, **kwargs):
        value = real_spool(*args, **kwargs)
        created.append(value)
        return value

    monkeypatch.setattr(parsers, "SpooledTemporaryFile", spool)
    with TestClient(upload_app([])) as client:
        response = client.put("/upload", files=files, data=data)
    assert response.status_code == status
    assert all(file.closed for file in created)


def test_json_cannot_be_treated_as_file_upload():
    with TestClient(upload_app([])) as client:
        assert client.put("/upload", json={"file": "fake"}).status_code == 415


def test_total_body_limit_applies_without_content_length():
    def chunks():
        yield b"x" * (11 * 1024 * 1024 + 1)

    with TestClient(upload_app([])) as client:
        response = client.put(
            "/upload",
            content=chunks(),
            headers={"Content-Type": "multipart/form-data; boundary=example"},
        )
    assert response.status_code == 413


def test_truncated_multipart_is_rejected_and_partial_spool_is_closed(monkeypatch):
    import starlette.formparsers as parsers

    created = []
    real_spool = parsers.SpooledTemporaryFile

    def spool(*args, **kwargs):
        file = real_spool(*args, **kwargs)
        created.append(file)
        return file

    monkeypatch.setattr(parsers, "SpooledTemporaryFile", spool)
    body = (
        b'--example\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n'
        b"Content-Type: text/plain\r\n\r\npartial file with no closing boundary"
    )
    with TestClient(upload_app([])) as client:
        response = client.put(
            "/upload",
            content=body,
            headers={"Content-Type": "multipart/form-data; boundary=example"},
        )
    assert response.status_code == 422
    assert created and all(file.closed for file in created)


def test_consumer_timeout_is_not_reported_as_body_read_timeout():
    """Ошибка хранилища после разбора тела не превращается в HTTP 408."""
    from homework_service.api.file_upload import read_upload

    app = FastAPI()
    seen = []

    @app.put("/upload")
    async def upload(request: Request):
        async with read_upload(request) as file:
            seen.append(file.file)
            raise TimeoutError("storage timed out")

    with (
        TestClient(app) as client,
        pytest.raises(TimeoutError, match="storage timed out"),
    ):
        client.put("/upload", files={"file": ("x.txt", b"x")})
    assert seen and seen[0].closed
