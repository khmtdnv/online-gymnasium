import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_create_keeps_session_and_user_identity() -> None:
    from gateway_service.infrastructure.auth_session_repository import (
        AuthSessionRepository,
    )

    db = Mock()
    session_id, user_id = uuid4(), uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    asyncio.run(AuthSessionRepository(db).create(session_id, user_id, expires_at))
    row = db.add.call_args.args[0]
    assert (row.id, row.user_id, row.expires_at) == (session_id, user_id, expires_at)


def test_active_check_requires_matching_user_unrevoked_and_unexpired() -> None:
    from gateway_service.infrastructure.auth_session_repository import (
        AuthSessionRepository,
    )

    db = Mock()
    db.scalar = AsyncMock(return_value=uuid4())
    assert asyncio.run(AuthSessionRepository(db).is_active(uuid4(), uuid4())) is True
    sql = str(db.scalar.call_args.args[0])
    assert "auth_sessions.id =" in sql
    assert "auth_sessions.user_id =" in sql
    assert "auth_sessions.revoked_at IS NULL" in sql
    assert "auth_sessions.expires_at > now()" in sql
    db.scalar.return_value = None
    assert asyncio.run(AuthSessionRepository(db).is_active(uuid4(), uuid4())) is False


def test_revoke_only_updates_matching_active_session() -> None:
    from gateway_service.infrastructure.auth_session_repository import (
        AuthSessionRepository,
    )

    db = Mock()
    db.execute = AsyncMock()
    asyncio.run(AuthSessionRepository(db).revoke(uuid4(), uuid4()))
    sql = str(db.execute.call_args.args[0])
    assert "UPDATE auth_sessions SET revoked_at=now()" in sql
    assert "auth_sessions.id =" in sql
    assert "auth_sessions.user_id =" in sql
    assert "auth_sessions.revoked_at IS NULL" in sql


def test_session_lifecycle_with_real_database() -> None:
    from gateway_service.infrastructure.auth_session_repository import (
        AuthSessionRepository,
    )
    from gateway_service.infrastructure.models.auth_session import AuthSessionRow
    from gateway_service.infrastructure.models.user import UserRow

    engine = create_engine("sqlite://")
    assert UserRow.__tablename__ == "users"
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id CHAR(32) PRIMARY KEY)"))
        AuthSessionRow.__table__.create(connection)
    user_id, other_user_id, session_id, expired_id = (uuid4() for _ in range(4))
    with Session(engine) as db:
        db.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": user_id.hex})

        class AsyncAdapter:
            def add(self, row):
                db.add(row)

            async def scalar(self, stmt):
                return db.scalar(stmt)

            async def execute(self, stmt):
                return db.execute(stmt)

        repo = AuthSessionRepository(AsyncAdapter())

        async def lifecycle() -> None:
            await repo.create(
                session_id, user_id, datetime.now(UTC) + timedelta(hours=1)
            )
            await repo.create(
                expired_id, user_id, datetime.now(UTC) - timedelta(days=1)
            )
            assert not await repo.is_active(expired_id, user_id)
            assert await repo.is_active(session_id, user_id)
            assert not await repo.is_active(session_id, other_user_id)
            await repo.revoke(session_id, other_user_id)
            assert await repo.is_active(session_id, user_id)
            await repo.revoke(session_id, user_id)
            assert not await repo.is_active(session_id, user_id)
            await repo.revoke(session_id, user_id)

        asyncio.run(lifecycle())
    engine.dispose()
