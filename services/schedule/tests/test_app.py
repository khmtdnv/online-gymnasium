import pytest
from conftest import NoopScheduleCache
from fastapi.testclient import TestClient

from schedule_service.app import create_app
from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.config import Settings
from schedule_service.infrastructure.database import create_engine


@pytest.mark.anyio
async def test_create_app_uses_title_from_settings(
    unused_uow_factory: UnitOfWorkFactory,
) -> None:
    test_app_name = "Test Schedule Service"
    test_settings = Settings(
        app_name=test_app_name,
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    test_engine = create_engine(url=test_settings.database_url)

    try:
        test_app = create_app(
            test_settings,
            test_engine,
            unused_uow_factory,
            NoopScheduleCache(),
        )
        assert test_app.title == test_app_name
        assert test_app.state.engine is test_engine
    finally:
        await test_engine.dispose()


def _school_periods_app(
    gateway_service_token: str | None, uow_factory: UnitOfWorkFactory
):
    """Собирает продакшн-приложение с заданным служебным доступом Gateway."""
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
        gateway_service_token=gateway_service_token,
        homework_service_token="homework-only",
    )
    engine = create_engine(url=settings.database_url)
    return create_app(settings, engine, uow_factory, NoopScheduleCache())


def test_school_periods_endpoint_returns_contract_to_gateway(
    unused_uow_factory: UnitOfWorkFactory,
) -> None:
    app = _school_periods_app("gateway-only", unused_uow_factory)

    with TestClient(app) as client:
        response = client.get(
            "/internal/school-periods",
            headers={"Authorization": "Bearer gateway-only"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "timezone": "Asia/Yekaterinburg",
        "effective_from": "2026-11-30",
        "periods": [
            {"number": 1, "start_at": "09:00", "end_at": "09:45"},
            {"number": 2, "start_at": "09:55", "end_at": "10:40"},
            {"number": 3, "start_at": "11:00", "end_at": "11:45"},
            {"number": 4, "start_at": "11:55", "end_at": "12:40"},
            {"number": 5, "start_at": "13:00", "end_at": "13:45"},
            {"number": 6, "start_at": "13:55", "end_at": "14:40"},
            {"number": 7, "start_at": "15:00", "end_at": "15:45"},
        ],
    }
    assert "/internal/school-periods" not in app.openapi()["paths"]


@pytest.mark.parametrize("token", [None, "bad", "homework-only"])
def test_school_periods_rejects_wrong_service_credentials(
    token, unused_uow_factory: UnitOfWorkFactory
) -> None:
    app = _school_periods_app("gateway-only", unused_uow_factory)
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/internal/school-periods", headers=headers)

    assert response.status_code == 401


@pytest.mark.parametrize("configured", [None, "homework-only"])
def test_school_periods_fail_closed_without_separate_service_token(
    configured, unused_uow_factory: UnitOfWorkFactory
) -> None:
    """Отдельный доступ Gateway не настроен или делит секрет — 503."""
    app = _school_periods_app(configured, unused_uow_factory)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/internal/school-periods",
            headers={"Authorization": "Bearer whatever"},
        )

    assert response.status_code == 503
