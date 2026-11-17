"""Обе группы выбираются по ссылкам, индекс не изменяет задания."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_card_groups_and_reversible_due_index(engine, migrate):
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def check(insert=False, index=True):
        if insert:
            async with SqlAlchemyUnitOfWork(sessions) as uow:
                for issued, due in [(11, None), (10, 11), (12, 99)]:
                    await uow.homeworks.add(
                        Homework(
                            issued_lesson_id=issued,
                            class_id=7,
                            subject_id=3,
                            author_id=UUID(int=1),
                            description="Проверить",
                            due_lesson_id=due,
                            manual_due_datetime=datetime(2026, 11, 1, tzinfo=UTC)
                            if due is None
                            else None,
                        )
                    )
        async with SqlAlchemyUnitOfWork(sessions) as uow:
            rows = await uow.homeworks.list_for_lesson(11)
            assert [row.id for row in rows] == [2, 1]
            assert await uow.homeworks.list_for_lesson(999) == []
        async with engine.connect() as connection:
            present = await connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE indexname='homework_assignments_due_lesson_idx'"
                )
            )
            assert bool(present) == index
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM homework_assignments")
                )
                == 3
            )

    asyncio.run(check(insert=True))
    migrate("e13c8bd4a902", "downgrade")
    try:
        asyncio.run(check(index=False))
    finally:
        migrate("head")
    asyncio.run(check())
