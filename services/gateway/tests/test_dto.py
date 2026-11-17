"""Проверяет границу создания DTO, не подменяя бизнес-сценарии."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from gateway_service.application.auth import RefreshCommand
from gateway_service.application.backoffice import CreateUserCommand, UserSummary
from gateway_service.application.user_lookup import GetUserQuery
from gateway_service.domain.user import Role


def test_user_query_rejects_unparsed_uuid() -> None:
    """Неверный тип ID не должен доходить до репозитория."""
    with pytest.raises(ValidationError):
        GetUserQuery(user_id="not-a-uuid")


def test_user_summary_rejects_non_boolean_activity() -> None:
    """Строка не должна незаметно становиться признаком активности."""
    with pytest.raises(ValidationError):
        UserSummary(
            id=uuid4(),
            email="a@example.com",
            role=Role.STUDENT,
            is_active="false",
            first_name="Тестовый",
            last_name="Пользователь",
        )


def test_refresh_command_rejects_unknown_fields() -> None:
    """Опечатка в аргументе не должна исчезать из команды."""
    with pytest.raises(ValidationError):
        RefreshCommand(refresh_token="token", banana=123)


@pytest.mark.parametrize(
    ("field", "value"), [("email", " "), ("password", "\t"), ("email", 42)]
)
def test_create_user_rejects_blank_or_nonstring_fields(field, value) -> None:
    """Некорректный вход отклоняется до хеширования пароля."""
    values = {
        "email": "a@example.com",
        "password": " password ",
        "role": Role.STUDENT,
        "first_name": "Тестовый",
        "last_name": "Пользователь",
    }
    values[field] = value
    with pytest.raises(ValidationError):
        CreateUserCommand(**values)


def test_create_user_preserves_password_and_enum() -> None:
    """Валидатор не должен незаметно обрезать пароль или менять enum."""
    command = CreateUserCommand(
        email="a@example.com",
        password=" password ",
        role=Role.STUDENT,
        first_name="Тестовый",
        last_name="Пользователь",
    )
    assert command.password == " password "
    assert command.role is Role.STUDENT


def test_refresh_command_cannot_be_reassigned() -> None:
    """Готовая команда остаётся неизменяемой."""
    command = RefreshCommand(refresh_token="token")
    with pytest.raises(ValidationError):
        command.refresh_token = "another"


def test_issued_refresh_rejects_naive_expiration() -> None:
    """Срок действия выпускаемого токена содержит часовой пояс."""
    from gateway_service.application.ports.token_service import IssuedRefresh

    with pytest.raises(ValidationError):
        IssuedRefresh(
            token="jwt",
            jti=uuid4(),
            expires_at=datetime(2026, 10, 14, tzinfo=UTC).replace(tzinfo=None),
        )
