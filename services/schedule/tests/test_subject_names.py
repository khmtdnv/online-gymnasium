"""Неизвестные предметы не получают выдуманных названий."""

import pytest


def test_subject_allows_unknown_legacy_name_but_rejects_blank_and_bad_id():
    from schedule_service.domain.subject import Subject

    assert Subject(id=7, name=None).name is None
    assert Subject(id=7, name="Математика").name == "Математика"
    for values in (
        {"id": 0, "name": "Физика"},
        {"id": True, "name": "Физика"},
        {"id": 7, "name": " "},
        {"id": 7, "name": " Физика"},
        {"id": 7, "name": "x" * 101},
    ):
        with pytest.raises((TypeError, ValueError)):
            Subject(**values)
