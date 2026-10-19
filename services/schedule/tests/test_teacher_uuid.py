"""Общий UUID проходит HTTP, домен, кеш и outbox без подмены идентичности."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

TEACHER = UUID("8df96b7a-7d30-44e7-b577-f6581300e101")


def test_http_teacher_uuid_becomes_domain_uuid_and_json_string():
    from schedule_service.api.lessons import CreateLessonRequest, LessonResponse

    request = CreateLessonRequest.model_validate_json(
        '{"class_id":7,"teacher_id":"8df96b7a-7d30-44e7-b577-f6581300e101",'
        '"subject_id":1,"starts_at":"2026-10-19T10:00:00Z","ends_at":"2026-10-19T11:00:00Z"}'
    )
    assert request.teacher_id == TEACHER
    response = LessonResponse(
        id=501, **request.model_dump(), status="planned", version=1
    )
    assert response.model_dump(mode="json")["teacher_id"] == str(TEACHER)
    assert response.id == 501


@pytest.mark.parametrize("teacher_id", [42, True, "not-a-uuid"])
def test_domain_refuses_non_uuid_teacher(teacher_id):
    from schedule_service.domain.lesson import Lesson

    with pytest.raises(ValueError):
        Lesson.create(
            class_id=7,
            teacher_id=teacher_id,
            subject_id=1,
            starts_at=datetime(2026, 10, 19, 10, tzinfo=UTC),
            ends_at=datetime(2026, 10, 19, 11, tzinfo=UTC),
        )


def test_cache_uuid_roundtrip_uses_separate_namespace():
    from schedule_service.domain.lesson import Lesson
    from schedule_service.infrastructure.redis_schedule_cache import RedisScheduleCache

    lesson = Lesson.create(
        class_id=7,
        teacher_id=TEACHER,
        subject_id=1,
        starts_at=datetime(2026, 10, 19, 10, tzinfo=UTC),
        ends_at=datetime(2026, 10, 19, 11, tzinfo=UTC),
    )
    payload = RedisScheduleCache._serialize([lesson])
    assert str(TEACHER) in payload
    assert RedisScheduleCache._deserialize(payload)[0].teacher_id == TEACHER
    assert (
        RedisScheduleCache(None)
        ._key(class_id=7, day=lesson.starts_at.date())
        .startswith("schedule:v2:")
    )
