"""Проверяет форму как границу административных команд."""

import pytest

from backoffice_admin.forms import CreateUserForm, LinkParentStudentForm


def test_create_form_preserves_password_spaces():
    form = CreateUserForm(
        {
            "email": "student@example.com",
            "password": " secret ",
            "role": "student",
            "first_name": "Тестовый",
            "last_name": "Пользователь",
        }
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["password"] == " secret "


@pytest.mark.parametrize(
    "field,value",
    [
        ("email", "bad-email"),
        ("role", "unknown"),
        ("password", ""),
        ("password", "   "),
    ],
)
def test_create_form_rejects_invalid_input(field, value):
    data = {
        "email": "student@example.com",
        "password": "secret",
        "role": "student",
        "first_name": "Тестовый",
        "last_name": "Пользователь",
    }
    data[field] = value
    form = CreateUserForm(data)
    assert not form.is_valid()
    assert field in form.errors


def test_link_form_rejects_invalid_uuid():
    form = LinkParentStudentForm({"parent_id": "bad-id", "student_id": "bad-id"})
    assert not form.is_valid()
    assert set(form.errors) == {"parent_id", "student_id"}
