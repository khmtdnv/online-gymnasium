"""Не позволяет принять числовой legacy snapshot за новый UUID-контракт."""

from uuid import UUID

import pytest


@pytest.mark.parametrize("version", [None, 1, True, 2.0, 3])
def test_snapshot_refuses_wrong_schema_version(version):
    from test_snapshot import lesson_snapshot_envelope

    from analytics_service.application.snapshot import parse_lesson_snapshot

    envelope = lesson_snapshot_envelope()
    envelope["schema_version"] = version
    with pytest.raises(ValueError):
        parse_lesson_snapshot(envelope)


def test_snapshot_v2_returns_same_teacher_uuid():
    from test_snapshot import lesson_snapshot_envelope

    from analytics_service.application.snapshot import parse_lesson_snapshot

    envelope = lesson_snapshot_envelope()
    envelope["schema_version"] = 2
    envelope["payload"]["teacher_id"] = "8df96b7a-7d30-44e7-b577-f6581300e101"
    assert parse_lesson_snapshot(envelope).teacher_id == UUID(
        "8df96b7a-7d30-44e7-b577-f6581300e101"
    )
