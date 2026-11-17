"""Перенос реальных ClickHouse-снимков не теряет историю и допускает повтор."""

from datetime import UTC, datetime
from uuid import UUID

import pytest


def seed(client):
    client.insert(
        "lesson_snapshots",
        [
            [
                42,
                datetime(2026, 10, 16, tzinfo=UTC),
                501,
                7,
                99,
                1,
                datetime(2026, 10, 19, 10, tzinfo=UTC),
                datetime(2026, 10, 19, 11, tzinfo=UTC),
                "planned",
                1,
            ]
        ],
        column_names=[
            "event_id",
            "occurred_at",
            "lesson_id",
            "class_id",
            "teacher_id",
            "subject_id",
            "starts_at",
            "ends_at",
            "status",
            "version",
        ],
    )


def test_missing_historical_mapping_writes_nothing(legacy_clickhouse):
    from analytics_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
        migrate_teacher_ids,
    )

    seed(legacy_clickhouse)
    with pytest.raises(TeacherIdMigrationError, match="99"):
        migrate_teacher_ids(legacy_clickhouse, {})
    assert legacy_clickhouse.command("EXISTS TABLE lesson_snapshots_v2") == 0
    assert legacy_clickhouse.command("SELECT count() FROM lesson_snapshots") == 1


def test_repeated_backfill_preserves_uuid_history_and_workload(legacy_clickhouse):
    from analytics_service.infrastructure.teacher_id_migration import (
        migrate_teacher_ids,
    )

    seed(legacy_clickhouse)
    mapping = {99: UUID("8df96b7a-7d30-44e7-b577-f6581300e199")}
    assert migrate_teacher_ids(legacy_clickhouse, mapping) == 1
    assert migrate_teacher_ids(legacy_clickhouse, mapping) == 0
    assert legacy_clickhouse.command("SELECT count() FROM lesson_snapshots") == 1
    assert legacy_clickhouse.query(
        "SELECT event_id,lesson_id,teacher_id FROM lesson_snapshots_v2"
    ).result_rows == [(42, 501, mapping[99])]
    assert (
        legacy_clickhouse.query(
            "SELECT occurred_at,starts_at,ends_at FROM lesson_snapshots_v2"
        ).result_rows
        == legacy_clickhouse.query(
            "SELECT occurred_at,starts_at,ends_at FROM lesson_snapshots"
        ).result_rows
    )
    legacy_clickhouse.command("SYSTEM REFRESH VIEW class_daily_workload_v2_mv")
    legacy_clickhouse.command("SYSTEM WAIT VIEW class_daily_workload_v2_mv")
    assert legacy_clickhouse.query(
        "SELECT class_id,planned_lessons_count,planned_minutes FROM class_daily_workload_v2"
    ).result_rows == [(7, 1, 60)]


def test_check_only_does_not_create_target(legacy_clickhouse):
    from analytics_service.infrastructure.teacher_id_migration import (
        migrate_teacher_ids,
    )

    seed(legacy_clickhouse)
    assert (
        migrate_teacher_ids(legacy_clickhouse, {99: UUID(int=99)}, check_only=True) == 1
    )
    assert legacy_clickhouse.command("EXISTS TABLE lesson_snapshots_v2") == 0


def test_duplicate_legacy_rows_are_preserved_without_retry_growth(legacy_clickhouse):
    from analytics_service.infrastructure.teacher_id_migration import (
        migrate_teacher_ids,
    )

    seed(legacy_clickhouse)
    seed(legacy_clickhouse)
    assert migrate_teacher_ids(legacy_clickhouse, {99: UUID(int=99)}) == 2
    assert migrate_teacher_ids(legacy_clickhouse, {99: UUID(int=99)}) == 0
    assert legacy_clickhouse.command("SELECT count() FROM lesson_snapshots_v2") == 2


@pytest.mark.parametrize(
    "raw",
    [
        '{"1":"00000000-0000-0000-0000-000000000001","1":"00000000-0000-0000-0000-000000000002"}',
        '{"1":"00000000-0000-0000-0000-000000000001","2":"00000000-0000-0000-0000-000000000001"}',
        '{"2147483648":"00000000-0000-0000-0000-000000000001"}',
    ],
)
def test_mapping_rejects_ambiguous_or_out_of_range_ids(tmp_path, raw):
    from analytics_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
        load_teacher_id_mapping,
    )

    path = tmp_path / "mapping.json"
    path.write_text(raw)
    with pytest.raises(TeacherIdMigrationError):
        load_teacher_id_mapping(path)
