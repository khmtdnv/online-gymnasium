"""Проверяет соединение HTTP-приложения с реальными фабриками инфраструктуры."""

import asyncio
import importlib
import sys
from unittest.mock import AsyncMock, Mock, patch

import httpx

from journal_service.config import JournalSettings
from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


def test_main_wires_database_readiness_and_shutdown() -> None:
    """Передаёт один engine проверке БД, фабрике сессий и очистке ресурсов."""
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    engine = Mock()
    engine.dispose = AsyncMock()
    session_factory = Mock()
    check = AsyncMock()
    sys.modules.pop("journal_service.main", None)
    try:
        with (
            patch("journal_service.config.JournalSettings", return_value=settings),
            patch(
                "journal_service.infrastructure.database.create_engine",
                return_value=engine,
            ) as create_engine,
            patch(
                "journal_service.infrastructure.database.create_session_factory",
                return_value=session_factory,
            ) as create_sessions,
            patch("journal_service.infrastructure.database.check_database", check),
        ):
            main = importlib.import_module("journal_service.main")
            create_engine.assert_called_once_with(settings.database_url)
            create_sessions.assert_called_once_with(engine)
            assert isinstance(main.app.state.uow_factory(), SqlAlchemyUnitOfWork)
            session_factory.assert_not_called()

            async def run():
                async with (
                    main.app.router.lifespan_context(main.app),
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=main.app),
                        base_url="http://test",
                    ) as client,
                ):
                    response = await client.get("/health/ready")
                    assert response.status_code == 200
                    engine.dispose.assert_not_awaited()

            asyncio.run(run())
            check.assert_awaited_once_with(engine)
            engine.dispose.assert_awaited_once()
    finally:
        sys.modules.pop("journal_service.main", None)
