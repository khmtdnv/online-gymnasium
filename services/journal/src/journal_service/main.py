"""Собирает зависимости Journal для запуска HTTP-процесса Uvicorn."""

from journal_service.app import create_app
from journal_service.config import JournalSettings
from journal_service.infrastructure.database import (
    check_database,
    create_engine,
    create_session_factory,
)
from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

settings = JournalSettings()
engine = create_engine(settings.database_url)
session_factory = create_session_factory(engine)


async def check_readiness() -> None:
    """Проверяет подключение текущего процесса к PostgreSQL запросом SELECT 1.

    Raises:
        SQLAlchemyError: База недоступна или запрос не выполнен.
    """
    await check_database(engine)


app = create_app(
    settings=settings,
    uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
    readiness_check=check_readiness,
    close_resources=engine.dispose,
)
