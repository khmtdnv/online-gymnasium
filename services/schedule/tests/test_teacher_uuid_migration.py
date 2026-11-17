"""Реальная старая схема: перенос ID не должен менять уроки, ключи и события."""

import asyncio
import json
from uuid import UUID

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

TEACHER_A = UUID("8df96b7a-7d30-44e7-b577-f6581300e101")
TEACHER_B = UUID("8df96b7a-7d30-44e7-b577-f6581300e102")
HISTORICAL = UUID("8df96b7a-7d30-44e7-b577-f6581300e199")
MAPPING = {42: TEACHER_A, 77: TEACHER_B, 99: HISTORICAL}


def test_old_fingerprint_is_not_rebuilt_from_rescheduled_lesson(
    teacher_uuid_legacy_database_url,
):
    """UUID-запрос со старым ключом получает 409 даже после переноса даты урока."""
    from datetime import UTC, datetime

    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from schedule_service.api.lessons import CreateLessonRequest, create_lesson
    from schedule_service.application.create_lesson import CreateLessonHandler
    from schedule_service.infrastructure.teacher_uuid_schema import upgrade_teacher_ids
    from schedule_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    async def scenario(engine):
        async with engine.begin() as connection:
            await seed(connection)
            await connection.execute(
                text(
                    "UPDATE scheduled_lessons SET starts_at=starts_at+interval '1 day',ends_at=ends_at+interval '1 day' WHERE id=501"
                )
            )
            await connection.run_sync(upgrade_teacher_ids, MAPPING)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        handler = CreateLessonHandler(lambda: SqlAlchemyUnitOfWork(sessions))
        with pytest.raises(HTTPException) as error:
            await create_lesson(
                CreateLessonRequest(
                    class_id=7,
                    teacher_id=TEACHER_A,
                    subject_id=1,
                    starts_at=datetime(2026, 10, 19, 10, tzinfo=UTC),
                    ends_at=datetime(2026, 10, 19, 11, tzinfo=UTC),
                ),
                handler,
                "original-key",
            )
        assert error.value.status_code == 409
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT count(*) FROM scheduled_lessons"))
                == 2
            )
            assert (
                await connection.scalar(
                    text("SELECT request_hash FROM idempotency_requests")
                )
                == "original-request-hash"
            )

    execute_case(teacher_uuid_legacy_database_url, scenario)


def test_downgrade_restores_explicit_legacy_ids(teacher_uuid_legacy_database_url):
    from schedule_service.infrastructure.teacher_uuid_schema import (
        downgrade_teacher_ids,
        upgrade_teacher_ids,
    )

    async def scenario(engine):
        async with engine.begin() as connection:
            await seed(connection)
            await connection.run_sync(upgrade_teacher_ids, MAPPING)
        async with engine.begin() as connection:
            await connection.run_sync(downgrade_teacher_ids, MAPPING)
            assert list(
                await connection.scalars(
                    text("SELECT teacher_id FROM scheduled_lessons ORDER BY id")
                )
            ) == [42, 77]
            assert (await connection.scalar(text("SELECT payload FROM outbox_events")))[
                "teacher_id"
            ] == 99

    execute_case(teacher_uuid_legacy_database_url, scenario)


@pytest.mark.parametrize("provide_mapping", [False, True])
def test_registered_revision_requires_mapping_and_preserves_rows(
    teacher_uuid_legacy_database_url, tmp_path, monkeypatch, provide_mapping
):
    from alembic import command
    from alembic.config import Config

    from schedule_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
    )

    async def populate(engine):
        async with engine.begin() as connection:
            await seed(connection)

    execute_case(teacher_uuid_legacy_database_url, populate)
    monkeypatch.setenv("DATABASE_URL", teacher_uuid_legacy_database_url)
    monkeypatch.delenv("SCHEDULE_TEACHER_ID_MAP_FILE", raising=False)
    if provide_mapping:
        mapping_file = tmp_path / "mapping.json"
        mapping_file.write_text(
            json.dumps({str(k): str(v) for k, v in MAPPING.items()})
        )
        monkeypatch.setenv("SCHEDULE_TEACHER_ID_MAP_FILE", str(mapping_file))
        command.upgrade(Config("alembic.ini"), "d7a8046e2b91")
    else:
        with pytest.raises(TeacherIdMigrationError):
            command.upgrade(Config("alembic.ini"), "d7a8046e2b91")

    async def verify(engine):
        async with engine.connect() as connection:
            assert await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == ("d7a8046e2b91" if provide_mapping else "c9c13a8d994d")
            assert list(
                await connection.scalars(
                    text("SELECT teacher_id FROM scheduled_lessons ORDER BY id")
                )
            ) == ([TEACHER_A, TEACHER_B] if provide_mapping else [42, 77])

    execute_case(teacher_uuid_legacy_database_url, verify)


def test_downgrade_unknown_uuid_stops_before_schema_write(
    teacher_uuid_legacy_database_url,
):
    from schedule_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
    )
    from schedule_service.infrastructure.teacher_uuid_schema import (
        downgrade_teacher_ids,
        upgrade_teacher_ids,
    )

    async def scenario(engine):
        async with engine.begin() as connection:
            await seed(connection)
            await connection.run_sync(upgrade_teacher_ids, MAPPING)
        with pytest.raises(TeacherIdMigrationError):
            async with engine.begin() as connection:
                await connection.run_sync(downgrade_teacher_ids, {42: TEACHER_A})
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT teacher_id FROM scheduled_lessons WHERE id=502")
                )
                == TEACHER_B
            )

    execute_case(teacher_uuid_legacy_database_url, scenario)


async def seed(connection):
    await connection.execute(
        text(
            "INSERT INTO scheduled_lessons "
            "(id,class_id,teacher_id,subject_id,starts_at,ends_at,version) VALUES "
            "(501,7,42,1,'2026-10-19 10:00+00','2026-10-19 11:00+00',4),"
            "(502,8,77,1,'2026-10-19 10:00+00','2026-10-19 11:00+00',1)"
        )
    )
    await connection.execute(
        text(
            "INSERT INTO idempotency_requests(operation,idempotency_key,request_hash,lesson_id) "
            "VALUES ('create_lesson','original-key','original-request-hash',501)"
        )
    )
    payload = {
        "lesson_id": 499,
        "class_id": 6,
        "teacher_id": 99,
        "subject_id": 1,
        "starts_at": "2026-10-18T10:00:00+00:00",
        "ends_at": "2026-10-18T11:00:00+00:00",
        "status": "planned",
        "version": 1,
    }
    await connection.execute(
        text(
            "INSERT INTO outbox_events(id,event_type,payload,published_at) VALUES "
            "(601,'lesson.snapshot',CAST(:payload AS jsonb),now())"
        ),
        {"payload": json.dumps(payload)},
    )


def execute_case(url, operation):
    async def run():
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            await operation(engine)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_missing_historical_teacher_stops_before_schema_write(
    teacher_uuid_legacy_database_url,
):
    from schedule_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
    )
    from schedule_service.infrastructure.teacher_uuid_schema import upgrade_teacher_ids

    async def scenario(engine):
        async with engine.begin() as connection:
            await seed(connection)
        with pytest.raises(TeacherIdMigrationError, match="99"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    upgrade_teacher_ids, {42: TEACHER_A, 77: TEACHER_B}
                )
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda bind: inspect(bind).get_columns("scheduled_lessons")
            )
            assert "teacher_id_uuid" not in {item["name"] for item in columns}
            assert (
                await connection.scalar(
                    text("SELECT teacher_id FROM scheduled_lessons WHERE id=501")
                )
                == 42
            )

    execute_case(teacher_uuid_legacy_database_url, scenario)


def test_empty_upgrade_has_uuid_column_and_overlap_constraint(
    teacher_uuid_legacy_database_url,
):
    from schedule_service.infrastructure.teacher_uuid_schema import upgrade_teacher_ids

    async def scenario(engine):
        async with engine.begin() as connection:
            await connection.run_sync(upgrade_teacher_ids, {})
            assert (
                await connection.scalar(
                    text(
                        "SELECT data_type FROM information_schema.columns WHERE table_name='scheduled_lessons' AND column_name='teacher_id'"
                    )
                )
                == "uuid"
            )
            await connection.execute(
                text(
                    "INSERT INTO scheduled_lessons(id,class_id,teacher_id,subject_id,starts_at,ends_at) VALUES (501,7,CAST(:teacher AS uuid),1,'2026-10-19 10:00+00','2026-10-19 11:00+00')"
                ),
                {"teacher": str(TEACHER_A)},
            )
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO scheduled_lessons(id,class_id,teacher_id,subject_id,starts_at,ends_at) VALUES (502,8,CAST(:teacher AS uuid),1,'2026-10-19 10:00+00','2026-10-19 11:00+00')"
                    ),
                    {"teacher": str(TEACHER_A)},
                )

    execute_case(teacher_uuid_legacy_database_url, scenario)


def test_invalid_backfill_rolls_back_schema_and_data(
    teacher_uuid_legacy_database_url, monkeypatch
):
    from schedule_service.infrastructure import teacher_uuid_schema
    from schedule_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
    )

    # Ошибка учебного тела: случайно назначен один учитель всем урокам.
    def wrong_backfill(bind, mapping):
        bind.execute(
            text("UPDATE scheduled_lessons SET teacher_id_uuid=CAST(:wrong AS uuid)"),
            {"wrong": str(TEACHER_A)},
        )

    monkeypatch.setattr(
        teacher_uuid_schema, "backfill_lesson_teacher_ids", wrong_backfill
    )

    async def scenario(engine):
        async with engine.begin() as connection:
            await seed(connection)
        with pytest.raises(TeacherIdMigrationError, match="backfill"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    teacher_uuid_schema.upgrade_teacher_ids, MAPPING
                )
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda bind: inspect(bind).get_columns("scheduled_lessons")
            )
            assert "teacher_id_uuid" not in {item["name"] for item in columns}
            assert list(
                await connection.scalars(
                    text("SELECT teacher_id FROM scheduled_lessons ORDER BY id")
                )
            ) == [42, 77]

    execute_case(teacher_uuid_legacy_database_url, scenario)


def test_upgrade_preserves_lesson_ids_hashes_and_historical_events(
    teacher_uuid_legacy_database_url,
):
    from schedule_service.infrastructure.teacher_uuid_schema import upgrade_teacher_ids

    async def scenario(engine):
        async with engine.begin() as connection:
            await seed(connection)
        async with engine.begin() as connection:
            await connection.run_sync(upgrade_teacher_ids, MAPPING)
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT id,teacher_id,class_id,version FROM scheduled_lessons ORDER BY id"
                    )
                )
            ).all()
            assert rows == [(501, TEACHER_A, 7, 4), (502, TEACHER_B, 8, 1)]
            assert (
                await connection.execute(
                    text(
                        "SELECT idempotency_key,request_hash,lesson_id FROM idempotency_requests"
                    )
                )
            ).one() == ("original-key", "original-request-hash", 501)
            snapshot = (
                await connection.execute(
                    text("SELECT id,payload,published_at FROM outbox_events")
                )
            ).one()
            assert snapshot.id == 601
            assert snapshot.payload["teacher_id"] == str(HISTORICAL)
            assert snapshot.payload["lesson_id"] == 499
            assert snapshot.published_at is not None

    execute_case(teacher_uuid_legacy_database_url, scenario)


def test_learner_backfill_changes_only_staging_column(teacher_uuid_legacy_database_url):
    from schedule_service.infrastructure.teacher_id_backfill import (
        backfill_lesson_teacher_ids,
    )

    async def scenario(engine):
        async with engine.begin() as connection:
            await seed(connection)
            await connection.execute(
                text("ALTER TABLE scheduled_lessons ADD COLUMN teacher_id_uuid uuid")
            )
            await connection.run_sync(backfill_lesson_teacher_ids, MAPPING)
            rows = (
                await connection.execute(
                    text(
                        "SELECT id,teacher_id,teacher_id_uuid,version FROM scheduled_lessons ORDER BY id"
                    )
                )
            ).all()
            assert rows == [(501, 42, TEACHER_A, 4), (502, 77, TEACHER_B, 1)]
            assert (
                await connection.scalar(text("SELECT count(*) FROM scheduled_lessons"))
                == 2
            )

    execute_case(teacher_uuid_legacy_database_url, scenario)


def test_outbox_only_teacher_is_converted_without_touching_event_metadata(
    teacher_uuid_legacy_database_url,
):
    from schedule_service.infrastructure.teacher_uuid_schema import upgrade_teacher_ids

    async def scenario(engine):
        async with engine.begin() as connection:
            await seed(connection)
            await connection.execute(text("DELETE FROM idempotency_requests"))
            await connection.execute(text("DELETE FROM scheduled_lessons"))
            original = (
                await connection.execute(
                    text("SELECT id,payload,created_at,published_at FROM outbox_events")
                )
            ).one()
            await connection.run_sync(upgrade_teacher_ids, {99: HISTORICAL})
            converted = (
                await connection.execute(
                    text("SELECT id,payload,created_at,published_at FROM outbox_events")
                )
            ).one()
            assert converted.id == original.id
            assert converted.created_at == original.created_at
            assert converted.published_at == original.published_at
            assert converted.payload == {
                **original.payload,
                "teacher_id": str(HISTORICAL),
            }

    execute_case(teacher_uuid_legacy_database_url, scenario)
