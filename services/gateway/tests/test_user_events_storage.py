"""Реальная PG: создание/вход и их события фиксируются одной транзакцией."""

import asyncio
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_auth import FakePasswordVerifier, make_fakes
from test_backoffice import FakePasswordService

from gateway_service.application.auth import LoginCommand, LoginHandler
from gateway_service.application.backoffice import CreateUserCommand, CreateUserHandler
from gateway_service.domain.user import Role
from gateway_service.infrastructure.models.auth_session import AuthSessionRow
from gateway_service.infrastructure.models.base import Base
from gateway_service.infrastructure.models.outbox_event import GatewayOutboxEventRow
from gateway_service.infrastructure.models.refresh_token import RefreshTokenRow
from gateway_service.infrastructure.models.user import UserRow
from gateway_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


@pytest.mark.skipif(
    not os.getenv("GATEWAY_TEST_DATABASE_URL"), reason="Needs disposable PostgreSQL"
)
def test_user_events_do_not_commit_when_login_transaction_rolls_back():
    async def run():
        url = os.environ["GATEWAY_TEST_DATABASE_URL"]
        assert (make_url(url).database or "").startswith("gateway_test_")
        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        created_id = None
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = lambda: SqlAlchemyUnitOfWork(sessions)
            user = await CreateUserHandler(factory, FakePasswordService()).handle(
                CreateUserCommand(
                    email=f"{uuid4().hex}@example.test",
                    password="not-for-kafka",
                    role=Role.STUDENT,
                    first_name="Иван",
                    last_name="Петров",
                )
            )
            _, tokens = make_fakes()
            created_id = user.id
            tokens.user_id = user.id

            @asynccontextmanager
            async def failed_commit():
                async with factory() as unit:
                    yield unit
                    raise RuntimeError("commit unavailable")

            command = LoginCommand(email=user.email, password="not-for-kafka")
            with pytest.raises(RuntimeError, match="commit unavailable"):
                await LoginHandler(
                    failed_commit, FakePasswordVerifier(), tokens
                ).handle(command)
            async with sessions() as session:
                condition = GatewayOutboxEventRow.envelope["payload"][
                    "user_id"
                ].astext == str(user.id)
                before = list(
                    await session.scalars(
                        select(GatewayOutboxEventRow).where(condition)
                    )
                )
                assert (
                    len(before) == 1
                    and before[0].envelope["event_type"] == "gateway.user.created"
                )
            await LoginHandler(factory, FakePasswordVerifier(), tokens).handle(command)
            async with sessions() as session:
                events = list(
                    await session.scalars(
                        select(GatewayOutboxEventRow).where(condition)
                    )
                )
                assert len(events) == 2
                assert {row.envelope["event_type"] for row in events} == {
                    "gateway.user.created",
                    "gateway.user.logged_in",
                }
                assert all(
                    set(row.envelope["payload"]) == {"user_id", "role"}
                    for row in events
                )
        finally:
            try:
                if created_id is not None:
                    async with engine.begin() as connection:
                        await connection.execute(
                            delete(GatewayOutboxEventRow).where(
                                GatewayOutboxEventRow.envelope["payload"][
                                    "user_id"
                                ].astext
                                == str(created_id)
                            )
                        )
                        await connection.execute(
                            delete(RefreshTokenRow).where(
                                RefreshTokenRow.user_id == created_id
                            )
                        )
                        await connection.execute(
                            delete(AuthSessionRow).where(
                                AuthSessionRow.user_id == created_id
                            )
                        )
                        await connection.execute(
                            delete(UserRow).where(UserRow.id == created_id)
                        )
            finally:
                await engine.dispose()

    asyncio.run(run())
