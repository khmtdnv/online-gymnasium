"""Отдельные ошибки полей и миграция ограничений без потери задания."""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.test_domain_homework import data

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("field", "constraint"),
    [
        ("issued_lesson_id", "homework_assignments_issued_lesson_positive"),
        ("class_id", "homework_assignments_class_positive"),
        ("subject_id", "homework_assignments_subject_positive"),
        ("due_lesson_id", "homework_assignments_due_lesson_positive"),
    ],
)
@pytest.mark.parametrize("invalid", [0, -1])
def test_database_reports_specific_invalid_reference(
    engine, field, constraint, invalid
):
    from homework_service.infrastructure.models.homework import HomeworkRow

    async def run():
        async with async_sessionmaker(engine)() as session:
            session.add(
                HomeworkRow(**(data(description="Задачи 1–3") | {field: invalid}))
            )
            with pytest.raises(IntegrityError) as caught:
                await session.flush()
            assert caught.value.driver_exception.sqlstate == "23514"
            assert caught.value.driver_exception.constraint_name == constraint
            await session.rollback()

    asyncio.run(run())


def test_column_check_migration_preserves_existing_assignment(engine, migrate):
    # Existing schema and row must survive replacement of the combined CHECK.
    migrate("21c39bd05a74", "downgrade")

    async def seed():
        async with engine.begin() as conn:
            return await conn.scalar(
                text(
                    "INSERT INTO homework_assignments(issued_lesson_id,class_id,subject_id,author_id,description,due_lesson_id) VALUES (11,7,3,:author,'Задачи 1–3',12) RETURNING id"
                ),
                {"author": UUID(int=1)},
            )

    id = asyncio.run(seed())
    migrate("head")

    async def verify():
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id,issued_lesson_id,class_id,subject_id,description,due_lesson_id FROM homework_assignments"
                    )
                )
            ).one()
            assert tuple(row) == (id, 11, 7, 3, "Задачи 1–3", 12)
            constraints = await conn.run_sync(
                lambda sync: inspect(sync).get_check_constraints("homework_assignments")
            )
            names = {item["name"] for item in constraints}
            assert "homework_assignments_positive_references" not in names
            assert {
                "homework_assignments_issued_lesson_positive",
                "homework_assignments_class_positive",
                "homework_assignments_subject_positive",
                "homework_assignments_due_lesson_positive",
            } <= names

    asyncio.run(verify())
