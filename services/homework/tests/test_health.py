"""Каркас отвечает честно: готовность БД не равна работающему созданию ДЗ."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


def test_live_ready_and_no_published_create_route():
    from homework_service.app import create_app
    from homework_service.config import HomeworkSettings

    engine = AsyncMock()
    probe = AsyncMock()
    app = create_app(
        HomeworkSettings(database_url="test", _env_file=None),
        engine,
        database_probe=probe,
    )
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
        assert client.post("/homework", json={}).status_code == 404
    engine.dispose.assert_awaited_once()


def test_ready_hides_database_details():
    from homework_service.app import create_app
    from homework_service.config import HomeworkSettings

    probe = AsyncMock(
        side_effect=OperationalError("SELECT", {}, RuntimeError("secret-password"))
    )
    with TestClient(
        create_app(
            HomeworkSettings(database_url="test", _env_file=None),
            AsyncMock(),
            database_probe=probe,
        )
    ) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert "secret-password" not in response.text
        assert client.get("/health/live").status_code == 200
