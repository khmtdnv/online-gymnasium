"""Проверяет сохранение истории и ограничения членства настоящим PostgreSQL."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from conftest import database
from sqlalchemy import insert, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from journal_service.infrastructure.models.student_class_period import (
    StudentClassPeriodRow,
)


async def create_classes(connection: AsyncConnection) -> tuple[int, int]:
    """Создаёт два класса для проверки переводов без участия application.

    Args:
        connection: Соединение внутри текущей тестовой транзакции.

    Returns:
        ID классов 7А и 7Б.
    """
    result = await connection.execute(
        text(
            "INSERT INTO classes (name, study_year) VALUES ('7А', 2026), ('7Б', 2026) RETURNING id, name"
        )
    )
    ids = {row.name: row.id for row in result}
    return ids["7А"], ids["7Б"]


async def add_period(
    connection: AsyncConnection,
    student_id: UUID,
    class_id: int,
    *,
    joined_at: datetime | None = None,
    left_at: datetime | None = None,
) -> RowMapping:
    """Вставляет период напрямую, чтобы проверялось ограничение БД, а не домен.

    Args:
        connection: Соединение внутри тестовой транзакции.
        student_id: ID ученика; БД Gateway в тесте не используется.
        class_id: ID локального класса.
        joined_at: Явное начало или использование серверного default.
        left_at: Время выхода; None оставляет период открытым.

    Returns:
        Сохранённые поля периода, включая серверные ID и время.
    """
    values = {"student_id": student_id, "class_id": class_id, "left_at": left_at}
    if joined_at is not None:
        values["joined_at"] = joined_at
    result = await connection.execute(
        insert(StudentClassPeriodRow)
        .values(**values)
        .returning(*StudentClassPeriodRow.__table__.columns)
    )
    return result.mappings().one()


def test_open_class_period_has_server_id_and_aware_joined_at(database_url: str) -> None:
    """Получает положительный ID и серверное время при вставке открытого периода."""

    async def run():
        async with database(database_url) as (engine, _):
            student_id = uuid4()
            async with engine.begin() as connection:
                class_id, _ = await create_classes(connection)
                row = await add_period(connection, student_id, class_id)
                assert row["id"] > 0
                assert row["student_id"] == student_id
                assert row["class_id"] == class_id
                assert row["joined_at"].utcoffset() is not None
                assert row["left_at"] is None

    asyncio.run(run())


def test_closed_periods_do_not_block_one_open_class_period(database_url: str) -> None:
    """Допускает историю ученика и других учеников того же класса."""

    async def run():
        async with database(database_url) as (engine, _):
            student = uuid4()
            joined = datetime(2026, 9, 1, tzinfo=UTC)
            left = datetime(2026, 9, 2, tzinfo=UTC)
            async with engine.begin() as connection:
                class_id, _ = await create_classes(connection)
                first = await add_period(
                    connection, student, class_id, joined_at=joined, left_at=left
                )
                second = await add_period(
                    connection, student, class_id, joined_at=left, left_at=left
                )
                current = await add_period(connection, student, class_id)
                other = await add_period(connection, uuid4(), class_id)
                assert len({row["id"] for row in (first, second, current, other)}) == 4

    asyncio.run(run())


def test_second_open_class_period_is_rejected(database_url: str) -> None:
    """Не позволяет открыть другой класс ученику с текущим членством."""

    async def run():
        async with database(database_url) as (engine, _):
            student = uuid4()
            async with engine.begin() as connection:
                first, second = await create_classes(connection)
                await add_period(connection, student, first)
            with pytest.raises(IntegrityError) as caught:
                async with engine.begin() as connection:
                    await add_period(connection, student, second)
            error = caught.value.driver_exception
            assert error.sqlstate == "23505"
            assert (
                error.constraint_name == "student_class_periods_current_student_unique"
            )

    asyncio.run(run())


def test_concurrent_open_class_periods_have_one_winner(database_url: str) -> None:
    """Две независимые транзакции не могут сохранить два текущих класса."""

    async def run():
        async with database(database_url) as (engine, _):
            async with engine.begin() as connection:
                first, second = await create_classes(connection)
            student, start = uuid4(), asyncio.Event()
            ready = asyncio.Queue()

            async def create(class_id):
                async with engine.begin() as connection:
                    await ready.put(True)
                    await start.wait()
                    return await add_period(connection, student, class_id)

            tasks = [
                asyncio.create_task(create(first)),
                asyncio.create_task(create(second)),
            ]
            await asyncio.wait_for(ready.get(), timeout=10)
            await asyncio.wait_for(ready.get(), timeout=10)
            start.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors = [row for row in results if isinstance(row, IntegrityError)]
            assert len(errors) == 1
            assert errors[0].driver_exception.sqlstate == "23505"
            assert (
                errors[0].driver_exception.constraint_name
                == "student_class_periods_current_student_unique"
            )
            assert sum(isinstance(row, RowMapping) for row in results) == 1
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM student_class_periods")
                    )
                    == 1
                )

    asyncio.run(run())


def test_unknown_class_is_rejected(database_url: str) -> None:
    """Не допускает ссылки на класс, которого нет в локальной таблице."""

    async def run():
        async with database(database_url) as (engine, _):
            with pytest.raises(IntegrityError) as caught:
                async with engine.begin() as connection:
                    await add_period(connection, uuid4(), 123456789)
            assert caught.value.driver_exception.sqlstate == "23503"

    asyncio.run(run())


def test_reverse_period_is_rejected(database_url: str) -> None:
    """Отвергает неверный порядок дат при прямой записи, минуя домен."""

    async def run():
        async with database(database_url) as (engine, _):
            joined = datetime(2026, 9, 1, tzinfo=UTC)
            async with engine.begin() as connection:
                class_id, _ = await create_classes(connection)
            with pytest.raises(IntegrityError) as caught:
                async with engine.begin() as connection:
                    await add_period(
                        connection,
                        uuid4(),
                        class_id,
                        joined_at=joined,
                        left_at=joined - timedelta(seconds=1),
                    )
            error = caught.value.driver_exception
            assert error.sqlstate == "23514"
            assert error.constraint_name == "student_class_periods_valid_period"

    asyncio.run(run())


def test_class_with_history_cannot_be_deleted(database_url: str) -> None:
    """Не удаляет класс вместе с историей завершённых периодов."""

    async def run():
        async with database(database_url) as (engine, _):
            joined = datetime(2026, 9, 1, tzinfo=UTC)
            async with engine.begin() as connection:
                class_id, _ = await create_classes(connection)
                await add_period(
                    connection, uuid4(), class_id, joined_at=joined, left_at=joined
                )
            with pytest.raises(IntegrityError) as caught:
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM classes WHERE id = :id"), {"id": class_id}
                    )
            assert caught.value.driver_exception.sqlstate == "23503"
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM student_class_periods")
                    )
                    == 1
                )

    asyncio.run(run())


def test_return_to_class_creates_third_period(database_url: str) -> None:
    """Сохраняет три разные строки для перевода 7А → 7Б → 7А."""

    async def run():
        async with database(database_url) as (engine, _):
            student = uuid4()
            joined = datetime(2026, 9, 1, tzinfo=UTC)
            async with engine.begin() as connection:
                first_class, second_class = await create_classes(connection)
                first = await add_period(
                    connection, student, first_class, joined_at=joined
                )
                await connection.execute(
                    text(
                        "UPDATE student_class_periods SET left_at = :at WHERE id = :id"
                    ),
                    {"at": joined + timedelta(days=1), "id": first["id"]},
                )
                second = await add_period(
                    connection,
                    student,
                    second_class,
                    joined_at=joined + timedelta(days=1),
                )
                await connection.execute(
                    text(
                        "UPDATE student_class_periods SET left_at = :at WHERE id = :id"
                    ),
                    {"at": joined + timedelta(days=2), "id": second["id"]},
                )
                third = await add_period(
                    connection,
                    student,
                    first_class,
                    joined_at=joined + timedelta(days=2),
                )
                rows = (
                    await connection.execute(
                        text(
                            "SELECT id, class_id, left_at FROM student_class_periods ORDER BY id"
                        )
                    )
                ).all()
                assert [row.id for row in rows] == [
                    first["id"],
                    second["id"],
                    third["id"],
                ]
                assert [row.class_id for row in rows] == [
                    first_class,
                    second_class,
                    first_class,
                ]
                assert [row.left_at is None for row in rows] == [False, False, True]

    asyncio.run(run())
