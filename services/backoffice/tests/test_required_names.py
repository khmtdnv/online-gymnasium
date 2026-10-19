"""Форма создания не принимает отсутствие имени или фамилии."""

import pytest

from backoffice_admin.forms import CreateUserForm


@pytest.mark.parametrize("field", ["first_name", "last_name"])
@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_create_requires_nonblank_name(field, value):
    data = {
        "email": "a@example.com",
        "password": "secret",
        "role": "student",
        "first_name": "Иван",
        "last_name": "Петров",
    }
    data[field] = value
    form = CreateUserForm(data)
    assert not form.is_valid()
    assert field in form.errors


def test_create_allows_no_middle_name():
    form = CreateUserForm(
        {
            "email": "a@example.com",
            "password": "secret",
            "role": "student",
            "first_name": "Иван",
            "last_name": "Петров",
        }
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["middle_name"] == ""
