"""Реальная PostgreSQL: инвентаризация не теряет исторические ID и ничего не пишет."""

import asyncio
import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def test_inventory_command_supports_declared_python_312_syntax():
    """Не допускает синтаксис только 3.14 в новой команде для Python >=3.12."""
    import ast
    from pathlib import Path

    from schedule_service.workers import inspect_teacher_ids

    ast.parse(
        Path(inspect_teacher_ids.__file__).read_text(encoding="utf-8"),
        feature_version=(3, 12),
    )


async def seed(connection):
    await connection.execute(
        text(
            "INSERT INTO scheduled_lessons "
            "(id,class_id,teacher_id,subject_id,starts_at,ends_at) VALUES "
            "(501,7,42,1,'2026-10-19 10:00+00','2026-10-19 11:00+00')"
        )
    )
    await connection.execute(
        text(
            "INSERT INTO outbox_events(event_type,payload,published_at) VALUES "
            "('lesson.snapshot',CAST(:payload AS jsonb),now()),"
            "('schedule.changed',CAST(:changed AS jsonb),NULL)"
        ),
        {
            "payload": json.dumps({"lesson_id": 499, "teacher_id": 77}),
            "changed": json.dumps({"lesson_id": 501}),
        },
    )


def test_inventory_contains_outbox_only_teacher_and_preserves_rows(
    teacher_uuid_legacy_database_url,
):
    from schedule_service.infrastructure.teacher_id_migration import inspect_teacher_ids

    async def run():
        engine = create_async_engine(
            teacher_uuid_legacy_database_url, poolclass=NullPool
        )
        try:
            async with engine.begin() as connection:
                await seed(connection)
            async with engine.begin() as connection:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                report = await connection.run_sync(inspect_teacher_ids)
                assert report.legacy_ids == frozenset({42, 77})
                assert report.lesson_teacher_ids == frozenset({42})
                assert report.snapshot_teacher_ids == frozenset({77})
                assert report.lesson_count == 1
                assert report.snapshot_count == 1
                assert report.column_type == "integer"
                assert (
                    await connection.scalar(
                        text("SELECT teacher_id FROM scheduled_lessons")
                    )
                    == 42
                )
                assert (
                    await connection.scalar(text("SELECT count(*) FROM outbox_events"))
                    == 2
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cli_reports_ids_without_connection_secret(teacher_uuid_legacy_database_url):
    from schedule_service.workers.inspect_teacher_ids import run

    report = asyncio.run(run(teacher_uuid_legacy_database_url))
    assert report == {
        "column_type": "integer",
        "lesson_count": 0,
        "snapshot_count": 0,
        "lesson_teacher_ids": [],
        "snapshot_teacher_ids": [],
        "legacy_ids": [],
    }


def test_inventory_handles_already_uuid_schema(teacher_uuid_legacy_database_url):
    from schedule_service.infrastructure.teacher_id_migration import inspect_teacher_ids

    async def run():
        engine = create_async_engine(
            teacher_uuid_legacy_database_url, poolclass=NullPool
        )
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "ALTER TABLE scheduled_lessons ALTER COLUMN teacher_id TYPE uuid USING NULL::uuid"
                    )
                )
            async with engine.begin() as connection:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                report = await connection.run_sync(inspect_teacher_ids)
                assert report.column_type == "uuid"
                assert report.legacy_ids == frozenset()
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_inventory_rejects_malformed_snapshot_identity(
    teacher_uuid_legacy_database_url,
):
    from schedule_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
        inspect_teacher_ids,
    )

    async def run():
        engine = create_async_engine(
            teacher_uuid_legacy_database_url, poolclass=NullPool
        )
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO outbox_events(event_type,payload) VALUES "
                        "('lesson.snapshot',CAST(:payload AS jsonb))"
                    ),
                    {"payload": json.dumps({"teacher_id": True})},
                )
                with pytest.raises(TeacherIdMigrationError):
                    await connection.run_sync(inspect_teacher_ids)
        finally:
            await engine.dispose()

    asyncio.run(run())
