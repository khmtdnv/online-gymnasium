"""Запись уроков: только владелец, контекст урока от Gateway, маппинг ошибок."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
from fastapi import FastAPI

from gateway_service.api.diary import router
from gateway_service.api.security import get_authenticated_user
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.domain.user import Role
from gateway_service.infrastructure.journal_client import (
    JournalUnavailableError,
    LessonRecordConflictError,
    LessonRecordValidationError,
    RecordLessonEntriesBody,
)

TEACHER_ID = UUID(int=4)
OTHER_TEACHER_ID = UUID(int=5)
LESSON_ID = 42


def make_user(user_id: UUID, role: Role) -> GetCurrentUserResult:
    """Собирает активного пользователя для подмены авторизации."""
    return GetCurrentUserResult(id=user_id, email="user@example.test", role=role)


def make_app(
    user: GetCurrentUserResult,
    *,
    lesson_teacher: UUID = TEACHER_ID,
    lesson_status: str = "planned",
    write_error: Exception | None = None,
) -> FastAPI:
    """Собирает приложение с подменёнными клиентами для записи уроков."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_user] = lambda: user

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(
                has_parent_student_link=AsyncMock(return_value=True),
            )
        )

    app.state.uow_factory = uow
    app.state.schedule_client = SimpleNamespace(
        get_lesson=AsyncMock(
            return_value=(
                SimpleNamespace(
                    id=LESSON_ID,
                    class_id=7,
                    subject_id=3,
                    teacher_id=lesson_teacher,
                    starts_at=datetime(2026, 11, 26, 9, 0, tzinfo=UTC),
                    ends_at=datetime(2026, 11, 26, 9, 45, tzinfo=UTC),
                    status=lesson_status,
                    version=1,
                )
                if lesson_status is not None
                else None
            )
        ),
        list_calendar_lessons=AsyncMock(return_value=[]),
    )

    write_result = SimpleNamespace(
        attendance=[
            SimpleNamespace(
                lesson_id=LESSON_ID, student_id=UUID(int=1), status="present"
            )
        ],
        grades=[
            SimpleNamespace(
                lesson_id=LESSON_ID, student_id=UUID(int=1), grade=5, kind="oral"
            )
        ],
    )
    if write_error is not None:
        record_mock = AsyncMock(side_effect=write_error)
    else:
        record_mock = AsyncMock(return_value=write_result)
    app.state.journal_client = SimpleNamespace(
        diary_anchor=AsyncMock(
            return_value=SimpleNamespace(
                last_entry_date=date(2026, 11, 26),
                quarter=2,
                quarter_from=date(2026, 11, 9),
                quarter_to=date(2026, 12, 26),
            )
        ),
        list_student_entries=AsyncMock(
            return_value=SimpleNamespace(attendance=[], grades=[])
        ),
        subject_averages=AsyncMock(return_value=[]),
        lesson_entries=AsyncMock(
            return_value=SimpleNamespace(attendance=[], grades=[])
        ),
    )
    app.state.journal_write_client = SimpleNamespace(record_lesson_entries=record_mock)
    app.state.homework_client = SimpleNamespace(
        list_my_homework=AsyncMock(return_value=SimpleNamespace(items=[], total=0))
    )
    return app


def make_body(teacher_id: UUID = TEACHER_ID) -> dict:
    """Собирает валидное тело записи урока."""
    return {
        "context": {
            "class_id": 7,
            "subject_id": 3,
            "lesson_date": "2026-11-26",
            "status": "planned",
            "teacher_id": str(teacher_id),
        },
        "attendance": [],
        "grades": [],
    }


def call(app: FastAPI, method: str, path: str, **kwargs):
    """Выполняет HTTP-запрос через ASGI."""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_teacher_records_own_lesson() -> None:
    """Владелец урока успешно записывает и получает состояние."""
    app = make_app(make_user(TEACHER_ID, Role.TEACHER))
    response = call(
        app, "POST", f"/api/v1/lessons/{LESSON_ID}/entries", json=make_body()
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["attendance"][0]["status"] == "present"
    assert payload["grades"][0]["grade"] == 5
    args = app.state.journal_write_client.record_lesson_entries.await_args
    assert args.args[0] == LESSON_ID
    assert args.args[2] == TEACHER_ID
    body = args.args[1]
    assert isinstance(body, RecordLessonEntriesBody)
    assert body.context.teacher_id == TEACHER_ID


def test_teacher_cannot_record_foreign_lesson() -> None:
    """Не-владелец урока получает 403."""
    app = make_app(
        make_user(OTHER_TEACHER_ID, Role.TEACHER),
        lesson_teacher=TEACHER_ID,
    )
    response = call(
        app, "POST", f"/api/v1/lessons/{LESSON_ID}/entries", json=make_body()
    )
    assert response.status_code == 403
    app.state.journal_write_client.record_lesson_entries.assert_not_awaited()


def test_teacher_cannot_record_cancelled_lesson() -> None:
    """Отменённый урок отклоняется 422."""
    app = make_app(
        make_user(TEACHER_ID, Role.TEACHER),
        lesson_status="canceled",
    )
    response = call(
        app, "POST", f"/api/v1/lessons/{LESSON_ID}/entries", json=make_body()
    )
    assert response.status_code == 422
    app.state.journal_write_client.record_lesson_entries.assert_not_awaited()


def test_teacher_cannot_record_missing_lesson() -> None:
    """Несуществующий урок даёт 404."""
    app = make_app(
        make_user(TEACHER_ID, Role.TEACHER),
        lesson_status=None,
    )
    response = call(
        app, "POST", f"/api/v1/lessons/{LESSON_ID}/entries", json=make_body()
    )
    assert response.status_code == 404
    app.state.journal_write_client.record_lesson_entries.assert_not_awaited()


def test_student_cannot_record_lessons() -> None:
    """Ученику запись урока недоступна (роль)."""
    app = make_app(make_user(UUID(int=1), Role.STUDENT))
    response = call(
        app, "POST", f"/api/v1/lessons/{LESSON_ID}/entries", json=make_body()
    )
    assert response.status_code in (401, 403)


def test_validation_error_maps_to_422() -> None:
    """Ошибка валидации Journal проксируется как 422."""
    app = make_app(
        make_user(TEACHER_ID, Role.TEACHER),
        write_error=LessonRecordValidationError(),
    )
    response = call(
        app, "POST", f"/api/v1/lessons/{LESSON_ID}/entries", json=make_body()
    )
    assert response.status_code == 422


def test_conflict_error_maps_to_409() -> None:
    """Конфликт учителя Journal проксируется как 409."""
    app = make_app(
        make_user(TEACHER_ID, Role.TEACHER),
        write_error=LessonRecordConflictError(),
    )
    response = call(
        app, "POST", f"/api/v1/lessons/{LESSON_ID}/entries", json=make_body()
    )
    assert response.status_code == 409


def test_journal_unavailable_maps_to_503() -> None:
    """Недоступность Journal проксируется как 503."""
    app = make_app(
        make_user(TEACHER_ID, Role.TEACHER),
        write_error=JournalUnavailableError(),
    )
    response = call(
        app, "POST", f"/api/v1/lessons/{LESSON_ID}/entries", json=make_body()
    )
    assert response.status_code == 503


def test_teacher_reads_lesson_entries_for_form() -> None:
    """Владелец читает записи урока для формы правки."""
    app = make_app(make_user(TEACHER_ID, Role.TEACHER))
    response = call(app, "GET", f"/api/v1/lessons/{LESSON_ID}/entries")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {"attendance": [], "grades": []}
    app.state.journal_client.lesson_entries.assert_awaited_once_with(LESSON_ID)


def test_teacher_cannot_read_foreign_lesson_entries() -> None:
    """Не-владелец не читает записи урока."""
    app = make_app(
        make_user(OTHER_TEACHER_ID, Role.TEACHER),
        lesson_teacher=TEACHER_ID,
    )
    response = call(app, "GET", f"/api/v1/lessons/{LESSON_ID}/entries")
    assert response.status_code == 403
    app.state.journal_client.lesson_entries.assert_not_awaited()
