"""Подключает миграции Journal к настройкам сервиса и metadata моделей."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from journal_service.config import JournalSettings
from journal_service.infrastructure.models.base import Base
from journal_service.infrastructure.models.outbox_event import (
    JournalOutboxEventRow,  # noqa: F401
)
from journal_service.infrastructure.models.school_class import (
    ClassRow,  # noqa: F401
)
from journal_service.infrastructure.models.student_class_period import (
    StudentClassPeriodRow,  # noqa: F401
)
from journal_service.infrastructure.models.teacher_class import (
    TeacherClassRow,  # noqa: F401
)

config = context.config
settings = JournalSettings()
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.replace("%", "%%"),
)
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Генерирует SQL миграций без подключения к базе данных."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Выполняет миграции через синхронный интерфейс соединения.

    Args:
        connection: Соединение, переданное асинхронным run_sync.
    """
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Подключается к БД асинхронно и запускает миграции через run_sync."""

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Запускает асинхронную работу с БД из обычной команды Alembic."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
