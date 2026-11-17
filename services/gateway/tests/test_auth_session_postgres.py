"""Изолированная проверка миграции и репозитория во временных таблицах PostgreSQL."""

import asyncio
import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from gateway_service.config import GatewaySettings
from gateway_service.infrastructure.auth_session_repository import AuthSessionRepository
from gateway_service.infrastructure.models.user import UserRow  # noqa: F401


@pytest.mark.skipif(
    not os.getenv("GATEWAY_SESSION_LIVE_TEST"), reason="Needs local PostgreSQL"
)
def test_migration_and_session_lifecycle_in_postgres() -> None:
    async def scenario() -> None:
        url = make_url(GatewaySettings().database_url).set(host="127.0.0.1", port=5434)
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.execute(
                        text("CREATE TEMP TABLE users (id UUID PRIMARY KEY)")
                    )
                    await connection.execute(text("SET LOCAL search_path TO pg_temp"))
                    migration_path = (
                        Path(__file__).resolve().parents[1]
                        / "migrations/versions/c18d384bd12f_add_auth_sessions.py"
                    )
                    spec = importlib.util.spec_from_file_location(
                        "session_migration", migration_path
                    )
                    assert spec is not None and spec.loader is not None
                    migration = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(migration)

                    def upgrade(sync_connection):
                        with Operations.context(
                            MigrationContext.configure(sync_connection)
                        ):
                            migration.upgrade()

                    await connection.run_sync(upgrade)
                    user_id, session_id = uuid4(), uuid4()
                    await connection.execute(
                        text("INSERT INTO users (id) VALUES (:id)"), {"id": user_id}
                    )
                    async with AsyncSession(bind=connection) as db:
                        repo = AuthSessionRepository(db)
                        await repo.create(
                            session_id, user_id, datetime.now(UTC) + timedelta(hours=1)
                        )
                        assert await repo.is_active(session_id, user_id)
                        await repo.revoke(session_id, user_id)
                        assert not await repo.is_active(session_id, user_id)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(scenario())
