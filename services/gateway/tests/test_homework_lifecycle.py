"""Жизненный цикл исходящего Homework-клиента не зависит от запросов."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway_service.app import create_app
from gateway_service.config import GatewaySettings


@pytest.mark.parametrize("complete", [False, True])
def test_client_is_created_only_for_complete_configuration_and_closed(
    monkeypatch, complete
):
    original = httpx.AsyncClient
    clients = []

    def factory(**kwargs):
        client = original(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    engine = AsyncMock()
    app = create_app(
        GatewaySettings(
            database_url="test",
            jwt_secret="x" * 32,
            backoffice_service_token="test",
            homework_base_url="http://homework",
            homework_service_token="test" if complete else None,
            _env_file=None,
        ),
        engine,
        Mock(),
        Mock(),
        Mock(),
    )
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert (app.state.homework_client is not None) == complete
        assert all(not item.is_closed for item in clients)
    assert len(clients) == int(complete)
    assert all(item.is_closed for item in clients)
    engine.dispose.assert_awaited_once()
    assert app.state.homework_client is None


def test_failed_client_setup_still_disposes_engine(monkeypatch):
    def fail(**kwargs):
        raise ValueError("bad setup")

    monkeypatch.setattr(httpx, "AsyncClient", fail)
    engine = AsyncMock()
    app = create_app(
        GatewaySettings(
            database_url="test",
            jwt_secret="x" * 32,
            backoffice_service_token="test",
            homework_base_url="http://homework",
            homework_service_token="test",
            _env_file=None,
        ),
        engine,
        Mock(),
        Mock(),
        Mock(),
    )
    with pytest.raises(ValueError, match="bad setup"), TestClient(app):
        pass
    engine.dispose.assert_awaited_once()
