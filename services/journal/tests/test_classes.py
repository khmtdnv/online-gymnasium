"""Проверяет сценарии создания и чтения классов без HTTP и реальной базы."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from journal_service.application.classes import (
    ClassResult,
    CreateClassCommand,
    ListClassesQuery,
)
from journal_service.application.ports.errors import (
    DuplicateClassError,
)
from journal_service.domain.school_class import Class


def test_create_class_normalizes_name_and_returns_saved_data() -> None:
    """Передаёт нормализованный класс и возвращает его ID и серверное время."""
    from journal_service.application.classes import CreateClassHandler

    created_at = datetime(2026, 10, 11, 15, 0, tzinfo=UTC)
    received = []

    async def create_class(school_class: Class) -> Class:
        received.append(school_class)
        return Class(
            name=school_class.name,
            study_year=school_class.study_year,
            id=42,
            created_at=created_at,
        )

    uow = Mock()
    uow.classes.create_class = AsyncMock(side_effect=create_class)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    factory = Mock(return_value=uow)
    handler = CreateClassHandler(factory)

    result = asyncio.run(
        handler.handle(CreateClassCommand(name=" 7А ", study_year=2026))
    )

    assert result == ClassResult(
        id=42, name="7А", study_year=2026, created_at=created_at
    )
    assert len(received) == 1
    assert isinstance(received[0], Class)
    assert received[0].name == "7А"
    assert received[0].study_year == 2026
    factory.assert_called_once_with()


def test_create_class_does_not_return_success_when_commit_fails() -> None:
    """Не возвращает успешный результат при ошибке выхода из UoW."""
    from journal_service.application.classes import CreateClassHandler

    failure = RuntimeError("commit failed")
    uow = Mock()
    uow.classes.create_class = AsyncMock(
        return_value=Class(
            name="7А",
            study_year=2026,
            id=42,
            created_at=datetime(2026, 10, 11, 15, 0, tzinfo=UTC),
        )
    )
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(side_effect=failure)
    handler = CreateClassHandler(lambda: uow)

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(handler.handle(CreateClassCommand(name="7А", study_year=2026)))

    assert caught.value is failure


@pytest.mark.parametrize(
    ("query", "returned_ids", "expected_arguments"),
    [
        (ListClassesQuery(), [10, 20], (None, 50, 0)),
        (ListClassesQuery(study_year=2026, limit=1, offset=1), [20], (2026, 1, 1)),
        (ListClassesQuery(study_year=2025), [], (2025, 50, 0)),
    ],
)
def test_list_classes_passes_query_and_returns_result_objects(
    query: ListClassesQuery,
    returned_ids: list[int],
    expected_arguments: tuple[int | None, int, int],
) -> None:
    """Передаёт параметры репозиторию, преобразует классы и сохраняет порядок."""
    from journal_service.application.classes import ListClassesHandler

    created_at = datetime(2026, 10, 11, 15, 0, tzinfo=UTC)
    names = {10: "7А", 20: "7Б"}
    received = []

    async def list_classes(study_year, limit, offset) -> list[Class]:
        received.append((study_year, limit, offset))
        return [
            Class(
                id=class_id,
                name=names[class_id],
                study_year=2026,
                created_at=created_at,
            )
            for class_id in returned_ids
        ]

    uow = Mock()
    uow.classes.list_classes = AsyncMock(side_effect=list_classes)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    factory = Mock(return_value=uow)
    handler = ListClassesHandler(factory)

    result = asyncio.run(handler.handle(query))

    assert isinstance(result, list)
    assert received == [expected_arguments]
    assert result == [
        ClassResult(
            id=class_id, name=names[class_id], study_year=2026, created_at=created_at
        )
        for class_id in returned_ids
    ]
    factory.assert_called_once_with()


@pytest.mark.parametrize(
    ("name", "study_year"),
    [(" ", 2026), ("А" * 65, 2026), ("7А", 1899), ("7А", 9999), ("7\x00А", 2026)],
)
def test_create_class_rejects_invalid_data_before_opening_transaction(
    name: str, study_year: int
) -> None:
    """Переводит ошибку доменных данных, не обращаясь к базе."""
    from journal_service.application.classes import CreateClassHandler

    factory = Mock()
    handler = CreateClassHandler(factory)

    with pytest.raises(ValidationError):
        asyncio.run(
            handler.handle(CreateClassCommand(name=name, study_year=study_year))
        )

    factory.assert_not_called()


def test_create_class_preserves_repository_duplicate() -> None:
    """Передаёт понятную ошибку дубликата, не подавляя её на границе UoW."""
    from journal_service.application.classes import CreateClassHandler

    failure = DuplicateClassError()
    uow = Mock()
    uow.classes.create_class = AsyncMock(side_effect=failure)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    handler = CreateClassHandler(lambda: uow)

    with pytest.raises(DuplicateClassError) as caught:
        asyncio.run(handler.handle(CreateClassCommand(name="7А", study_year=2026)))

    assert caught.value is failure
    assert uow.__aexit__.await_args.args[1] is failure


def test_create_class_preserves_unexpected_repository_failure() -> None:
    """Не маскирует неожиданную ошибку записи как дубликат или плохие данные."""
    from journal_service.application.classes import CreateClassHandler

    failure = RuntimeError("database unavailable")
    uow = Mock()
    uow.classes.create_class = AsyncMock(side_effect=failure)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    handler = CreateClassHandler(lambda: uow)

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(handler.handle(CreateClassCommand(name="7А", study_year=2026)))

    assert caught.value is failure


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": 2**63},
        {"study_year": 2026, "offset": -1},
        {"study_year": 1899},
        {"study_year": 9999},
    ],
)
def test_list_classes_rejects_invalid_query_before_opening_transaction(
    query: dict,
) -> None:
    """Не отправляет неверный год или параметры страницы в репозиторий."""
    from journal_service.application.classes import ListClassesHandler

    uow = Mock()
    uow.classes.list_classes = AsyncMock(return_value=[])
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    factory = Mock(return_value=uow)
    handler = ListClassesHandler(factory)

    with pytest.raises(ValidationError):
        asyncio.run(handler.handle(ListClassesQuery(**query)))

    factory.assert_not_called()


@pytest.mark.parametrize(
    "query",
    [
        ListClassesQuery(study_year=1900, limit=1, offset=0),
        ListClassesQuery(study_year=9998, limit=100, offset=1),
    ],
)
def test_list_classes_accepts_boundary_query_values(query: ListClassesQuery) -> None:
    """Разрешает крайние допустимые годы и размеры страницы."""
    from journal_service.application.classes import ListClassesHandler

    uow = Mock()
    uow.classes.list_classes = AsyncMock(return_value=[])
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    handler = ListClassesHandler(lambda: uow)

    assert asyncio.run(handler.handle(query)) == []
