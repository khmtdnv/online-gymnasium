"""Общая подготовка интеграций только в явно выбранной тестовой PostgreSQL-БД."""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from journal_service.infrastructure.database import create_session_factory
from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


def require_test_url(value: str) -> None:
    """Запрещает разрушительную очистку рабочей базы по ошибочно переданному URL.

    Args:
        value: Адрес отдельной тестовой базы.

    Raises:
        ValueError: Драйвер или имя базы не соответствуют тестовому контракту.
    """
    url = make_url(value)
    if url.drivername != "postgresql+asyncpg" or not (url.database or "").startswith(
        "journal_test_"
    ):
        raise ValueError("Разрешена только отдельная PostgreSQL-БД journal_test_*")


@pytest.fixture(scope="session")
def database_url() -> str:
    """Применяет готовые миграции в указанной существующей тестовой БД.

    Returns:
        URL проверенной тестовой базы; без переменной тесты пропускаются.
    """
    value = os.environ.get("JOURNAL_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Нужен JOURNAL_TEST_DATABASE_URL отдельной тестовой PostgreSQL-БД")
    require_test_url(value)
    service_dir = Path(__file__).resolve().parents[2]
    config = Config(str(service_dir / "alembic.ini"))
    config.set_main_option("script_location", str(service_dir / "migrations"))
    with patch.dict(os.environ, {"DATABASE_URL": value}):
        command.upgrade(config, "head")
    return value


@asynccontextmanager
async def database(
    url: str,
) -> AsyncIterator[tuple[AsyncEngine, Callable[[], SqlAlchemyUnitOfWork]]]:
    """Очищает дочерние периоды перед классами и закрывает тестовый engine.

    Args:
        url: Проверенный URL отдельной тестовой базы.

    Yields:
        Engine и фабрику UoW, используемые внутри одного asyncio.run.

    Raises:
        ValueError: URL указывает не на разрешённую тестовую базу.
    """
    require_test_url(url)
    engine = create_async_engine(url, poolclass=NullPool)
    sessions = create_session_factory(engine)
    try:
        async with engine.begin() as connection:
            grades = await connection.scalar(
                text("SELECT to_regclass('public.lesson_grades')")
            )
            if grades is not None:
                await connection.execute(text("DELETE FROM lesson_grades"))
            attendance = await connection.scalar(
                text("SELECT to_regclass('public.lesson_attendance')")
            )
            if attendance is not None:
                await connection.execute(text("DELETE FROM lesson_attendance"))
            if (
                await connection.scalar(
                    text("SELECT to_regclass('public.teacher_classes')")
                )
                is not None
            ):
                await connection.execute(text("DELETE FROM teacher_classes"))
            outbox = await connection.scalar(
                text("SELECT to_regclass('public.journal_event_outbox')")
            )
            if outbox is not None:
                await connection.execute(text("DELETE FROM journal_event_outbox"))
            # До новой миграции таблицы нет: старые тесты классов ещё должны работать.
            exists = await connection.scalar(
                text("SELECT to_regclass('public.student_class_periods')")
            )
            if exists is not None:
                await connection.execute(text("DELETE FROM student_class_periods"))
            await connection.execute(text("DELETE FROM classes"))
        yield engine, lambda: SqlAlchemyUnitOfWork(sessions)
    finally:
        await engine.dispose()
