"""Проверки безопасного чтения пользователя для другого сервиса."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from gateway_service.application.errors import UserNotFoundError
from gateway_service.domain.user import Role, User

USER_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")


def make_handler(user):
    from gateway_service.application.user_lookup import GetUserHandler

    users = SimpleNamespace(get_by_id=AsyncMock(return_value=user))
    uow = AsyncMock()
    uow.__aenter__.return_value = SimpleNamespace(users=users)
    uow.__aexit__.return_value = False
    return GetUserHandler(Mock(return_value=uow)), uow, users


def test_get_user_returns_safe_result() -> None:
    """Не раскрывает email и хеш при чтении чужим сервисом."""
    from gateway_service.application.user_lookup import GetUserQuery

    user = User(
        USER_ID,
        "private@example.com",
        Role.PARENT,
        "private-hash",
        False,
        first_name="Тестовый",
        last_name="Пользователь",
    )
    handler, _, users = make_handler(user)
    result = asyncio.run(handler.handle(GetUserQuery(user_id=USER_ID)))
    assert result.model_dump() == {
        "id": USER_ID,
        "role": Role.PARENT,
        "is_active": False,
    }
    users.get_by_id.assert_awaited_once_with(USER_ID)


def test_missing_user_raises_not_found() -> None:
    """Отличает отсутствие пользователя от успешного ответа."""
    from gateway_service.application.user_lookup import GetUserQuery

    handler, uow, _ = make_handler(None)
    with pytest.raises(UserNotFoundError):
        asyncio.run(handler.handle(GetUserQuery(user_id=USER_ID)))
    assert uow.__aexit__.await_args.args[0] is UserNotFoundError


def test_lookup_exits_uow_before_return() -> None:
    """Не отдаёт результат до завершения транзакционного контекста."""
    from gateway_service.application.user_lookup import GetUserQuery

    user = User(
        USER_ID,
        "private@example.com",
        Role.STUDENT,
        "private-hash",
        True,
        first_name="Тестовый",
        last_name="Пользователь",
    )
    handler, uow, _ = make_handler(user)
    uow.__aexit__.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError, match="commit failed"):
        asyncio.run(handler.handle(GetUserQuery(user_id=USER_ID)))
