import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_auth import FakePasswordVerifier, make_fakes
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


def test_login_creates_one_session_and_binds_both_tokens() -> None:
    uow, _ = make_fakes()
    uow.auth_sessions = AsyncMock()
    tokens = make_service()
    result = asyncio.run(
        LoginHandler(lambda: uow, FakePasswordVerifier(), tokens).handle(
            LoginCommand(email=uow.users.user.email, password="password")
        )
    )
    access = tokens.decode_access(result.access_token)
    refresh = tokens.decode_refresh(result.refresh_token)
    assert access.session_id is not None
    assert access.session_id == refresh.session_id
    args = uow.auth_sessions.create.await_args.args
    assert args[0] == access.session_id
    assert args[1] == uow.users.user.id


def test_refresh_keeps_session_and_logout_revokes_access() -> None:
    uow, _ = make_fakes()
    tokens = make_service()
    active = True

    async def is_active(session_id, user_id):
        return active

    async def revoke(session_id, user_id):
        nonlocal active
        active = False

    uow.auth_sessions = AsyncMock()
    uow.auth_sessions.is_active.side_effect = is_active
    uow.auth_sessions.revoke.side_effect = revoke

    async def scenario() -> None:
        login = await LoginHandler(lambda: uow, FakePasswordVerifier(), tokens).handle(
            LoginCommand(email=uow.users.user.email, password="password")
        )
        refreshed = await RefreshHandler(lambda: uow, tokens).handle(
            RefreshCommand(refresh_token=login.refresh_token)
        )
        assert (
            tokens.decode_access(login.access_token).session_id
            == tokens.decode_access(refreshed.access_token).session_id
        )
        await LogoutHandler(lambda: uow, tokens).handle(
            LogoutCommand(refresh_token=refreshed.refresh_token)
        )
        with pytest.raises(AuthenticationError):
            await GetCurrentUserHandler(lambda: uow, tokens).handle(
                GetCurrentUserCommand(access_token=refreshed.access_token)
            )

    asyncio.run(scenario())


def test_logout_revokes_session_even_if_refresh_already_rotated() -> None:
    uow, _ = make_fakes(can_consume=False)
    uow.auth_sessions = AsyncMock()
    tokens = make_service()
    session_id = uuid4()
    refresh = tokens.issue_refresh(uow.users.user, session_id=session_id)

    asyncio.run(
        LogoutHandler(lambda: uow, tokens).handle(
            LogoutCommand(refresh_token=refresh.token)
        )
    )

    uow.auth_sessions.revoke.assert_awaited_once_with(session_id, uow.users.user.id)


def test_successful_account_switch_revokes_previous_browser_session() -> None:
    uow, _ = make_fakes()
    uow.auth_sessions = AsyncMock()
    tokens = make_service()
    previous_session = uuid4()
    previous_token = tokens.issue_refresh(uow.users.user, session_id=previous_session)
    command = LoginCommand(
        email=uow.users.user.email,
        password="password",
        previous_refresh_token=previous_token.token,
    )
    asyncio.run(
        LoginHandler(lambda: uow, FakePasswordVerifier(), tokens).handle(command)
    )
    uow.auth_sessions.revoke.assert_awaited_once_with(
        previous_session, uow.users.user.id
    )


def test_failed_account_switch_keeps_previous_session() -> None:
    uow, _ = make_fakes()
    uow.auth_sessions = AsyncMock()
    tokens = make_service()
    previous_token = tokens.issue_refresh(uow.users.user, session_id=uuid4())
    command = LoginCommand(
        email=uow.users.user.email,
        password="wrong",
        previous_refresh_token=previous_token.token,
    )
    with pytest.raises(AuthenticationError):
        asyncio.run(
            LoginHandler(
                lambda: uow, FakePasswordVerifier(matches=False), tokens
            ).handle(command)
        )
    uow.auth_sessions.revoke.assert_not_awaited()


def test_legacy_refresh_is_upgraded_to_shared_session() -> None:
    uow, _ = make_fakes()
    uow.auth_sessions = AsyncMock()
    tokens = make_service()
    old = tokens.issue_refresh(uow.users.user)
    refreshed = asyncio.run(
        RefreshHandler(lambda: uow, tokens).handle(
            RefreshCommand(refresh_token=old.token)
        )
    )
    access = tokens.decode_access(refreshed.access_token)
    refresh = tokens.decode_refresh(refreshed.refresh_token)
    assert access.session_id is not None
    assert refresh.session_id == access.session_id
    assert uow.auth_sessions.create.await_args.args[:2] == (
        access.session_id,
        uow.users.user.id,
    )
