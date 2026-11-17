"""Применяет готовые миграции отдельной БД Billing."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from billing_service.config import BillingSettings
from billing_service.models import Base

config = context.config
fileConfig(config.config_file_name, disable_existing_loggers=False)
url = BillingSettings().database_url


def run(connection=None):
    """Выполняет ревизии внутри транзакции текущего соединения."""
    context.configure(
        connection=connection,
        url=url,
        target_metadata=Base.metadata,
        literal_binds=connection is None,
    )
    with context.begin_transaction():
        context.run_migrations()


async def online():
    """Не оставляет открытым пул одноразового процесса миграций."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run()
else:
    asyncio.run(online())
