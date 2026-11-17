"""Настройка Schedule не должна ломать старые маршруты Gateway."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway_service.app import create_app
from gateway_service.config import GatewaySettings


@pytest.mark.parametrize("complete", [False, True])
def test_schedule_client_is_created_and_closed_only_when_configured(
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
            _env_file=None,
            database_url="unused",
            jwt_secret="x" * 32,
            backoffice_service_token="test",
            schedule_base_url="http://schedule",
            schedule_service_token="schedule-only" if complete else None,
        ),
        engine,
        Mock(),
        Mock(),
        Mock(),
    )
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert (app.state.schedule_client is not None) == complete
        assert all(not client.is_closed for client in clients)
    assert len(clients) == int(complete)
    assert all(client.is_closed for client in clients)
    assert app.state.schedule_client is None
    engine.dispose.assert_awaited_once()


def test_failed_schedule_setup_closes_previously_created_homework_client(monkeypatch):
    original = httpx.AsyncClient
    clients = []

    def factory(**kwargs):
        if clients:
            raise ValueError("setup failed")
        client = original(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    engine = AsyncMock()
    app = create_app(
        GatewaySettings(
            _env_file=None,
            database_url="unused",
            jwt_secret="x" * 32,
            backoffice_service_token="test",
            homework_base_url="http://homework",
            homework_service_token="h",
            schedule_base_url="http://schedule",
            schedule_service_token="s",
        ),
        engine,
        Mock(),
        Mock(),
        Mock(),
    )
    with pytest.raises(ValueError, match="setup failed"), TestClient(app):
        pass
    assert clients and clients[0].is_closed
    assert app.state.schedule_client is None and app.state.homework_client is None
    engine.dispose.assert_awaited_once()
