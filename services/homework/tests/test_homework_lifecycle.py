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
