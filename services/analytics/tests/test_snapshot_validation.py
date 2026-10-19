"""Проверяет внешние события до записи в ClickHouse."""

import pytest
from test_snapshot import lesson_snapshot_envelope

from analytics_service.application.snapshot import parse_lesson_snapshot


@pytest.mark.parametrize(
    "field",
    ["event_id", "lesson_id", "class_id", "teacher_id", "subject_id", "version"],
)
@pytest.mark.parametrize("value", [0, -1, True, "1", None])
def test_rejects_invalid_snapshot_integer(field, value):
    envelope = lesson_snapshot_envelope()
    target = envelope if field == "event_id" else envelope["payload"]
    target[field] = value
    with pytest.raises((ValueError, TypeError)):
        parse_lesson_snapshot(envelope)


@pytest.mark.parametrize(
    "envelope", [None, [], 1, {}, {"event_type": None}, {"event_type": []}]
)
def test_rejects_invalid_envelope(envelope):
    with pytest.raises((ValueError, TypeError)):
        parse_lesson_snapshot(envelope)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "unknown"),
        ("status", []),
        ("starts_at", "2026-09-20T10:00:00"),
        ("ends_at", "2026-09-20T11:30:00"),
        ("starts_at", "2026-09-20T11:30:00Z"),
        ("ends_at", "2026-09-20T09:00:00Z"),
    ],
)
def test_rejects_invalid_snapshot_period_or_status(field, value):
    envelope = lesson_snapshot_envelope()
    envelope["payload"][field] = value
    with pytest.raises((ValueError, TypeError)):
        parse_lesson_snapshot(envelope)


def test_rejects_naive_occurrence_time():
    envelope = lesson_snapshot_envelope()
    envelope["occurred_at"] = "2026-09-19T10:00:00"
    with pytest.raises(ValueError):
        parse_lesson_snapshot(envelope)


@pytest.mark.parametrize("status", ["planned", "canceled"])
def test_accepts_known_status_and_offsets(status):
    envelope = lesson_snapshot_envelope()
    envelope["payload"].update(status=status, ends_at="2026-09-20T14:30:00+03:00")
    snapshot = parse_lesson_snapshot(envelope)
    assert snapshot.status == status
    assert (snapshot.ends_at - snapshot.starts_at).total_seconds() == 5400
