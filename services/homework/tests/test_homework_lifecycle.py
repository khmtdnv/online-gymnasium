"""HTTP-ресурсы закрываются и при штатном выходе, и при сбое сборки."""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from homework_service.app import create_app
from homework_service.config import HomeworkSettings


@pytest.mark.parametrize("fail_second", [False, True])
def test_owner_clients_are_closed_after_lifespan(monkeypatch, fail_second):
    real_client = httpx.AsyncClient
    clients = []

    def factory(**kwargs):
        if fail_second and clients:
            raise ValueError("bad owner configuration")
        client = real_client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    engine = AsyncMock()
    app = create_app(
        HomeworkSettings(
            database_url="test",
            gateway_service_token="gateway-test",
            schedule_base_url="http://schedule",
            schedule_service_token="s",
            journal_base_url="http://journal",
            journal_service_token="j",
            _env_file=None,
        ),
        engine,
    )
    if fail_second:
        with pytest.raises(ValueError, match="bad owner"), TestClient(app):
            pass
    else:
        with TestClient(app) as client:
            assert client.get("/health/live").status_code == 200
            assert app.state.create_homework_handler is not None
            assert app.state.get_teacher_lesson_handler is not None
            assert all(not item.is_closed for item in clients)
    assert clients and all(item.is_closed for item in clients)
    engine.dispose.assert_awaited_once()
    assert app.state.create_homework_handler is None
    assert app.state.get_teacher_lesson_handler is None


@pytest.mark.parametrize("owner_start_fails", [False, True])
def test_storage_pool_closed_even_when_later_owner_startup_fails(
    monkeypatch, owner_start_fails
):
    from unittest.mock import Mock

    import homework_service.app as app_module

    storage = Mock()
    monkeypatch.setattr(app_module, "create_file_storage", Mock(return_value=storage))
    if owner_start_fails:
        monkeypatch.setattr(
            httpx, "AsyncClient", Mock(side_effect=ValueError("bad owner config"))
        )
    app = create_app(
        HomeworkSettings(
            database_url="test",
            gateway_service_token="g",
            schedule_base_url="http://schedule",
            schedule_service_token="s",
            journal_base_url="http://journal",
            journal_service_token="j",
            _env_file=None,
        ),
        AsyncMock(),
    )
    if owner_start_fails:
        with pytest.raises(ValueError), TestClient(app):
            pass
    else:
        with TestClient(app) as client:
            assert client.get("/health/live").status_code == 200
            assert app.state.file_storage is storage
    storage.close.assert_called_once_with()
    assert app.state.file_storage is None


def test_upload_handler_is_prepared_only_when_storage_and_owners_are_configured(
    monkeypatch,
):
    from unittest.mock import Mock

    import homework_service.app as module
    from homework_service.application.homework_files import UploadHomeworkFileHandler

    storage = Mock()
    monkeypatch.setattr(module, "create_file_storage", Mock(return_value=storage))
    app = create_app(
        HomeworkSettings(
            database_url="test",
            gateway_service_token="g",
            schedule_base_url="http://schedule",
            schedule_service_token="s",
            journal_base_url="http://journal",
            journal_service_token="j",
            _env_file=None,
        ),
        AsyncMock(),
    )
    with TestClient(app):
        assert isinstance(
            app.state.upload_homework_file_handler, UploadHomeworkFileHandler
        )
    assert app.state.upload_homework_file_handler is None


def test_missing_storage_keeps_upload_handler_disabled_but_json_handler_ready():
    app = create_app(
        HomeworkSettings(
            database_url="test",
            gateway_service_token="g",
            schedule_base_url="http://schedule",
            schedule_service_token="s",
            journal_base_url="http://journal",
            journal_service_token="j",
            _env_file=None,
        ),
        AsyncMock(),
    )
    with TestClient(app) as client:
        assert app.state.upload_homework_file_handler is None
        assert app.state.create_homework_handler is not None
        assert client.get("/health/live").status_code == 200
