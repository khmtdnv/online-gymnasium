"""Проверки доменных правил имени класса и учебного года."""

import pytest


@pytest.mark.parametrize(
    ("name", "expected_name"),
    [
        (" 7А ", "7А"),
        ("\t7Б\n", "7Б"),
        (" 7  а ", "7  а"),
    ],
)
def test_class_normalizes_name(name: str, expected_name: str) -> None:
    """Удаляет внешние пробелы, сохраняя внутренние пробелы и регистр."""
    from journal_service.domain.school_class import Class

    data = Class(name=name, study_year=2026)

    assert data.name == expected_name


def test_class_accepts_64_characters_after_normalization() -> None:
    """Проверяет длину уже очищенного имени, включая верхнюю границу."""
    from journal_service.domain.school_class import Class

    data = Class(name="  " + "А" * 64 + "  ", study_year=2026)

    assert data.name == "А" * 64


@pytest.mark.parametrize("name", ["", "   ", "\t\n", "7\x00А"])
def test_class_rejects_blank_or_nul_name(name: str) -> None:
    """Не позволяет создать класс с пустым именем или нулевым символом."""
    from journal_service.domain.school_class import Class

    with pytest.raises(ValueError):
        Class(name=name, study_year=2026)


def test_class_rejects_name_longer_than_64_characters() -> None:
    """Отклоняет имя, превышающее допустимую длину."""
    from journal_service.domain.school_class import Class

    with pytest.raises(ValueError):
        Class(name="А" * 65, study_year=2026)


@pytest.mark.parametrize("study_year", [1900, 2026, 9998])
def test_class_accepts_valid_study_year(study_year: int) -> None:
    """Принимает допустимый год, включая обе границы диапазона."""
    from journal_service.domain.school_class import Class

    data = Class(name="7А", study_year=study_year)

    assert data.study_year == study_year


@pytest.mark.parametrize("study_year", [1899, 9999])
def test_class_rejects_study_year_outside_range(study_year: int) -> None:
    """Отклоняет год за пределами согласованного диапазона."""
    from journal_service.domain.school_class import Class

    with pytest.raises(ValueError):
        Class(name="7А", study_year=study_year)
