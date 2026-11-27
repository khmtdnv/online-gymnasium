"""Рабочее место администратора расписания: справочники и операции с уроками.

Все маршруты требуют роль администратора; портал лишь передаёт проверенные
данные сервису Schedule, который остаётся владельцем конфликтов и версий.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from gateway_service.api.security import RequireRoles
from gateway_service.api.teacher_lessons import get_schedule_client
from gateway_service.api.user_profiles import get_profiles_handler
from gateway_service.application.teacher_lessons import ScheduleUnavailableError
from gateway_service.application.user_profiles import (
    SearchUsersQuery,
    UserProfilesHandler,
)
from gateway_service.domain.user import Role
from gateway_service.infrastructure.journal_client import JournalUnavailableError
from gateway_service.infrastructure.schedule_client import ScheduleClient, SchoolPeriod

router = APIRouter(
    prefix="/api/v1/schedule",
    tags=["schedule admin"],
    dependencies=[Depends(RequireRoles((Role.ADMIN,)))],
)


class AdminLessonResponse(BaseModel):
    """Урок в терминах административного контракта Schedule."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(strict=True, ge=1)
    class_id: int = Field(strict=True, ge=1)
    teacher_id: UUID
    subject_id: int = Field(strict=True, ge=1)
    starts_at: str
    ends_at: str
    status: str
    version: int = Field(strict=True, ge=1)


class CreateAdminLessonRequest(BaseModel):
    """Создание урока: класс, преподаватель, предмет и интервал UTC."""

    model_config = ConfigDict(extra="forbid")

    class_id: int = Field(strict=True, ge=1)
    teacher_id: UUID
    subject_id: int = Field(strict=True, ge=1)
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class UpdateAdminLessonRequest(BaseModel):
    """Перенос урока на новый интервал с ожидаемой версией."""

    model_config = ConfigDict(extra="forbid")

    starts_at: AwareDatetime
    ends_at: AwareDatetime
    expected_version: int = Field(strict=True, ge=1)


class CancelAdminLessonRequest(BaseModel):
    """Отмена урока с ожидаемой версией."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(strict=True, ge=1)


class DirectoryResponse(BaseModel):
    """Справочники для формы расписания: классы, предметы и периоды."""

    model_config = ConfigDict(extra="forbid")

    classes: list[dict[str, Any]]
    subjects: list[dict[str, Any]]
    periods: list[SchoolPeriod]


class TeacherDirectoryItem(BaseModel):
    """Преподаватель с человеком понятным именем для выбора в форме."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    full_name: str
    email: str


def _forward_error(code: int, body: Any) -> HTTPException:
    """Переводит ошибку Schedule в безопасный ответ портала."""
    detail = body.get("detail") if isinstance(body, dict) else None
    message = detail if isinstance(detail, str) else "Schedule rejected the request"
    return HTTPException(status_code=code, detail=message)


@router.get("/lessons", response_model=list[AdminLessonResponse])
async def list_lessons(
    class_id: Annotated[int, Query(gt=0)],
    date: Annotated[str, Query(min_length=10, max_length=10)],
    client: Annotated[ScheduleClient, Depends(get_schedule_client)],
) -> list[AdminLessonResponse]:
    """Уроки класса за учебный день."""
    try:
        rows = await client.admin_list_lessons(class_id, date)
    except ScheduleUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc
    try:
        return [AdminLessonResponse(**row) for row in rows]
    except Exception as exc:
        raise HTTPException(502, "Unexpected schedule response") from exc


@router.post(
    "/lessons",
    status_code=201,
    response_model=AdminLessonResponse,
)
async def create_lesson(
    request_model: CreateAdminLessonRequest,
    response: Response,
    request: Request,
    client: Annotated[ScheduleClient, Depends(get_schedule_client)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> AdminLessonResponse:
    """Создаёт урок; повтор запроса с тем же ключом безопасен."""
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    key = idempotency_key
    body = request_model.model_dump(mode="json")
    code, payload = await client.admin_create_lesson(body, key)
    if code not in (200, 201):
        raise _forward_error(code, payload)
    response.status_code = status.HTTP_201_CREATED
    return AdminLessonResponse(**payload)


@router.patch("/lessons/{lesson_id}", response_model=AdminLessonResponse)
async def update_lesson(
    request_model: UpdateAdminLessonRequest,
    lesson_id: Annotated[int, Path(gt=0)],
    client: Annotated[ScheduleClient, Depends(get_schedule_client)],
) -> AdminLessonResponse:
    """Переносит урок; конфликт версий возвращает 409."""
    code, payload = await client.admin_update_lesson(
        lesson_id, request_model.model_dump(mode="json")
    )
    if code != 200:
        raise _forward_error(code, payload)
    return AdminLessonResponse(**payload)


@router.post("/lessons/{lesson_id}/cancel", response_model=AdminLessonResponse)
async def cancel_lesson(
    request_model: CancelAdminLessonRequest,
    lesson_id: Annotated[int, Path(gt=0)],
    client: Annotated[ScheduleClient, Depends(get_schedule_client)],
) -> AdminLessonResponse:
    """Отменяет урок; конфликт версий возвращает 409."""
    code, payload = await client.admin_cancel_lesson(
        lesson_id, request_model.model_dump(mode="json")
    )
    if code != 200:
        raise _forward_error(code, payload)
    return AdminLessonResponse(**payload)


@router.get("/directory", response_model=DirectoryResponse)
async def directory(
    client: Annotated[ScheduleClient, Depends(get_schedule_client)],
    request: Request,
) -> DirectoryResponse:
    """Классы Journal и предметы Schedule для селектов формы."""
    journal = request.app.state.journal_client
    if journal is None:
        raise HTTPException(503, "Service unavailable")
    try:
        classes: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await journal.list_classes(limit=100, offset=offset)
            classes.extend({"id": row.id, "name": row.name} for row in page)
            if len(page) < 100:
                break
            offset += 100
    except JournalUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc
    try:
        subjects = await client.list_subjects()
        grid = await client.get_school_periods()
    except ScheduleUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc
    return DirectoryResponse(classes=classes, subjects=subjects, periods=grid.periods)


@router.get("/teachers", response_model=list[TeacherDirectoryItem])
async def search_teachers(
    q: Annotated[str, Query(min_length=2, max_length=200)],
    handler: Annotated[UserProfilesHandler, Depends(get_profiles_handler)],
) -> list[TeacherDirectoryItem]:
    """Ищет преподавателей по ФИО или email для выбора в форме урока."""
    result = await handler.search(
        SearchUsersQuery(q=q, role=Role.TEACHER, active_only=True, limit=20)
    )
    return [
        TeacherDirectoryItem(
            id=row.id,
            full_name=" ".join(
                part
                for part in (row.last_name, row.first_name, row.middle_name)
                if part
            )
            or row.email,
            email=row.email,
        )
        for row in result
    ]
