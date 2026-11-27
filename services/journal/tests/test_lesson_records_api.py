"""Проверяет контракт внутренних ручек записей урока с подменой только БД."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

import journal_service.application.lesson_records as lesson_records_module
from journal_service.app import create_app
from journal_service.application.ports.lesson_record_repository import SubjectAverage
from journal_service.config import JournalSettings
from journal_service.domain.lesson_records import (
    AttendanceStatus,
    GradeKind,
    LessonAttendance,
    LessonGrade,
)
from journal_service.domain.student_class_period import StudentClassPeriod

TODAY = date(2026, 11, 27)
TEACHER_ID = UUID("bbbbbbbb-0000-4000-8000-000000000001")
OTHER_TEACHER_ID = UUID("bbbbbbbb-0000-4000-8000-000000000002")
STUDENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
OTHER_STUDENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000002")
LESSON_DATE = date(2026, 11, 15)
SERVER_MOMENT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
JOINED_AT = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)

WRITE_TOKEN = "gateway-write-token"
READ_TOKEN = "gateway-read-token"
BACKOFFICE_TOKEN = "backoffice-token"
POST_HEADERS = {"X-User-ID": str(TEACHER_ID), "X-User-Role": "teacher"}


def make_saved_entries() -> tuple[list[LessonAttendance], list[LessonGrade]]:
    """Собирает состояние урока после сохранения для ответа ручки."""
    attendance = LessonAttendance(
        lesson_id=42,
        lesson_date=LESSON_DATE,
        class_id=7,
        student_id=STUDENT_ID,
        status=AttendanceStatus.PRESENT,
        author_id=TEACHER_ID,
        id=1,
        created_at=SERVER_MOMENT,
        updated_at=SERVER_MOMENT,
    )
    grade = LessonGrade(
        lesson_id=42,
        lesson_date=LESSON_DATE,
        class_id=7,
        subject_id=3,
        student_id=STUDENT_ID,
        grade=5,
        kind=GradeKind.ORAL,
        author_id=TEACHER_ID,
        id=2,
        created_at=SERVER_MOMENT,
        updated_at=SERVER_MOMENT,
    )
    return [attendance], [grade]


def make_app(
    monkeypatch,
    *,
    members: list[StudentClassPeriod] | None = None,
    saved: tuple[list[LessonAttendance], list[LessonGrade]] | None = None,
    replace_error: Exception | None = None,
    averages: list[SubjectAverage] | None = None,
    last_entry_date: date | None = None,
):
    """Собирает приложение с настоящими обработчиками и отдельным fake UoW."""
    monkeypatch.setattr(lesson_records_module, "school_today", lambda: TODAY)
    roster = members or [
        StudentClassPeriod(
            id=20, student_id=STUDENT_ID, class_id=7, joined_at=JOINED_AT
        )
    ]
    if saved is None:
        saved = make_saved_entries()

    uow = Mock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.class_periods.list_members_on_date = AsyncMock(return_value=roster)
    uow.lesson_records = Mock()
    if replace_error is not None:
        uow.lesson_records.replace_lesson_entries = AsyncMock(side_effect=replace_error)
    else:
        uow.lesson_records.replace_lesson_entries = AsyncMock(return_value=saved)
    uow.lesson_records.list_student_entries = AsyncMock(return_value=([], []))
    uow.lesson_records.list_lesson_entries = AsyncMock(return_value=([], []))
    uow.lesson_records.subject_averages = AsyncMock(
        return_value=averages if averages is not None else []
    )
    uow.lesson_records.last_entry_date = AsyncMock(return_value=last_entry_date)

    factory = Mock(return_value=uow)
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token=BACKOFFICE_TOKEN,
        gateway_read_service_token=READ_TOKEN,
        gateway_write_service_token=WRITE_TOKEN,
        _env_file=None,
    )
    return create_app(settings, factory), uow


def request(
    app,
    method: str,
    path: str,
    *,
    token: str | None = None,
    headers: dict | None = None,
    json_body: dict | None = None,
    params: dict | None = None,
):
    """Выполняет HTTP-запрос через ASGI с настоящими зависимостями."""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            request_headers = {}
            if token is not None:
                request_headers["Authorization"] = f"Bearer {token}"
            if headers is not None:
                request_headers.update(headers)
            return await client.request(
                method,
                path,
                headers=request_headers,
                json=json_body,
                params=params,
            )

    return asyncio.run(run())


def make_body(**overrides) -> dict:
    """Собирает валидное тело записи урока для тестов."""
    body = {
        "context": {
            "class_id": 7,
            "subject_id": 3,
            "lesson_date": LESSON_DATE.isoformat(),
            "status": "planned",
            "teacher_id": str(TEACHER_ID),
        },
        "attendance": [{"student_id": str(STUDENT_ID), "status": "present"}],
        "grades": [{"student_id": str(STUDENT_ID), "kind": "oral", "grade": 5}],
    }
    body.update(overrides)
    return body


def test_record_lesson_entries_replaces_and_returns_state(monkeypatch) -> None:
    """Успешная замена возвращает состояние урока и передаёт доменные объекты."""
    app, uow = make_app(monkeypatch)
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers=POST_HEADERS,
        json_body=make_body(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["attendance"] == [
        {
            "lesson_id": 42,
            "lesson_date": LESSON_DATE.isoformat(),
            "class_id": 7,
            "student_id": str(STUDENT_ID),
            "status": "present",
            "author_id": str(TEACHER_ID),
            "generator": False,
            "created_at": "2026-11-15T12:00:00Z",
            "updated_at": "2026-11-15T12:00:00Z",
        }
    ]
    assert payload["grades"][0]["kind"] == "oral"
    assert payload["grades"][0]["subject_id"] == 3
    uow.lesson_records.replace_lesson_entries.assert_awaited_once()
    lesson_id, attendance, grades = (
        uow.lesson_records.replace_lesson_entries.await_args.args
    )
    assert lesson_id == 42
    assert attendance[0].status is AttendanceStatus.PRESENT
    assert attendance[0].author_id == TEACHER_ID
    assert grades[0].subject_id == 3
    assert grades[0].kind is GradeKind.ORAL


def test_record_lesson_entries_requires_teacher_match(monkeypatch) -> None:
    """Несовпадение учителя контекста с автором даёт 409 без записи."""
    app, uow = make_app(monkeypatch)
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers={**POST_HEADERS, "X-User-ID": str(OTHER_TEACHER_ID)},
        json_body=make_body(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


@pytest.mark.parametrize(
    ("lesson_date", "detail"),
    [
        ("2027-05-01", "future"),
        ("2026-09-15", "closed quarter"),
        ("2026-11-01", "vacation"),
    ],
)
def test_record_lesson_entries_rejects_wrong_dates(
    monkeypatch, lesson_date: str, detail: str
) -> None:
    """Будущий урок, закрытая четверть и каникулы отклоняются как 422."""
    app, uow = make_app(monkeypatch)
    body = make_body()
    body["context"]["lesson_date"] = lesson_date
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers=POST_HEADERS,
        json_body=body,
    )
    assert response.status_code == 422, detail
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


def test_record_lesson_entries_rejects_duplicate_attendance(
    monkeypatch,
) -> None:
    """Повтор ученика в посещаемости отклоняется."""
    app, uow = make_app(monkeypatch)
    entry = {"student_id": str(STUDENT_ID), "status": "present"}
    body = make_body(attendance=[entry, entry])
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers=POST_HEADERS,
        json_body=body,
    )
    assert response.status_code == 422
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


def test_record_lesson_entries_rejects_duplicate_kind(monkeypatch) -> None:
    """Повтор типа оценки у ученика отклоняется."""
    app, uow = make_app(monkeypatch)
    grade = {"student_id": str(STUDENT_ID), "kind": "oral", "grade": 5}
    body = make_body(grades=[grade, grade])
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers=POST_HEADERS,
        json_body=body,
    )
    assert response.status_code == 422
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


def test_record_lesson_entries_rejects_three_grades(monkeypatch) -> None:
    """Больше двух оценок одному ученику отклоняется."""
    app, uow = make_app(monkeypatch)
    body = make_body(
        grades=[
            {"student_id": str(STUDENT_ID), "kind": "oral", "grade": 5},
            {"student_id": str(STUDENT_ID), "kind": "written", "grade": 4},
            {"student_id": str(STUDENT_ID), "kind": "control", "grade": 3},
        ]
    )
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers=POST_HEADERS,
        json_body=body,
    )
    assert response.status_code == 422
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


def test_record_lesson_entries_rejects_grade_for_absent(monkeypatch) -> None:
    """Оценка отсутствующему ученику отклоняется."""
    app, uow = make_app(monkeypatch)
    body = make_body(
        attendance=[{"student_id": str(STUDENT_ID), "status": "absent_sick"}]
    )
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers=POST_HEADERS,
        json_body=body,
    )
    assert response.status_code == 422
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


def test_record_lesson_entries_rejects_grade_without_attendance(
    monkeypatch,
) -> None:
    """Оценка без строки посещаемости отклоняется."""
    app, uow = make_app(monkeypatch)
    body = make_body(attendance=[])
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers=POST_HEADERS,
        json_body=body,
    )
    assert response.status_code == 422
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


def test_record_lesson_entries_rejects_foreign_students(monkeypatch) -> None:
    """Ученик вне состава класса на дату урока отклоняется."""
    app, uow = make_app(monkeypatch)
    body = make_body(
        attendance=[{"student_id": str(OTHER_STUDENT_ID), "status": "present"}],
        grades=[{"student_id": str(OTHER_STUDENT_ID), "kind": "oral", "grade": 5}],
    )
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers=POST_HEADERS,
        json_body=body,
    )
    assert response.status_code == 422
    uow.class_periods.list_members_on_date.assert_awaited_once_with(7, LESSON_DATE)
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


@pytest.mark.parametrize("token", [None, "wrong-token", BACKOFFICE_TOKEN, READ_TOKEN])
def test_record_lesson_entries_requires_write_principal(
    monkeypatch, token: str | None
) -> None:
    """Запись доступна только принципалу записи Gateway."""
    app, uow = make_app(monkeypatch)
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=token,
        headers=POST_HEADERS,
        json_body=make_body(),
    )
    assert response.status_code in (401, 403)
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


def test_record_lesson_entries_requires_teacher_role_header(monkeypatch) -> None:
    """Роль не-учителя в заголовке отклоняется на уровне контракта."""
    app, uow = make_app(monkeypatch)
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers={"X-User-ID": str(TEACHER_ID), "X-User-Role": "student"},
        json_body=make_body(),
    )
    assert response.status_code == 422
    uow.lesson_records.replace_lesson_entries.assert_not_awaited()


def test_record_lesson_entries_maps_storage_failure(monkeypatch) -> None:
    """Сбой хранилища отображается как 503 без внутренних деталей."""
    app, _ = make_app(monkeypatch, replace_error=SQLAlchemyError("boom"))
    response = request(
        app,
        "POST",
        "/internal/lessons/42/entries",
        token=WRITE_TOKEN,
        headers=POST_HEADERS,
        json_body=make_body(),
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "http_error"


def test_diary_entries_read_window(monkeypatch) -> None:
    """Чтение окном недели проходит с diary:read и передаёт границы."""
    app, uow = make_app(monkeypatch)
    response = request(
        app,
        "GET",
        f"/internal/students/{STUDENT_ID}/diary-entries",
        token=READ_TOKEN,
        params={"date_from": "2026-11-09", "date_to": "2026-11-15"},
    )
    assert response.status_code == 200
    assert response.json() == {"attendance": [], "grades": []}
    uow.lesson_records.list_student_entries.assert_awaited_once_with(
        STUDENT_ID, date(2026, 11, 9), date(2026, 11, 15)
    )


def test_diary_entries_reject_long_window(monkeypatch) -> None:
    """Окно длиннее четверти отклоняется как 422."""
    app, uow = make_app(monkeypatch)
    response = request(
        app,
        "GET",
        f"/internal/students/{STUDENT_ID}/diary-entries",
        token=READ_TOKEN,
        params={"date_from": "2026-09-01", "date_to": "2027-05-29"},
    )
    assert response.status_code == 422
    uow.lesson_records.list_student_entries.assert_not_awaited()


def test_diary_entries_require_diary_permission(monkeypatch) -> None:
    """Токен без права diary:read не открывает окно."""
    app, uow = make_app(monkeypatch)
    response = request(
        app,
        "GET",
        f"/internal/students/{STUDENT_ID}/diary-entries",
        token=BACKOFFICE_TOKEN,
        params={"date_from": "2026-11-09", "date_to": "2026-11-15"},
    )
    assert response.status_code == 403
    uow.lesson_records.list_student_entries.assert_not_awaited()


def test_last_entry_date_returns_anchor(monkeypatch) -> None:
    """Дата последней записи возвращается как якорь дефолтной недели."""
    app, uow = make_app(monkeypatch, last_entry_date=date(2026, 11, 26))
    response = request(
        app,
        "GET",
        f"/internal/students/{STUDENT_ID}/last-entry-date",
        token=READ_TOKEN,
    )
    assert response.status_code == 200
    assert response.json() == {"last_entry_date": "2026-11-26"}
    uow.lesson_records.last_entry_date.assert_awaited_once_with(STUDENT_ID)


def test_last_entry_date_returns_none_without_entries(monkeypatch) -> None:
    """Без записей якорь равен None."""
    app, _ = make_app(monkeypatch, last_entry_date=None)
    response = request(
        app,
        "GET",
        f"/internal/students/{STUDENT_ID}/last-entry-date",
        token=READ_TOKEN,
    )
    assert response.status_code == 200
    assert response.json() == {"last_entry_date": None}


def test_subject_averages_round_half_up(monkeypatch) -> None:
    """Средняя 4,5 округляется к 5 по правилу half-up."""
    app, uow = make_app(
        monkeypatch,
        averages=[SubjectAverage(subject_id=3, average=Decimal("4.5"), grade_count=6)],
    )
    response = request(
        app,
        "GET",
        f"/internal/students/{STUDENT_ID}/subject-averages",
        token=READ_TOKEN,
        params={"quarter": 2},
    )
    assert response.status_code == 200
    assert response.json() == [
        {"subject_id": 3, "average": 4.5, "grade_count": 6, "quarter_grade": 5}
    ]
    uow.lesson_records.subject_averages.assert_awaited_once_with(
        STUDENT_ID, date(2026, 11, 9), date(2026, 12, 26)
    )


def test_subject_averages_reject_wrong_quarter(monkeypatch) -> None:
    """Номер четверти вне 1–4 отклоняется."""
    app, uow = make_app(monkeypatch)
    response = request(
        app,
        "GET",
        f"/internal/students/{STUDENT_ID}/subject-averages",
        token=READ_TOKEN,
        params={"quarter": 5},
    )
    assert response.status_code == 422
    uow.lesson_records.subject_averages.assert_not_awaited()


def test_lesson_entries_read_for_form(monkeypatch) -> None:
    """Чтение записей урока для формы правки доступно read-принципалу."""
    app, uow = make_app(monkeypatch)
    response = request(
        app,
        "GET",
        "/internal/lessons/42/entries",
        token=READ_TOKEN,
    )
    assert response.status_code == 200
    assert response.json() == {"attendance": [], "grades": []}
    uow.lesson_records.list_lesson_entries.assert_awaited_once_with(42)
