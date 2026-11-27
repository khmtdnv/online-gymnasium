"""Публичные ручки дневника: сетка недели, сводка и запись урока."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from sqlalchemy.exc import SQLAlchemyError

from gateway_service.api.dependent_access import require_dependent_access
from gateway_service.api.security import RequireRoles
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.diary import (
    MAX_LESSON_ID,
    MAX_QUARTER,
    DiarySummaryResult,
    DiaryWeekResult,
    GetDiaryHandler,
    GetDiaryQuery,
    GetDiarySummaryHandler,
    GetDiarySummaryQuery,
)
from gateway_service.domain.user import Role
from gateway_service.infrastructure.journal_client import (
    JournalWriteClient,
    LessonRecordConflictError,
    LessonRecordValidationError,
    RecordLessonEntriesBody,
)

router = APIRouter(prefix="/api/v1", tags=["diary"])

Viewer = Annotated[
    GetCurrentUserResult,
    Depends(RequireRoles((Role.STUDENT, Role.PARENT, Role.ADMIN))),
]
Teacher = Annotated[GetCurrentUserResult, Depends(RequireRoles((Role.TEACHER,)))]
StudentId = Annotated[UUID | None, Query()]
WeekStart = Annotated[date | None, Query()]
Quarter = Annotated[int, Query(ge=1, le=MAX_QUARTER)]
LessonId = Annotated[int, Path(ge=1, le=MAX_LESSON_ID)]


def get_diary_handler(request: Request) -> GetDiaryHandler:
    """Собирает композитор недели из зависимостей приложения.

    Args:
        request: Запрос с клиентами в состоянии приложения.

    Returns:
        Обработчик страницы недели.

    Raises:
        HTTPException: 503 при отсутствии любого клиента.
    """
    journal = request.app.state.journal_client
    schedule = request.app.state.schedule_client
    homework = request.app.state.homework_client
    if journal is None or schedule is None or homework is None:
        raise HTTPException(503, "Service unavailable")
    return GetDiaryHandler(journal, schedule, homework)


def get_summary_handler(request: Request) -> GetDiarySummaryHandler:
    """Собирает композитор сводки из зависимостей приложения.

    Args:
        request: Запрос с клиентом Journal в состоянии приложения.

    Returns:
        Обработчик сводки четверти.

    Raises:
        HTTPException: 503 при отсутствии клиента.
    """
    journal = request.app.state.journal_client
    if journal is None:
        raise HTTPException(503, "Service unavailable")
    return GetDiarySummaryHandler(journal)


def get_write_client(request: Request) -> JournalWriteClient:
    """Возвращает клиент записи уроков из состояния приложения.

    Args:
        request: Запрос с write-клиентом в состоянии приложения.

    Returns:
        Клиент принципала lesson-records:write.

    Raises:
        HTTPException: 503 при отсутствии клиента.
    """
    client = request.app.state.journal_write_client
    if client is None:
        raise HTTPException(503, "Service unavailable")
    return client


async def resolve_student_id(
    viewer: Viewer,
    student_id: StudentId,
    request: Request,
) -> UUID:
    """Резолвит ID ученика: свой для student, указанный для parent.

    Args:
        viewer: Активный пользователь.
        student_id: Указанный ID ученика (для родителя).
        request: Запрос с зависимостями для проверки привязки.

    Returns:
        ID ученика, чей дневник запрашивается.

    Raises:
        HTTPException: 400/403 при неверном использовании.
    """
    if viewer.role == Role.STUDENT:
        if student_id is not None and student_id != viewer.id:
            raise HTTPException(403, "Access denied")
        return viewer.id
    if student_id is None:
        raise HTTPException(422, "student_id is required for parent")
    await require_dependent_access(request, viewer, student_id)
    return student_id


@router.get("/diary", response_model=DiaryWeekResult)
async def get_diary(
    request: Request,
    response: Response,
    viewer: Viewer,
    handler: Annotated[GetDiaryHandler, Depends(get_diary_handler)],
    week_start: WeekStart = None,
    student_id: StudentId = None,
) -> DiaryWeekResult:
    """Возвращает сетку недели со встроенной сводкой четверти.

    Args:
        request: Запрос с клиентами в состоянии приложения.
        response: Ответ для установки заголовков кэша.
        viewer: Активный пользователь (ученик/родитель/админ).
        handler: Композитор недели.
        week_start: Понедельник недели; без него — дефолт по якорю.
        student_id: ID ученика для родителя; ученику не нужен.

    Returns:
        Сетка недели со сводкой четверти.

    Raises:
        HTTPException: 403 без права, 422 при неверных параметрах, 503 при сбое.
    """
    response.headers["Cache-Control"] = "private, no-store"
    resolved = await resolve_student_id(viewer, student_id, request)
    try:
        return await handler.handle(
            GetDiaryQuery(student_id=resolved, week_start=week_start)
        )
    except ValueError as exc:
        raise HTTPException(422, "Expected school week Monday") from exc


@router.get("/diary/summary", response_model=DiarySummaryResult)
async def get_diary_summary(
    request: Request,
    response: Response,
    viewer: Viewer,
    handler: Annotated[GetDiarySummaryHandler, Depends(get_summary_handler)],
    quarter: Quarter,
    student_id: StudentId = None,
) -> DiarySummaryResult:
    """Возвращает сводку выбранной четверти.

    Args:
        request: Запрос с клиентом Journal в состоянии приложения.
        response: Ответ для установки заголовков кэша.
        viewer: Активный пользователь (ученик/родитель/админ).
        handler: Композитор сводки.
        quarter: Номер четверти от 1 до 4.
        student_id: ID ученика для родителя; ученику не нужен.

    Returns:
        Средние, четвертные оценки и пропуски.

    Raises:
        HTTPException: 403 без права, 422 при неверных параметрах, 503 при сбое.
    """
    response.headers["Cache-Control"] = "private, no-store"
    resolved = await resolve_student_id(viewer, student_id, request)
    try:
        return await handler.handle(
            GetDiarySummaryQuery(student_id=resolved, quarter=quarter)
        )
    except ValueError as exc:
        raise HTTPException(422, "Expected quarter 1 to 4") from exc


@router.post("/lessons/{lesson_id}/entries")
async def record_lesson_entries(
    lesson_id: LessonId,
    body: RecordLessonEntriesBody,
    teacher: Teacher,
    write_client: Annotated[JournalWriteClient, Depends(get_write_client)],
    request: Request,
) -> dict:
    """Проксирует пакет-замену записей урока в Journal.

    Args:
        lesson_id: Урок Schedule, записи которого заменяются.
        body: Контекст урока, посещаемость и оценки.
        teacher: Активный учитель после проверки JWT.
        write_client: Клиент принципала записи уроков.
        request: Запрос с schedule-клиентом для проверки владения.

    Returns:
        Полное состояние записей урока после замены.

    Raises:
        HTTPException: 403 не-владельцу, 404 без урока, 409/422/503 от Journal.
    """
    schedule = request.app.state.schedule_client
    if schedule is None:
        raise HTTPException(503, "Service unavailable")
    lesson = await schedule.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(404, "Lesson not found")
    if lesson.status != "planned":
        raise HTTPException(422, "Lesson is canceled")
    if lesson.teacher_id != teacher.id:
        raise HTTPException(403, "Not the lesson owner")

    body.context.teacher_id = teacher.id
    try:
        result = await write_client.record_lesson_entries(lesson_id, body, teacher.id)
    except LessonRecordValidationError:
        raise HTTPException(422, "Invalid lesson record data") from None
    except LessonRecordConflictError:
        raise HTTPException(409, "Lesson teacher conflict") from None
    except Exception as exc:
        if isinstance(exc, SQLAlchemyError):
            raise HTTPException(503, "Journal unavailable") from exc
        raise HTTPException(503, "Journal unavailable") from exc

    return {
        "attendance": [
            {
                "lesson_id": row.lesson_id,
                "student_id": str(row.student_id),
                "status": row.status.value,
            }
            for row in result.attendance
        ],
        "grades": [
            {
                "lesson_id": row.lesson_id,
                "student_id": str(row.student_id),
                "grade": row.grade,
                "kind": row.kind.value,
            }
            for row in result.grades
        ],
    }


@router.get("/lessons/{lesson_id}/entries")
async def get_lesson_entries(
    lesson_id: LessonId,
    teacher: Teacher,
    request: Request,
    response: Response,
) -> dict:
    """Возвращает существующие записи урока для формы правки.

    Args:
        lesson_id: Урок, записи которого читаются.
        teacher: Активный учитель после проверки JWT.
        request: Запрос с клиентами в состоянии приложения.
        response: Ответ для установки заголовков кэша.

    Returns:
        Посещаемость и оценки урока.

    Raises:
        HTTPException: 403 не-владельцу, 404 без урока, 503 при сбое.
    """
    response.headers["Cache-Control"] = "private, no-store"
    schedule = request.app.state.schedule_client
    journal = request.app.state.journal_client
    if schedule is None or journal is None:
        raise HTTPException(503, "Service unavailable")
    lesson = await schedule.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(404, "Lesson not found")
    if lesson.teacher_id != teacher.id:
        raise HTTPException(403, "Not the lesson owner")

    entries = await journal.lesson_entries(lesson_id)
    return {
        "attendance": [
            {
                "lesson_id": row.lesson_id,
                "student_id": str(row.student_id),
                "status": row.status.value,
            }
            for row in entries.attendance
        ],
        "grades": [
            {
                "lesson_id": row.lesson_id,
                "student_id": str(row.student_id),
                "grade": row.grade,
                "kind": row.kind.value,
            }
            for row in entries.grades
        ],
    }
