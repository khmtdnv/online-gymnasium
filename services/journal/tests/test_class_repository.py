"""Проверяет преобразование ORM-строки и границу транзакции репозитория.

Сессия подменена: поведение PostgreSQL эти тесты не доказывают.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from asyncpg.exceptions import CheckViolationError, UniqueViolationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import EmulatedDBAPIException, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from journal_service.application.ports.errors import DuplicateClassError
from journal_service.domain.school_class import Class
from journal_service.infrastructure.models.school_class import ClassRow


def test_create_class_returns_saved_domain_data_without_committing() -> None:
    """Требует данные сохранённой строки и оставляет commit владельцу UoW."""
    from journal_service.infrastructure.class_repository import (
        SqlAlchemyClassRepository,
    )

    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    rows = []
    created_at = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)

    def add(row: ClassRow) -> None:
        rows.append(row)

    async def flush() -> None:
        for row in rows:
            row.id = 42

    async def refresh(row: ClassRow) -> None:
        row.created_at = created_at

    session.add.side_effect = add
    session.flush.side_effect = flush
    session.refresh.side_effect = refresh
    repository = SqlAlchemyClassRepository(session)

    result = asyncio.run(repository.create_class(Class(name="7А", study_year=2026)))

    assert isinstance(result, Class)
    assert result.id == 42
    assert result.name == "7А"
    assert result.study_year == 2026
    assert result.created_at == created_at
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    ("study_year", "limit", "offset", "expected_ids"),
    [
        (None, 50, 0, [10, 20, 30, 40]),
        (2026, 50, 0, [10, 30, 40]),
        (None, 2, 1, [20, 30]),
        (2026, 1, 1, [30]),
        (2025, 50, 0, []),
        (None, 50, 10, []),
    ],
)
def test_list_classes_filters_orders_and_returns_domain_objects(
    study_year: int | None,
    limit: int,
    offset: int,
    expected_ids: list[int],
) -> None:
    """Выполняет реальный SELECT в SQLite; PostgreSQL проверим отдельно."""
    from journal_service.infrastructure.class_repository import (
        SqlAlchemyClassRepository,
    )

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def register_name_functions(connection, _record) -> None:
        connection.create_function("char_length", 1, len)
        connection.create_function("btrim", 1, lambda value: value.strip(" "))

    # Эти функции обеспечивают только совместимость таблицы с SQLite.
    # Их регистрация не доказывает работу ограничений PostgreSQL.
    ClassRow.__table__.create(engine)
    try:
        with Session(engine) as database:
            database.add_all(
                [
                    ClassRow(id=40, name="8Б", study_year=2026),
                    ClassRow(id=10, name="7А", study_year=2026),
                    ClassRow(id=30, name="8А", study_year=2026),
                    ClassRow(id=20, name="7А", study_year=2027),
                ]
            )
            database.commit()
            session = Mock(spec=AsyncSession)
            session.execute = AsyncMock(side_effect=database.execute)
            session.scalars = AsyncMock(side_effect=database.scalars)
            session.commit = AsyncMock()
            repository = SqlAlchemyClassRepository(session)

            result = asyncio.run(repository.list_classes(study_year, limit, offset))

            assert isinstance(result, list)
            assert [school_class.id for school_class in result] == expected_ids
            names = {10: "7А", 20: "7А", 30: "8А", 40: "8Б"}
            years = {10: 2026, 20: 2027, 30: 2026, 40: 2026}
            for school_class in result:
                assert isinstance(school_class, Class)
                assert school_class.name == names[school_class.id]
                assert school_class.study_year == years[school_class.id]
                assert school_class.created_at is not None
            session.commit.assert_not_called()
    finally:
        engine.dispose()


def test_create_class_propagates_flush_failure_without_committing() -> None:
    """Не выдаёт успех, если запись не удалось отправить в базу."""
    from journal_service.infrastructure.class_repository import (
        SqlAlchemyClassRepository,
    )

    session = Mock(spec=AsyncSession)
    failure = RuntimeError("database write failed")
    session.flush = AsyncMock(side_effect=failure)
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    repository = SqlAlchemyClassRepository(session)

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(repository.create_class(Class(name="7А", study_year=2026)))

    assert caught.value is failure
    session.commit.assert_not_called()


def test_create_class_translates_named_unique_violation() -> None:
    """Переводит дубль имени и года в ошибку контракта репозитория."""
    from journal_service.infrastructure.class_repository import (
        SqlAlchemyClassRepository,
    )

    driver_error = UniqueViolationError("duplicate class")
    driver_error.constraint_name = "classes_name_study_year_unique"
    failure = IntegrityError(
        "INSERT INTO classes ...",
        {},
        EmulatedDBAPIException("database constraint failed", driver_error),
    )
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock(side_effect=failure)
    repository = SqlAlchemyClassRepository(session)

    with pytest.raises(DuplicateClassError) as caught:
        asyncio.run(repository.create_class(Class(name="7А", study_year=2026)))

    assert caught.value.__cause__ is failure


@pytest.mark.parametrize(
    ("error_type", "constraint_name"),
    [
        (UniqueViolationError, "classes_pkey"),
        (CheckViolationError, "classes_valid_study_year"),
        (CheckViolationError, "classes_name_study_year_unique"),
    ],
)
def test_create_class_preserves_unrelated_integrity_error(
    error_type: type[Exception], constraint_name: str
) -> None:
    """Не маскирует другую уникальность или CHECK под дубликат класса."""
    from journal_service.infrastructure.class_repository import (
        SqlAlchemyClassRepository,
    )

    driver_error = error_type("database constraint failed")
    driver_error.constraint_name = constraint_name
    failure = IntegrityError(
        "INSERT INTO classes ...",
        {},
        EmulatedDBAPIException("database constraint failed", driver_error),
    )
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock(side_effect=failure)
    repository = SqlAlchemyClassRepository(session)

    with pytest.raises(IntegrityError) as caught:
        asyncio.run(repository.create_class(Class(name="7А", study_year=2026)))

    assert caught.value is failure
