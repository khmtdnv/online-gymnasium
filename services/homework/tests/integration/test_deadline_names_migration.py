"""Переименование ручной даты обратимо и сохраняет её значение."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import inspect, text


def test_renaming_manual_datetime_preserves_value_in_both_directions(engine, migrate):
    migrate("b7c81d9e42af", "downgrade")
    value = datetime(2026, 12, 1, 18, tzinfo=UTC)

    async def seed():
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO homework_assignments "
                    "(issued_lesson_id,class_id,subject_id,author_id,description,due_at) "
                    "VALUES (11,7,3,:author,'Срок',:deadline)"
                ),
                {"author": UUID(int=1), "deadline": value},
            )

    async def verify(column, missing):
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: inspect(sync).get_columns("homework_assignments")
            )
            names = {item["name"] for item in columns}
            assert column in names and missing not in names
            assert (
                await connection.scalar(
                    text(
                        f"SELECT {column} FROM homework_assignments WHERE issued_lesson_id=11"
                    )
                )
                == value
            )

    asyncio.run(seed())
    migrate("head")
    asyncio.run(verify("manual_due_datetime", "due_at"))
    migrate("b7c81d9e42af", "downgrade")
    try:
        asyncio.run(verify("due_at", "manual_due_datetime"))
    finally:
        migrate("head")
    asyncio.run(verify("manual_due_datetime", "due_at"))
