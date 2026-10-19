"""Проверяет обратимое переименование на данных отдельной тестовой PostgreSQL-БД."""

import asyncio
import os
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from alembic import command
from alembic.config import Config
from conftest import database, require_test_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def test_period_rename_preserves_history_objects_and_sequence(
    database_url: str,
) -> None:
    """Сохраняет строки, существующие объекты БД и счётчик при откате и обновлении."""
    require_test_url(database_url)
    service_dir = Path(__file__).resolve().parents[2]
    config = Config(str(service_dir / "alembic.ini"))
    config.set_main_option("script_location", str(service_dir / "migrations"))

    async def prepare() -> int:
        async with (
            database(database_url) as (engine, _),
            engine.begin() as connection,
        ):
            class_id = await connection.scalar(
                text(
                    "INSERT INTO classes (name, study_year) VALUES ('7А', 2026) RETURNING id"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO student_class_periods (student_id, class_id, joined_at, left_at) "
                    "VALUES (:student, :class_id, '2026-09-01T09:00:00Z', '2026-10-01T09:00:00Z'), "
                    "(:student, :class_id, '2026-10-01T09:00:00Z', NULL)"
                ),
                {
                    "student": UUID("aaaaaaaa-0000-4000-8000-000000000001"),
                    "class_id": class_id,
                },
            )
            return class_id

    async def snapshot(table_name: str) -> dict:
        require_test_url(database_url)
        assert table_name in ("class_memberships", "student_class_periods")
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                rows = (
                    await connection.execute(
                        text(
                            f"SELECT id, student_id, class_id, joined_at, left_at FROM {table_name} ORDER BY id"
                        )
                    )
                ).all()
                objects = []
                for name in (
                    table_name,
                    f"{table_name}_current_student_unique",
                    f"{table_name}_id_seq",
                ):
                    objects.append(
                        await connection.scalar(
                            text(
                                "SELECT oid::bigint FROM pg_class WHERE oid = to_regclass(:name)"
                            ),
                            {"name": name},
                        )
                    )
                assert all(oid is not None for oid in objects)
                constraints = set(
                    (
                        await connection.execute(
                            text(
                                "SELECT conname FROM pg_constraint "
                                "WHERE conrelid = to_regclass(:name) AND contype IN ('c', 'p', 'f')"
                            ),
                            {"name": table_name},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert constraints == {
                    f"{table_name}_valid_period",
                    f"{table_name}_pkey",
                    f"{table_name}_class_id_fkey",
                }
                counter = (
                    await connection.execute(
                        text(f"SELECT last_value, is_called FROM {table_name}_id_seq")
                    )
                ).one()
                other_name = (
                    "class_memberships"
                    if table_name == "student_class_periods"
                    else "student_class_periods"
                )
                assert (
                    await connection.scalar(
                        text("SELECT to_regclass(:name)"), {"name": other_name}
                    )
                    is None
                )
                return {"rows": rows, "objects": objects, "counter": counter}
        finally:
            await engine.dispose()

    class_id = asyncio.run(prepare())
    before = asyncio.run(snapshot("student_class_periods"))
    assert len(before["rows"]) == 2
    assert before["rows"][0].left_at is not None
    assert before["rows"][1].left_at is None

    with patch.dict(os.environ, {"DATABASE_URL": database_url}):
        try:
            command.downgrade(config, "f98bb7a9333b")
            assert asyncio.run(snapshot("class_memberships")) == before
            command.upgrade(config, "head")
            assert asyncio.run(snapshot("student_class_periods")) == before
        finally:
            # Даже неудачная проверка не оставляет остальной suite на старой схеме.
            command.upgrade(config, "head")

    async def insert_next() -> int:
        require_test_url(database_url)
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                return await connection.scalar(
                    text(
                        "INSERT INTO student_class_periods (student_id, class_id) "
                        "VALUES (:student, :class_id) RETURNING id"
                    ),
                    {
                        "student": UUID("bbbbbbbb-0000-4000-8000-000000000002"),
                        "class_id": class_id,
                    },
                )
        finally:
            await engine.dispose()

    assert asyncio.run(insert_next()) == before["counter"].last_value + 1
