"""Запускает миграции собственной БД из настроек Homework."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from homework_service.config import HomeworkSettings
from homework_service.infrastructure.models.base import Base
from homework_service.infrastructure.models.homework import HomeworkRow  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
url = HomeworkSettings().database_url


def run_migrations(connection) -> None:
    """Применяет ревизии внутри транзакции соединения.

    Args:
        connection: Соединение SQLAlchemy либо None для offline SQL.
    """
    context.configure(
        connection=connection,
        url=url,
        target_metadata=Base.metadata,
        literal_binds=connection is None,
    )
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    """Открывает отдельное соединение и гарантированно освобождает engine."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations(None)
else:
    asyncio.run(online())
