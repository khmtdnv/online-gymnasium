"""Проверяет фильтры, сортировку и преобразование периодов на реальных SELECT.

SQLite проверяет чтения, но не заменяет PostgreSQL-тесты ограничений и времени.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy import Index, MetaData, create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from journal_service.domain.student_class_period import StudentClassPeriod
from journal_service.infrastructure.models.school_class import ClassRow
from journal_service.infrastructure.models.student_class_period import (
    StudentClassPeriodRow,
)


@pytest.mark.parametrize("has_current_period", [True, False])
def test_get_current_period_for_student_filters_student_and_closed_history(
    has_current_period: bool,
) -> None:
    """Выполняет SELECT в SQLite: чужой ученик и закрытая история не подходят.

    ORM-объекты сохраняются в identity map без commit/expire, чтобы SQLite
    не потеряла UTC-смещение тестовых дат. Реальные timezone и ограничения
    PostgreSQL проверяются отдельно в интеграционных тестах.
    """
    from journal_service.infrastructure.student_class_period_repository import (
        SqlAlchemyStudentClassPeriodRepository,
    )

    student_id = UUID("aaaaaaaa-0000-4000-8000-000000000001")
    other_id = UUID("bbbbbbbb-0000-4000-8000-000000000002")
    joined_at = datetime(2026, 9, 1, 9, tzinfo=UTC)
    left_at = datetime(2026, 10, 1, 9, tzinfo=UTC)
    rows = [
        StudentClassPeriodRow(
            id=10,
            student_id=student_id,
            class_id=1,
            joined_at=joined_at,
            left_at=left_at,
        ),
        StudentClassPeriodRow(
            id=30,
            student_id=other_id,
            class_id=2,
            joined_at=joined_at,
            left_at=None,
        ),
    ]
    if has_current_period:
        rows.append(
            StudentClassPeriodRow(
                id=20,
                student_id=student_id,
                class_id=2,
                joined_at=left_at,
                left_at=None,
            )
        )

    engine = create_engine("sqlite://")
    try:
        # PostgreSQL partial index не переносится на SQLite: проверяем только
        # SELECT на частной копии таблицы без индекса, не меняя metadata ORM.
        table = StudentClassPeriodRow.__table__.to_metadata(MetaData())
        ClassRow.__table__.to_metadata(table.metadata)
        table.indexes.clear()
        table.create(engine)
        with Session(engine) as database:
            database.add_all(rows)
            database.flush()
            session = Mock(spec=AsyncSession)
            session.execute = AsyncMock(side_effect=database.execute)
            repository = SqlAlchemyStudentClassPeriodRepository(session)
            result = asyncio.run(repository.get_current_period_for_student(student_id))

            if has_current_period:
                assert isinstance(result, StudentClassPeriod)
                assert result.id == 20
                assert result.student_id == student_id
                assert result.class_id == 2
                assert result.joined_at == left_at
                assert result.left_at is None
            else:
                assert result is None
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("limit", "offset", "known_student", "expected_ids"),
    [
        (50, 0, True, [30, 10, 20]),
        (1, 1, True, [10]),
        (2, 1, True, [10, 20]),
        (50, 3, True, []),
        (50, 0, False, []),
    ],
)
def test_list_periods_for_student_orders_history_before_pagination(
    limit: int, offset: int, known_student: bool, expected_ids: list[int]
) -> None:
    """Читает закрытые и открытые периоды по дате/ID, исключая чужого ученика.

    Реальный SELECT выполняется в SQLite без PostgreSQL-only индекса.
    Объекты не expire, чтобы смещения тестовых дат остались в identity map.
    """
    from journal_service.infrastructure.student_class_period_repository import (
        SqlAlchemyStudentClassPeriodRepository,
    )

    student_id = UUID("aaaaaaaa-0000-4000-8000-000000000001")
    other_id = UUID("bbbbbbbb-0000-4000-8000-000000000002")
    missing_id = UUID("cccccccc-0000-4000-8000-000000000003")
    september = datetime(2026, 9, 1, 9, tzinfo=UTC)
    october = datetime(2026, 10, 1, 9, tzinfo=UTC)
    rows = [
        StudentClassPeriodRow(
            id=20,
            student_id=student_id,
            class_id=1,
            joined_at=october,
            left_at=None,
        ),
        StudentClassPeriodRow(
            id=30,
            student_id=student_id,
            class_id=1,
            joined_at=september,
            left_at=october,
        ),
        StudentClassPeriodRow(
            id=10,
            student_id=student_id,
            class_id=2,
            joined_at=october,
            left_at=october,
        ),
        StudentClassPeriodRow(
            id=1,
            student_id=other_id,
            class_id=2,
            joined_at=september,
            left_at=None,
        ),
    ]
    expected_fields = {
        30: (1, september, october),
        10: (2, october, october),
        20: (1, october, None),
    }
    engine = create_engine("sqlite://")
    try:
        table = StudentClassPeriodRow.__table__.to_metadata(MetaData())
        ClassRow.__table__.to_metadata(table.metadata)
        table.indexes.clear()
        table.create(engine)
        with Session(engine) as database:
            database.add_all(rows)
            database.flush()
            session = Mock(spec=AsyncSession)
            session.scalars = AsyncMock(side_effect=database.scalars)
            repository = SqlAlchemyStudentClassPeriodRepository(session)
            result = asyncio.run(
                repository.list_periods_for_student(
                    student_id if known_student else missing_id,
                    limit,
                    offset,
                )
            )

            assert isinstance(result, list)
            assert [period.id for period in result] == expected_ids
            for period in result:
                assert isinstance(period, StudentClassPeriod)
                assert period.student_id == student_id
                assert (
                    period.class_id,
                    period.joined_at,
                    period.left_at,
                ) == expected_fields[period.id]
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("class_id", "limit", "offset", "expected_ids"),
    [
        (1, 50, 0, [20, 30, 40]),
        (1, 1, 1, [30]),
        (1, 2, 1, [30, 40]),
        (2, 50, 0, [1]),
        (3, 50, 0, []),
        (1, 50, 3, []),
    ],
)
def test_list_current_periods_for_class_filters_and_orders_before_pagination(
    class_id: int, limit: int, offset: int, expected_ids: list[int]
) -> None:
    """Читает только открытые периоды класса и выдаёт страницы по возрастанию ID."""
    from journal_service.infrastructure.student_class_period_repository import (
        SqlAlchemyStudentClassPeriodRepository,
    )

    joined_at = datetime(2026, 9, 1, 9, tzinfo=UTC)
    closed_at = datetime(2026, 10, 1, 9, tzinfo=UTC)
    students = {
        "a": UUID("aaaaaaaa-0000-4000-8000-000000000001"),
        "b": UUID("bbbbbbbb-0000-4000-8000-000000000002"),
        "c": UUID("cccccccc-0000-4000-8000-000000000003"),
        "d": UUID("dddddddd-0000-4000-8000-000000000004"),
    }
    rows = [
        StudentClassPeriodRow(
            id=period_id,
            student_id=students[student],
            class_id=record_class,
            joined_at=joined_at,
            left_at=left_at,
        )
        for period_id, student, record_class, left_at in [
            (30, "c", 1, None),
            (10, "c", 1, closed_at),
            (20, "a", 1, None),
            (40, "b", 1, None),
            (1, "d", 2, None),
            (50, "d", 3, closed_at),
        ]
    ]
    engine = create_engine("sqlite://")
    try:
        table = StudentClassPeriodRow.__table__.to_metadata(MetaData())
        ClassRow.__table__.to_metadata(table.metadata)
        table.indexes.clear()
        # Альтернативный путь чтения не совпадает с ID-порядком: отсутствие
        # ORDER BY не должно скрыться за случайным порядком SQLite rowid.
        Index("test_class_student_order", table.c.class_id, table.c.student_id.desc())
        table.create(engine)
        with Session(engine) as database:
            database.add_all(rows)
            database.flush()
            session = Mock(spec=AsyncSession)
            session.scalars = AsyncMock(side_effect=database.scalars)
            repository = SqlAlchemyStudentClassPeriodRepository(session)
            result = asyncio.run(
                repository.list_current_periods_for_class(class_id, limit, offset)
            )

            assert isinstance(result, list)
            assert [period.id for period in result] == expected_ids
            expected_students = {
                20: students["a"],
                30: students["c"],
                40: students["b"],
                1: students["d"],
            }
            for period in result:
                assert isinstance(period, StudentClassPeriod)
                assert period.class_id == class_id
                assert period.student_id == expected_students[period.id]
                assert period.joined_at == joined_at
                assert period.left_at is None
    finally:
        engine.dispose()
