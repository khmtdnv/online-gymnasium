"""Параллельный refresh и logout на отдельной тестовой PostgreSQL."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_auth import FakePasswordVerifier
from test_token_service import make_service

from gateway_service.application.auth import (
    GetCurrentUserCommand,
    GetCurrentUserHandler,
    LoginCommand,
    LoginHandler,
    LogoutCommand,
    LogoutHandler,
    RefreshCommand,
    RefreshHandler,
)
from gateway_service.application.errors import AuthenticationError
from gateway_service.infrastructure.models.base import Base
from gateway_service.infrastructure.models.user import UserRow
from gateway_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


@pytest.mark.skipif(
    not os.getenv("GATEWAY_TEST_DATABASE_URL"), reason="Needs disposable PostgreSQL"
)
def test_logout_and_refresh_cannot_leave_active_session():
    async def run():
        url = os.environ["GATEWAY_TEST_DATABASE_URL"]
        assert (make_url(url).database or "").startswith("gateway_test_")
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            factory = lambda: SqlAlchemyUnitOfWork(sessions)
            user_id = uuid4()
            email = f"{user_id}@example.test"
            async with sessions.begin() as db:
                db.add(
                    UserRow(
                        id=user_id,
                        email=email,
                        first_name="Иван",
                        last_name="Тестов",
                        role="admin",
                        password_hash="hash",
                        is_active=True,
                    )
                )
            tokens = make_service()
            login = await LoginHandler(factory, FakePasswordVerifier(), tokens).handle(
                LoginCommand(email=email, password="password")
            )
            old = tokens.decode_refresh(login.refresh_token)
            async with factory() as uow:
                assert await uow.users.consume_refresh_token(old.jti, user_id)
                pending = asyncio.create_task(
                    RefreshHandler(factory, tokens).handle(
                        RefreshCommand(refresh_token=login.refresh_token)
                    )
                )
                await asyncio.sleep(0.1)
                assert not pending.done()
                await uow.auth_sessions.revoke(old.session_id, user_id)
            with pytest.raises(AuthenticationError):
                await asyncio.wait_for(pending, timeout=5)
            with pytest.raises(AuthenticationError):
                await GetCurrentUserHandler(factory, tokens).handle(
                    GetCurrentUserCommand(access_token=login.access_token)
                )

            second = await LoginHandler(factory, FakePasswordVerifier(), tokens).handle(
                LoginCommand(email=email, password="password")
            )
            refreshed = await RefreshHandler(factory, tokens).handle(
                RefreshCommand(refresh_token=second.refresh_token)
            )
            await LogoutHandler(factory, tokens).handle(
                LogoutCommand(refresh_token=second.refresh_token)
            )
            with pytest.raises(AuthenticationError):
                await GetCurrentUserHandler(factory, tokens).handle(
                    GetCurrentUserCommand(access_token=refreshed.access_token)
                )
        finally:
            await engine.dispose()

    asyncio.run(run())
