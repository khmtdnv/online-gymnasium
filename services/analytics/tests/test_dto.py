from uuid import UUID

"""Проверяет снимки уроков независимо от Kafka-парсера."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from analytics_service.application.snapshot import LessonSnapshot


def snapshot_values():
    start = datetime(2026, 10, 14, 10, tzinfo=UTC)
    return {
        "event_id": 1,
        "occurred_at": start,
        "lesson_id": 2,
        "class_id": 3,
        "teacher_id": UUID(int=4),
        "subject_id": 5,
        "starts_at": start,
        "ends_at": start + timedelta(hours=1),
        "status": "planned",
        "version": 1,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", True),
        ("lesson_id", 0),
        ("class_id", "1"),
        ("version", -1),
        ("status", "unknown"),
        ("starts_at", datetime(2026, 10, 14, 10, tzinfo=UTC).replace(tzinfo=None)),
        ("occurred_at", datetime(2026, 10, 14, 10, tzinfo=UTC).replace(tzinfo=None)),
    ],
)
def test_snapshot_rejects_invalid_field(field, value):
    values = snapshot_values()
    values[field] = value
    with pytest.raises(ValidationError):
        LessonSnapshot(**values)


def test_snapshot_rejects_reversed_interval():
    values = snapshot_values()
    values["ends_at"] = values["starts_at"]
    with pytest.raises(ValidationError):
        LessonSnapshot(**values)


def test_snapshot_is_frozen():
    snapshot = LessonSnapshot(**snapshot_values())
    with pytest.raises(ValidationError):
        snapshot.version = 2


def test_workload_rejects_datetime_as_day():
    from analytics_service.application.workload import ClassDailyWorkload

    values = {
        "class_id": 1,
        "planned_lessons_count": 0,
        "planned_minutes": 0,
        "refreshed_at": datetime(2026, 10, 14, tzinfo=UTC),
    }
    with pytest.raises(ValidationError):
        ClassDailyWorkload(day=datetime(2026, 10, 14, tzinfo=UTC), **values)


def test_workload_rejects_naive_refresh_time():
    from datetime import date

    from analytics_service.application.workload import ClassDailyWorkload

    with pytest.raises(ValidationError):
        ClassDailyWorkload(
            class_id=1,
            day=date(2026, 10, 14),
            planned_lessons_count=0,
            planned_minutes=0,
            refreshed_at=datetime(2026, 10, 14, tzinfo=UTC).replace(tzinfo=None),
        )
