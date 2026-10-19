"""Индекс мигрируется обратимо, не меняя уже сохранённые задания."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_read_index_upgrade_downgrade_preserves_rows(engine, migrate):
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def insert():
        async with SqlAlchemyUnitOfWork(factory) as uow:
            await uow.homeworks.add(
                Homework(
                    issued_lesson_id=11,
                    class_id=7,
                    subject_id=3,
                    author_id=UUID(int=1),
                    description="Сохранить",
                    manual_due_datetime=datetime(2026, 12, 1, tzinfo=UTC),
                )
            )

    async def check(expected):
        async with engine.connect() as connection:
            present = await connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE tablename='homework_assignments' "
                    "AND indexname='homework_assignments_class_created_id_idx'"
                )
            )
            assert bool(present) == expected
            if expected:
                assert "(class_id, created_at DESC, id DESC)" in present
            assert (
                await connection.scalar(
                    text("SELECT description FROM homework_assignments WHERE id=1")
                )
                == "Сохранить"
            )
        # После downgrade колонка ручной даты имеет старое имя. Проверку
        # текущим ORM выполняем только после восстановления полной схемы.
        if expected:
            async with SqlAlchemyUnitOfWork(factory) as uow:
                assert [
                    item.id for item in await uow.homeworks.list_for_class(7, 2, 0)
                ] == [1]
                assert await uow.homeworks.list_for_class(8, 2, 0) == []

    asyncio.run(insert())
    asyncio.run(check(True))
    migrate("93f52dc710ab", "downgrade")
    try:
        asyncio.run(check(False))
    finally:
        migrate("head")
    asyncio.run(check(True))


def test_real_list_filters_sorts_ties_and_paginates(engine):
    from homework_service.infrastructure.models.homework import HomeworkRow
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run():
        async with factory.begin() as session:
            for id, class_id, day in [(1, 7, 10), (2, 7, 10), (3, 7, 9), (4, 8, 11)]:
                session.add(
                    HomeworkRow(
                        id=id,
                        issued_lesson_id=100 + id,
                        class_id=class_id,
                        subject_id=3,
                        author_id=UUID(int=1),
                        description="Задача",
                        manual_due_datetime=datetime(2026, 12, 1, tzinfo=UTC),
                        created_at=datetime(2026, 10, day, tzinfo=UTC),
                    )
                )
        async with SqlAlchemyUnitOfWork(factory) as uow:
            page = await uow.homeworks.list_for_class(7, 2, 1)
            assert [item.id for item in page] == [1, 3]
            assert await uow.homeworks.list_for_class(7, 2, 99) == []

    asyncio.run(run())
