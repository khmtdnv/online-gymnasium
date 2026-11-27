from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self
from unittest.mock import Mock
from uuid import UUID

import pytest
from conftest import NoopScheduleCache
from fastapi.testclient import TestClient

from schedule_service.app import create_app as create_production_app
from schedule_service.application.errors import ScheduleConflict
from schedule_service.config import Settings
from schedule_service.domain.lesson import Lesson
from schedule_service.infrastructure.database import create_engine


def create_app(settings: Settings, engine, uow_factory):
    return create_production_app(
        settings,
        engine,
        uow_factory,
        NoopScheduleCache(),
    )


@dataclass
class FakeIdempotencyRecord:
    request_hash: str
    lesson: Lesson | None = None


class FakeIdempotencyRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], FakeIdempotencyRecord] = {}

    async def claim(self, operation: str, key: str, request_hash: str) -> None:
        from schedule_service.application.errors import IdempotencyKeyAlreadyExists

        record = self.records.get((operation, key))

        if record is None:
            self.records[(operation, key)] = FakeIdempotencyRecord(
                request_hash=request_hash
            )
            return

        raise IdempotencyKeyAlreadyExists

    async def get_by_key(
        self, operation: str, key: str
    ) -> FakeIdempotencyRecord | None:
        return self.records.get((operation, key))

    async def complete(self, operation: str, key: str, lesson: Lesson) -> None:
        record = self.records.get((operation, key))
        assert record is not None
        record.lesson = lesson


class FakeLessonRepository:
    def __init__(self) -> None:
        self.add_calls = 0
        self.saved: Lesson | None = None

    async def add(self, lesson: Lesson) -> Lesson:
        self.add_calls += 1
        self.saved = lesson

        return Lesson(
            id=501,
            class_id=lesson.class_id,
            teacher_id=lesson.teacher_id,
            subject_id=lesson.subject_id,
            starts_at=lesson.starts_at,
            ends_at=lesson.ends_at,
            status=lesson.status,
            version=lesson.version,
        )


class FakeOutboxRepository:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def add(self, event: object) -> None:
        self.events.append(event)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.lessons = FakeLessonRepository()
        self.idempotency = FakeIdempotencyRepository()
        self.outbox = FakeOutboxRepository()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class UpdatingLessonRepository:
    async def get(self, lesson_id: int) -> Lesson | None:
        if lesson_id != 501:
            return None

        return Lesson(
            id=501,
            class_id=10,
            teacher_id=UUID(int=100),
            subject_id=1000,
            starts_at=datetime(2026, 9, 10, 10, tzinfo=UTC),
            ends_at=datetime(2026, 9, 10, 11, tzinfo=UTC),
            status="planned",
            version=3,
        )

    async def update(self, lesson: Lesson, expected_version: int) -> Lesson | None:
        return Lesson(
            id=lesson.id,
            class_id=lesson.class_id,
            teacher_id=lesson.teacher_id,
            subject_id=lesson.subject_id,
            starts_at=lesson.starts_at,
            ends_at=lesson.ends_at,
            status=lesson.status,
            version=4,
        )


class StaleVersionLessonRepository(UpdatingLessonRepository):
    async def update(self, lesson: Lesson, expected_version: int) -> Lesson | None:
        return None


class ConflictingUpdateLessonRepository(UpdatingLessonRepository):
    async def update(self, lesson: Lesson, expected_version: int) -> Lesson | None:
        raise ScheduleConflict


class CancelingLessonRepository:
    async def get(self, lesson_id: int) -> Lesson | None:
        if lesson_id != 501:
            return None
        return Lesson(
            id=501,
            class_id=10,
            teacher_id=UUID(int=100),
            subject_id=1000,
            starts_at=datetime(2026, 9, 10, 10, tzinfo=UTC),
            ends_at=datetime(2026, 9, 10, 11, tzinfo=UTC),
            status="planned",
            version=3,
        )

    async def cancel(self, lesson: Lesson, expected_version: int) -> Lesson | None:
        return Lesson(
            id=lesson.id,
            class_id=lesson.class_id,
            teacher_id=lesson.teacher_id,
            subject_id=lesson.subject_id,
            starts_at=lesson.starts_at,
            ends_at=lesson.ends_at,
            status="canceled",
            version=4,
        )


class StaleCancelingLessonRepository(CancelingLessonRepository):
    async def cancel(self, lesson: Lesson, expected_version: int) -> Lesson | None:
        return None


class AlreadyCanceledLessonRepository(CancelingLessonRepository):
    async def get(self, lesson_id: int) -> Lesson | None:
        lesson = await super().get(lesson_id)
        if lesson is not None:
            lesson.status = "canceled"
        return lesson


def test_create_lesson_endpoint() -> None:
    test_app_name = "Test Schedule Service"
    test_settings = Settings(
        app_name=test_app_name,
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    test_engine = create_engine(url=test_settings.database_url)
    fake_uow = FakeUnitOfWork()
    test_app = create_app(test_settings, test_engine, lambda: fake_uow)

    with TestClient(test_app) as test_client:
        request_body = {
            "class_id": 10,
            "teacher_id": str(UUID(int=100)),
            "subject_id": 1000,
            "starts_at": "2026-09-08T04:00:00Z",
            "ends_at": "2026-09-08T04:45:00Z",
        }
        response = test_client.post("/lessons", json=request_body)

        assert response.status_code == 201

        response_body = response.json()
        assert response_body["id"] == 501
        assert response_body["status"] == "planned"
        assert response_body["version"] == 1

    assert fake_uow.lessons.saved is not None
    assert fake_uow.lessons.saved.class_id == 10


@pytest.mark.parametrize(
    "starts_at,ends_at",
    [
        ("2026-09-08T04:00:00Z", "2026-09-08T04:45:00Z"),
        ("2026-09-08T04:55:00Z", "2026-09-08T05:40:00Z"),
        ("2026-09-08T06:00:00Z", "2026-09-08T06:45:00Z"),
        ("2026-09-08T06:55:00Z", "2026-09-08T07:40:00Z"),
        ("2026-09-08T08:00:00Z", "2026-09-08T08:45:00Z"),
        ("2026-09-08T08:55:00Z", "2026-09-08T09:40:00Z"),
        ("2026-09-08T10:00:00Z", "2026-09-08T10:45:00Z"),
    ],
)
def test_create_lesson_accepts_all_seven_school_periods(starts_at, ends_at) -> None:
    test_settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    test_engine = create_engine(url=test_settings.database_url)
    fake_uow = FakeUnitOfWork()
    test_app = create_app(test_settings, test_engine, lambda: fake_uow)

    with TestClient(test_app) as test_client:
        request_body = {
            "class_id": 10,
            "teacher_id": str(UUID(int=100)),
            "subject_id": 1000,
            "starts_at": starts_at,
            "ends_at": ends_at,
        }
        response = test_client.post("/lessons", json=request_body)

        assert response.status_code == 201

    assert fake_uow.lessons.saved is not None
    assert fake_uow.lessons.saved.starts_at.isoformat() == starts_at.replace(
        "Z", "+00:00"
    )


@pytest.mark.parametrize(
    "starts_at,ends_at",
    [
        ("2026-09-08T09:01:00+05:00", "2026-09-08T09:46:00+05:00"),
        ("2026-09-08T09:00:00+05:00", "2026-09-08T09:50:00+05:00"),
        ("2026-09-08T10:45:00+05:00", "2026-09-08T11:30:00+05:00"),
        ("2026-09-08T15:10:00+05:00", "2026-09-08T15:55:00+05:00"),
    ],
)
def test_create_lesson_rejects_off_grid_school_times(starts_at, ends_at) -> None:
    """Вне-сеточное локальное время — 422 со строкой detail по конвенции."""
    test_settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    test_engine = create_engine(url=test_settings.database_url)
    fake_uow = FakeUnitOfWork()
    test_app = create_app(test_settings, test_engine, lambda: fake_uow)

    with TestClient(test_app, raise_server_exceptions=False) as test_client:
        request_body = {
            "class_id": 10,
            "teacher_id": str(UUID(int=100)),
            "subject_id": 1000,
            "starts_at": starts_at,
            "ends_at": ends_at,
        }
        response = test_client.post("/lessons", json=request_body)

        assert response.status_code == 422
        assert response.json() == {"detail": "Lesson times must match a school period"}

    assert fake_uow.lessons.saved is None


def test_create_lesson_rejects_interval_in_different_days() -> None:
    test_settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    test_engine = create_engine(url=test_settings.database_url)
    fake_uow = FakeUnitOfWork()
    test_app = create_app(test_settings, test_engine, lambda: fake_uow)

    with TestClient(test_app, raise_server_exceptions=False) as test_client:
        request_body = {
            "class_id": 10,
            "teacher_id": str(UUID(int=100)),
            "subject_id": 1000,
            "starts_at": "2026-09-08T23:00:00Z",
            "ends_at": "2026-09-09T01:00:00Z",
        }
        response = test_client.post("/lessons", json=request_body)

        assert response.status_code == 422
        assert response.json() == {"detail": "starts_at must be before ends_at"}

    assert fake_uow.lessons.saved is None


def test_create_lesson_rejects_non_positive_interval() -> None:
    test_app_name = "Test Schedule Service"
    test_settings = Settings(
        app_name=test_app_name,
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    test_engine = create_engine(url=test_settings.database_url)
    fake_uow = FakeUnitOfWork()
    test_app = create_app(test_settings, test_engine, lambda: fake_uow)

    with TestClient(test_app, raise_server_exceptions=False) as test_client:
        request_body = {
            "class_id": 10,
            "teacher_id": str(UUID(int=100)),
            "subject_id": 1000,
            "starts_at": "2026-09-08T04:00:00Z",
            "ends_at": "2026-09-08T04:00:00Z",
        }
        response = test_client.post("/lessons", json=request_body)

        assert response.status_code == 422
        assert response.json() == {"detail": "starts_at must be before ends_at"}

    assert fake_uow.lessons.saved is None


class ConflictingLessonRepository:
    async def add(self, lesson: Lesson) -> Lesson:
        raise ScheduleConflict


def test_create_lesson_returns_conflict_for_schedule_conflict() -> None:
    test_app_name = "Test Schedule Service"
    test_settings = Settings(
        app_name=test_app_name,
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    test_engine = create_engine(url=test_settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = ConflictingLessonRepository()
    test_app = create_app(test_settings, test_engine, lambda: fake_uow)

    with TestClient(test_app, raise_server_exceptions=False) as test_client:
        request_body = {
            "class_id": 10,
            "teacher_id": str(UUID(int=100)),
            "subject_id": 1000,
            "starts_at": "2026-09-08T04:00:00Z",
            "ends_at": "2026-09-08T04:45:00Z",
        }
        response = test_client.post("/lessons", json=request_body)

        assert response.status_code == 409
        assert response.json() == {
            "detail": "Lesson conflicts with existing schedule",
        }


def test_update_lesson_endpoint() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = UpdatingLessonRepository()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app) as client:
        response = client.patch(
            "/lessons/501",
            json={
                "starts_at": "2026-09-10T06:00:00Z",
                "ends_at": "2026-09-10T06:45:00Z",
                "expected_version": 3,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "id": 501,
        "class_id": 10,
        "teacher_id": str(UUID(int=100)),
        "subject_id": 1000,
        "starts_at": "2026-09-10T06:00:00Z",
        "ends_at": "2026-09-10T06:45:00Z",
        "status": "planned",
        "version": 4,
    }


def test_update_lesson_rejects_non_positive_interval() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = UpdatingLessonRepository()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            "/lessons/501",
            json={
                "starts_at": "2026-09-10T06:00:00Z",
                "ends_at": "2026-09-10T06:00:00Z",
                "expected_version": 3,
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "starts_at must be before ends_at",
    }


def test_cross_day_update_is_rejected_before_lookup_of_missing_lesson() -> None:
    """Неверный интервал получает прежний 422 даже для отсутствующего урока."""
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = UpdatingLessonRepository()
    factory = Mock(return_value=fake_uow)
    app = create_app(settings, engine, factory)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            "/lessons/999",
            json={
                "starts_at": "2026-09-10T23:00:00Z",
                "ends_at": "2026-09-11T01:00:00Z",
                "expected_version": 3,
            },
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "starts_at must be before ends_at"}
    factory.assert_not_called()


def test_update_lesson_returns_not_found_for_missing_lesson() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = UpdatingLessonRepository()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            "/lessons/999",
            json={
                "starts_at": "2026-09-10T06:00:00Z",
                "ends_at": "2026-09-10T06:45:00Z",
                "expected_version": 3,
            },
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Lesson not found"}


def test_update_lesson_returns_conflict_for_stale_version() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = StaleVersionLessonRepository()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            "/lessons/501",
            json={
                "starts_at": "2026-09-10T06:00:00Z",
                "ends_at": "2026-09-10T06:45:00Z",
                "expected_version": 2,
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Lesson version conflict"}


def test_update_lesson_returns_conflict_for_schedule_conflict() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = ConflictingUpdateLessonRepository()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            "/lessons/501",
            json={
                "starts_at": "2026-09-10T06:00:00Z",
                "ends_at": "2026-09-10T06:45:00Z",
                "expected_version": 3,
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Lesson conflicts with existing schedule"}


class RecordingUpdateLessonRepository(UpdatingLessonRepository):
    """Считает вызовы update, чтобы убедиться, что отказ ничего не меняет."""

    def __init__(self) -> None:
        super().__init__()
        self.update_calls = 0

    async def update(self, lesson: Lesson, expected_version: int) -> Lesson | None:
        self.update_calls += 1
        return await super().update(lesson, expected_version)


def test_off_grid_update_is_rejected_and_lesson_stays_unchanged() -> None:
    """Неудачный перенос вне сетки не изменяет сохранённый урок."""
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    repository = RecordingUpdateLessonRepository()
    fake_uow.lessons = repository
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            "/lessons/501",
            json={
                "starts_at": "2026-09-10T05:45:00Z",
                "ends_at": "2026-09-10T06:30:00Z",
                "expected_version": 3,
            },
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Lesson times must match a school period"}
    assert repository.update_calls == 0


def test_cancel_lesson_endpoint() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = CancelingLessonRepository()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app) as client:
        response = client.post("/lessons/501/cancel", json={"expected_version": 3})

    assert response.status_code == 200
    assert response.json() == {
        "id": 501,
        "class_id": 10,
        "teacher_id": str(UUID(int=100)),
        "subject_id": 1000,
        "starts_at": "2026-09-10T10:00:00Z",
        "ends_at": "2026-09-10T11:00:00Z",
        "status": "canceled",
        "version": 4,
    }


def test_cancel_lesson_returns_not_found_for_missing_lesson() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = CancelingLessonRepository()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/lessons/999/cancel", json={"expected_version": 3})

    assert response.status_code == 404
    assert response.json() == {"detail": "Lesson not found"}


def test_cancel_lesson_returns_conflict_for_stale_version() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = StaleCancelingLessonRepository()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/lessons/501/cancel", json={"expected_version": 2})

    assert response.status_code == 409
    assert response.json() == {"detail": "Lesson version conflict"}


def test_cancel_lesson_returns_conflict_when_already_canceled() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    fake_uow.lessons = AlreadyCanceledLessonRepository()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/lessons/501/cancel", json={"expected_version": 3})

    assert response.status_code == 409
    assert response.json() == {"detail": "Lesson is already canceled"}


def test_create_lesson_rejects_reused_idempotency_key_for_different_request() -> None:
    settings = Settings(
        app_name="Test Schedule Service",
        database_url="postgresql+asyncpg://schedule:password@localhost:5432/schedule",
        redis_url="test_url",
        rabbitmq_url="test_url",
    )
    engine = create_engine(url=settings.database_url)
    fake_uow = FakeUnitOfWork()
    app = create_app(settings, engine, lambda: fake_uow)

    with TestClient(app, raise_server_exceptions=False) as client:
        original_request_body = {
            "class_id": 10,
            "teacher_id": str(UUID(int=100)),
            "subject_id": 1000,
            "starts_at": "2026-09-08T04:00:00Z",
            "ends_at": "2026-09-08T04:45:00Z",
        }
        first_response = client.post(
            "/lessons", headers={"Idempotency-Key": "k1"}, json=original_request_body
        )

        different_request_body = {
            "class_id": 10,
            "teacher_id": str(UUID(int=100)),
            "subject_id": 1000,
            "starts_at": "2026-09-08T04:55:00Z",
            "ends_at": "2026-09-08T05:40:00Z",
        }
        second_response = client.post(
            "/lessons", headers={"Idempotency-Key": "k1"}, json=different_request_body
        )

    assert first_response.status_code == 201
    assert fake_uow.lessons.add_calls == 1
    assert second_response.status_code == 409
    assert second_response.json() == {
        "detail": "Idempotency key was already used for another request"
    }
