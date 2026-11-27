"""Дневник доступен владельцу, связанному родителю и admin."""

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

STUDENT_ID = UUID(int=1)
PARENT_ID = UUID(int=2)
OTHER_STUDENT_ID = UUID(int=3)
TEACHER_ID = UUID(int=4)


def make_user(user_id: UUID, role: Role) -> GetCurrentUserResult:
    """Собирает активного пользователя для подмены авторизации."""
    return GetCurrentUserResult(id=user_id, email="user@example.test", role=role)


def make_app(
    user: GetCurrentUserResult,
    *,
    journal: SimpleNamespace | None = None,
    schedule: SimpleNamespace | None = None,
    homework: SimpleNamespace | None = None,
    linked: bool = True,
) -> FastAPI:
    """Собирает приложение с подменёнными клиентами и зависимостью авторизации."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_user] = lambda: user

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(
                has_parent_student_link=AsyncMock(return_value=linked),
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(
                        id=STUDENT_ID, role=Role.STUDENT, is_active=True
                    )
                ),
            )
        )

    app.state.uow_factory = uow
    app.state.journal_client = journal
    app.state.journal_write_client = None
    app.state.schedule_client = schedule
    app.state.homework_client = homework
    return app


def make_journal(
    *,
    last_entry_date: date | None = date(2026, 11, 26),
    quarter: int = 2,
) -> SimpleNamespace:
    """Собирает фейковый клиент Journal для дневника."""
    return SimpleNamespace(
        diary_anchor=AsyncMock(
            return_value=SimpleNamespace(
                last_entry_date=last_entry_date,
                quarter=quarter,
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


def make_schedule() -> SimpleNamespace:
    """Собирает фейковый клиент Schedule с уроком недели."""
    return SimpleNamespace(
        get_lesson=AsyncMock(
            return_value=SimpleNamespace(
                id=42,
                class_id=7,
                subject_id=3,
                teacher_id=TEACHER_ID,
                starts_at=datetime(2026, 11, 26, 9, 0, tzinfo=UTC),
                ends_at=datetime(2026, 11, 26, 9, 45, tzinfo=UTC),
                status="planned",
                version=1,
            )
        ),
        list_calendar_lessons=AsyncMock(return_value=[]),
    )


def make_homework() -> SimpleNamespace:
    """Собирает фейковый клиент Homework."""
    return SimpleNamespace(
        list_my_homework=AsyncMock(
            return_value=SimpleNamespace(
                items=[],
                total=0,
                date_from=date(2026, 11, 23),
                date_to=date(2026, 11, 28),
            )
        )
    )


def call(app: FastAPI, method: str, path: str, **kwargs):
    """Выполняет HTTP-запрос через ASGI."""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_student_gets_own_diary_week() -> None:
    """Ученик без student_id получает свою неделю."""
    app = make_app(
        make_user(STUDENT_ID, Role.STUDENT),
        journal=make_journal(),
        schedule=make_schedule(),
        homework=make_homework(),
    )
    response = call(app, "GET", "/api/v1/diary")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    assert payload["week_start"] == "2026-11-23"
    assert payload["quarter"] == 2
    assert payload["demo_cutoff"] == "2026-11-26"
    assert payload["summary"]["quarter"] == 2


def test_student_cannot_read_other_diary() -> None:
    """Ученик с чужим student_id получает 403."""
    app = make_app(
        make_user(STUDENT_ID, Role.STUDENT),
        journal=make_journal(),
        schedule=make_schedule(),
        homework=make_homework(),
    )
    response = call(
        app, "GET", "/api/v1/diary", params={"student_id": str(OTHER_STUDENT_ID)}
    )
    assert response.status_code == 403


def test_parent_requires_student_id() -> None:
    """Родитель без student_id получает 422."""
    app = make_app(
        make_user(PARENT_ID, Role.PARENT),
        journal=make_journal(),
        schedule=make_schedule(),
        homework=make_homework(),
    )
    response = call(app, "GET", "/api/v1/diary")
    assert response.status_code == 422


def test_parent_reads_linked_child_diary() -> None:
    """Родитель связанного ученика получает дневник."""
    app = make_app(
        make_user(PARENT_ID, Role.PARENT),
        journal=make_journal(),
        schedule=make_schedule(),
        homework=make_homework(),
        linked=True,
    )
    response = call(app, "GET", "/api/v1/diary", params={"student_id": str(STUDENT_ID)})
    assert response.status_code == 200
    assert response.json()["quarter"] == 2


def test_parent_unlinked_child_denied() -> None:
    """Родитель без связи с учеником получает 403."""
    app = make_app(
        make_user(PARENT_ID, Role.PARENT),
        journal=make_journal(),
        schedule=make_schedule(),
        homework=make_homework(),
        linked=False,
    )
    response = call(app, "GET", "/api/v1/diary", params={"student_id": str(STUDENT_ID)})
    assert response.status_code == 403


def test_diary_rejects_non_monday_week_start() -> None:
    """week_start не-понедельник отклоняется 422."""
    app = make_app(
        make_user(STUDENT_ID, Role.STUDENT),
        journal=make_journal(),
        schedule=make_schedule(),
        homework=make_homework(),
    )
    response = call(app, "GET", "/api/v1/diary", params={"week_start": "2026-11-27"})
    assert response.status_code == 422


def test_diary_summary_for_quarter() -> None:
    """Сводка четверти возвращает средние и пропуски."""
    journal = make_journal()
    app = make_app(
        make_user(STUDENT_ID, Role.STUDENT),
        journal=journal,
        schedule=make_schedule(),
        homework=make_homework(),
    )
    response = call(app, "GET", "/api/v1/diary/summary", params={"quarter": 2})
    assert response.status_code == 200
    assert response.json()["quarter"] == 2
    journal.subject_averages.assert_awaited_once_with(STUDENT_ID, 2)


def test_diary_summary_requires_valid_quarter() -> None:
    """Номер четверти вне 1–4 отклоняется 422."""
    app = make_app(
        make_user(STUDENT_ID, Role.STUDENT),
        journal=make_journal(),
        schedule=make_schedule(),
        homework=make_homework(),
    )
    response = call(app, "GET", "/api/v1/diary/summary", params={"quarter": 5})
    assert response.status_code == 422


def test_diary_unavailable_without_clients() -> None:
    """Без клиентов зависимостей страница возвращает 503."""
    app = make_app(make_user(STUDENT_ID, Role.STUDENT))
    response = call(app, "GET", "/api/v1/diary")
    assert response.status_code == 503
