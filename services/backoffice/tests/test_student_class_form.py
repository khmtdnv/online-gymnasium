"""Проверяет выбор класса по загруженному списку, без локальной копии таблицы."""

from uuid import UUID

import pytest

from backoffice_admin import forms


def make_form(data):
    from backoffice_admin.journal_client import JournalClass

    return forms.AddStudentToClassForm(
        data,
        classes=[
            JournalClass(
                id=10, name="8А", study_year=2026, created_at="2026-10-15T12:00:00Z"
            )
        ],
    )


def test_class_label_and_cleaned_types():
    form = make_form(
        {"student_id": "aaaaaaaa-0000-4000-8000-000000000001", "class_id": "10"}
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["class_id"] == 10
    assert isinstance(form.cleaned_data["student_id"], UUID)
    assert "8А · 2026/2027" in form.as_p()


@pytest.mark.parametrize(
    "data",
    [
        {"student_id": "bad", "class_id": "10"},
        {"student_id": "aaaaaaaa-0000-4000-8000-000000000001", "class_id": "20"},
    ],
)
def test_invalid_uuid_or_unlisted_class_is_rejected(data):
    assert not make_form(data).is_valid()
