from uuid import UUID

"""Проверяет отклонение неверных данных до обращения к хранилищам."""

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from schedule_service.application.cancel_lesson import (
    CancelLessonCommand,
    CancelLessonHandler,
)
from schedule_service.application.create_lesson import (
    CreateLessonCommand,
    CreateLessonHandler,
)
from schedule_service.application.list_lessons import (
    ListLessonsHandler,
    ListLessonsQuery,
)
from schedule_service.application.update_lesson import (
    UpdateLessonCommand,
    UpdateLessonHandler,
)
from schedule_service.domain.lesson import InvalidLessonInterval, Lesson


class UnknownOffset(tzinfo):
    """Представляет пояс без известного смещения."""

    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize("zone", [None, UnknownOffset()])
@pytest.mark.parametrize("field", ["starts_at", "ends_at"])
def test_lesson_rejects_unknown_time_offset(zone, field):
    values = {
        "class_id": 1,
        "teacher_id": UUID(int=2),
        "subject_id": 3,
        "starts_at": datetime(2026, 10, 12, 10, tzinfo=UTC),
        "ends_at": datetime(2026, 10, 12, 11, tzinfo=UTC),
    }
    values[field] = values[field].replace(tzinfo=zone)
    with pytest.raises(InvalidLessonInterval):
        Lesson.create(**values)


def test_reschedule_rejects_naive_time_without_changing_lesson():
    start = datetime(2026, 10, 12, 10, tzinfo=UTC)
    end = datetime(2026, 10, 12, 11, tzinfo=UTC)
    lesson = Lesson.create(1, UUID(int=2), 3, start, end)
    with pytest.raises(InvalidLessonInterval):
        lesson.reschedule(start.replace(tzinfo=None), end.replace(tzinfo=None))
    assert (lesson.starts_at, lesson.ends_at) == (start, end)


def test_lesson_accepts_different_known_offsets():
    lesson = Lesson.create(
        1,
        UUID(int=2),
        3,
        datetime(2026, 10, 12, 10, tzinfo=UTC),
        datetime(2026, 10, 12, 14, tzinfo=timezone(timedelta(hours=3))),
    )
    assert lesson.ends_at - lesson.starts_at == timedelta(hours=1)


@pytest.mark.parametrize("scenario", ["create", "update"])
@pytest.mark.parametrize("field", ["starts_at", "ends_at"])
def test_handler_rejects_naive_time_before_uow(scenario, field):
    """Отклоняет неверное время независимо от наличия HTTP-валидации."""
    factory = Mock()
    data = {
        "starts_at": datetime(2026, 10, 12, 10, tzinfo=UTC),
        "ends_at": datetime(2026, 10, 12, 11, tzinfo=UTC),
    }
    data[field] = data[field].replace(tzinfo=None)
    if scenario == "create":
        constructor = CreateLessonCommand
        data.update(class_id=1, teacher_id=UUID(int=2), subject_id=3)
        handler = CreateLessonHandler(factory)
    else:
        constructor = UpdateLessonCommand
        data.update(lesson_id=1, expected_version=1)
        handler = UpdateLessonHandler(factory)
    with pytest.raises(ValidationError):
        asyncio.run(handler.handle(constructor(**data)))
    factory.assert_not_called()


@pytest.mark.parametrize("method,path", [("POST", "/lessons"), ("PATCH", "/lessons/1")])
@pytest.mark.parametrize("field", ["starts_at", "ends_at"])
def test_http_rejects_naive_time_without_uow(method, path, field):
    """Возвращает 422 за время без пояса, не вызывая запись в БД."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from schedule_service.api.lessons import router

    app = FastAPI()
    app.include_router(router)
    app.state.uow_factory = factory = Mock()
    body = {
        "starts_at": "2026-10-12T10:00:00Z",
        "ends_at": "2026-10-12T11:00:00Z",
    }
    body[field] = body[field].removesuffix("Z")
    if method == "POST":
        body.update(class_id=1, teacher_id=str(UUID(int=2)), subject_id=3)
    else:
        body["expected_version"] = 1
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 422
    factory.assert_not_called()


@pytest.mark.parametrize("value", [0, -1, True])
@pytest.mark.parametrize(
    "scenario,field",
    [
        ("create", "class_id"),
        ("create", "teacher_id"),
        ("create", "subject_id"),
        ("update", "lesson_id"),
        ("update", "expected_version"),
        ("cancel", "lesson_id"),
        ("cancel", "expected_version"),
        ("list", "class_id"),
    ],
)
def test_invalid_identifiers_fail_before_uow_or_cache(scenario, field, value):

    factory, cache = Mock(), Mock()
    start = datetime(2026, 10, 12, 10, tzinfo=UTC)
    end = datetime(2026, 10, 12, 11, tzinfo=UTC)
    if scenario == "create":
        values = {
            "class_id": 1,
            "teacher_id": str(UUID(int=2)),
            "subject_id": 3,
            "starts_at": start,
            "ends_at": end,
        }
        values[field] = value
        constructor, handler = CreateLessonCommand, CreateLessonHandler(factory)
    elif scenario == "update":
        values = {
            "lesson_id": 1,
            "expected_version": 1,
            "starts_at": start,
            "ends_at": end,
        }
        values[field] = value
        constructor, handler = UpdateLessonCommand, UpdateLessonHandler(factory)
    elif scenario == "cancel":
        values = {"lesson_id": 1, "expected_version": 1}
        values[field] = value
        constructor, handler = CancelLessonCommand, CancelLessonHandler(factory)
    else:
        constructor = ListLessonsQuery
        values = {"class_id": value, "day": date(2026, 10, 12)}
        handler = ListLessonsHandler(factory, cache, 60, 1000, 1, 1)
    with pytest.raises(ValidationError):
        asyncio.run(handler.handle(constructor(**values)))
    factory.assert_not_called()
    assert cache.mock_calls == []


@pytest.mark.parametrize(
    "method,path,body",
    [
        (
            "POST",
            "/lessons",
            {
                "class_id": 0,
                "teacher_id": str(UUID(int=1)),
                "subject_id": 1,
                "starts_at": "2026-10-12T10:00:00Z",
                "ends_at": "2026-10-12T11:00:00Z",
            },
        ),
        (
            "POST",
            "/lessons",
            {
                "class_id": True,
                "teacher_id": str(UUID(int=1)),
                "subject_id": 1,
                "starts_at": "2026-10-12T10:00:00Z",
                "ends_at": "2026-10-12T11:00:00Z",
            },
        ),
        (
            "PATCH",
            "/lessons/0",
            {
                "expected_version": 1,
                "starts_at": "2026-10-12T10:00:00Z",
                "ends_at": "2026-10-12T11:00:00Z",
            },
        ),
        (
            "PATCH",
            "/lessons/1",
            {
                "expected_version": 0,
                "starts_at": "2026-10-12T10:00:00Z",
                "ends_at": "2026-10-12T11:00:00Z",
            },
        ),
        ("POST", "/lessons/1/cancel", {"expected_version": 0}),
        ("GET", "/lessons?class_id=0&date=2026-10-12", None),
    ],
)
def test_schedule_http_rejects_invalid_ids_without_dependencies(method, path, body):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from schedule_service.api.lessons import router

    app = FastAPI()
    app.include_router(router)
    factory = Mock()
    app.state.uow_factory = factory
    app.state.schedule_cache = Mock()
    app.state.settings = Mock()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 422
    factory.assert_not_called()
