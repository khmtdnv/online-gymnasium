"""Настоящие ограничения, конкурентный INSERT и обратимость миграции."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.test_domain_homework import data

pytestmark = pytest.mark.integration


def test_both_due_modes_roundtrip_and_reads(engine):
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run():
        async with SqlAlchemyUnitOfWork(factory) as uow:
            first = await uow.homeworks.add(Homework(**data()))
            second = await uow.homeworks.add(
                Homework(
                    **data(
                        issued_lesson_id=21,
                        due_lesson_id=None,
                        manual_due_datetime=datetime(2026, 11, 1, tzinfo=UTC),
                    )
                )
            )
        assert first.id == 1 and second.id == 2
        assert first.created_at.utcoffset() is not None
        async with SqlAlchemyUnitOfWork(factory) as uow:
            assert await uow.homeworks.get_by_id(1) == first
            assert await uow.homeworks.get_by_issued_lesson_id(21) == second
            assert await uow.homeworks.get_by_id(999) is None

    asyncio.run(run())


def test_concurrent_duplicate_and_new_transaction_after_rollback(engine):
    from homework_service.application.ports.errors import HomeworkAlreadyExistsError
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def insert():
        try:
            async with SqlAlchemyUnitOfWork(factory) as uow:
                await uow.homeworks.add(Homework(**data()))
            return "created"
        except HomeworkAlreadyExistsError:
            return "conflict"

    async def run():
        assert sorted(await asyncio.gather(insert(), insert())) == [
            "conflict",
            "created",
        ]
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM homework_assignments")
                )
                == 1
            )
        async with SqlAlchemyUnitOfWork(factory) as uow:
            assert (await uow.homeworks.get_by_issued_lesson_id(11)).id is not None

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"description": ""},
        {"description": " x "},
        {"description": "x" * 10001},
        {"due_lesson_id": None},
        {"manual_due_datetime": datetime(2026, 11, 1, tzinfo=UTC)},
        {"class_id": 0},
        {"description": "\t\n"},
        {"description": "\tРешить задачи\n"},
        {"description": "\u00a0Решить задачи\u3000"},
    ],
)
def test_database_rejects_invalid_raw_rows(engine, changes):
    from homework_service.infrastructure.models.homework import HomeworkRow

    async def run():
        async with async_sessionmaker(engine)() as session:
            session.add(HomeworkRow(**(data(description="valid") | changes)))
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

    asyncio.run(run())


def test_body_error_rolls_back_insert(engine):
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    async def run():
        with pytest.raises(RuntimeError):
            async with SqlAlchemyUnitOfWork(async_sessionmaker(engine)) as uow:
                await uow.homeworks.add(Homework(**data()))
                raise RuntimeError("later operation failed")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM homework_assignments")
                )
                == 0
            )

    asyncio.run(run())


def test_migration_roundtrip(migrate, engine):
    migrate("base", "downgrade")
    migrate("head")

    async def run():
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext

        from homework_service.infrastructure.models.base import Base

        async with engine.connect() as connection:
            differences = await connection.run_sync(
                lambda conn: compare_metadata(
                    MigrationContext.configure(conn), Base.metadata
                )
            )
            assert differences == []

    asyncio.run(run())
