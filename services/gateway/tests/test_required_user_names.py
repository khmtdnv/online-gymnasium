"""Фиксирует обязательность имени и фамилии независимо от способа создания."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from gateway_service.application.backoffice import CreateUserCommand
from gateway_service.domain.user import Role, User


@pytest.mark.parametrize("field", ["first_name", "last_name"])
@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_command_rejects_blank_name(field, value):
    data = {
        "email": "a@example.com",
        "password": "secret",
        "role": Role.STUDENT,
        "first_name": "Иван",
        "last_name": "Петров",
    }
    data[field] = value
    with pytest.raises(ValidationError):
        CreateUserCommand(**data)


@pytest.mark.parametrize("field", ["first_name", "last_name"])
def test_command_requires_each_name(field):
    data = {
        "email": "a@example.com",
        "password": "secret",
        "role": Role.STUDENT,
        "first_name": "Иван",
        "last_name": "Петров",
    }
    del data[field]
    with pytest.raises(ValidationError):
        CreateUserCommand(**data)


def test_patronymic_is_optional_but_names_are_preserved():
    command = CreateUserCommand(
        email="a@example.com",
        password="secret",
        role=Role.STUDENT,
        first_name=" Иван ",
        last_name=" Петров ",
    )
    assert (command.first_name, command.last_name, command.middle_name) == (
        "Иван",
        "Петров",
        "",
    )


@pytest.mark.parametrize("field", ["first_name", "last_name"])
@pytest.mark.parametrize("value", ["", "  ", "\t", None, "x" * 101])
def test_domain_rejects_invalid_names(field, value):
    data = {
        "id": uuid4(),
        "email": "a@example.com",
        "role": Role.STUDENT,
        "password_hash": "hash",
        "is_active": True,
        "first_name": "Иван",
        "last_name": "Петров",
    }
    data[field] = value
    with pytest.raises(ValueError):
        User(**data)
