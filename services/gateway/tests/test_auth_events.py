"""Успешный вход и регистрация сохраняют факт без передачи credentials."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_auth import FakePasswordVerifier, make_fakes


def test_login_adds_event_inside_its_uow():
    from gateway_service.application.auth import LoginCommand, LoginHandler

    unit, tokens = make_fakes()
    captured = []

    async def add(event_type, user):
        assert unit.active
        captured.append((event_type, user.id))

    unit.outbox = SimpleNamespace(add_user_event=add)
    asyncio.run(
        LoginHandler(lambda: unit, FakePasswordVerifier(), tokens).handle(
            LoginCommand(email=unit.users.user.email, password="plain"),
        )
    )
    assert captured == [("gateway.user.logged_in", unit.users.user.id)]


def test_registration_adds_event_without_changing_public_result():
    from test_backoffice import FakePasswordService, FakeUnitOfWork

    from gateway_service.application.backoffice import (
        CreateUserCommand,
        CreateUserHandler,
    )
    from gateway_service.domain.user import Role

    unit = FakeUnitOfWork()
    unit.outbox = SimpleNamespace(add_user_event=AsyncMock())
    result = asyncio.run(
        CreateUserHandler(lambda: unit, FakePasswordService()).handle(
            CreateUserCommand(
                email="new@example.test",
                password="plain",
                role=Role.STUDENT,
                first_name="Иван",
                last_name="Петров",
            ),
        )
    )
    unit.outbox.add_user_event.assert_awaited_once_with(
        "gateway.user.created", unit.users.created[0]
    )
    assert result.id == unit.users.created[0].id
