"""Закрытые чтения Schedule, доступные только Homework."""

import secrets
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError

from schedule_service.api.lessons import LessonResponse
from schedule_service.application.errors import LessonNotFound
from schedule_service.application.homework_reads import (
    GetHomeworkLessonHandler,
    GetHomeworkLessonQuery,
    GetNextHomeworkLessonHandler,
    LookupHomeworkLessonsHandler,
    LookupHomeworkLessonsQuery,
)

bearer = HTTPBearer(auto_error=False)


def require_homework_service(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    """Даёт Homework только чтение; внешний actor не является credential.

    Args:
        request: Запрос с настройками Schedule.
        credentials: Служебный Bearer-токен, не JWT пользователя.

    Raises:
        HTTPException: Нет credentials (401), интеграция не настроена (503).
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid service credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expected = request.app.state.settings.homework_service_token
    if not expected:
        raise HTTPException(status_code=503, detail="Homework integration unavailable")
    if not secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid service credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(
    prefix="/internal/lessons",
    include_in_schema=False,
    dependencies=[Depends(require_homework_service)],
)
LessonId = Annotated[int, Path(ge=1, le=2147483647)]


@router.post("/lookup", response_model=list[LessonResponse])
async def lookup_homework_lessons(
    body: LookupHomeworkLessonsQuery, request: Request
) -> list[LessonResponse]:
    """Возвращает пакет существующих уроков для вычисления сроков ДЗ.

    Args:
        body: Уникальные ID, не более ста.
        request: Запрос с фабрикой UoW.

    Returns:
        Уроки в порядке ID без фиктивных записей для отсутствующих.

    Raises:
        HTTPException: База недоступна (503).
    """
    try:
        lessons = await LookupHomeworkLessonsHandler(
            request.app.state.uow_factory
        ).handle(LookupHomeworkLessonsQuery(lesson_ids=body.lesson_ids))
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(503, "Schedule unavailable") from exc
    return [
        LessonResponse(
            id=lesson.id,
            class_id=lesson.class_id,
            teacher_id=lesson.teacher_id,
            subject_id=lesson.subject_id,
            starts_at=lesson.starts_at,
            ends_at=lesson.ends_at,
            status=lesson.status,
            version=lesson.version,
        )
        for lesson in lessons
    ]


@router.get("/{lesson_id}", response_model=LessonResponse)
async def get_homework_lesson(lesson_id: LessonId, request: Request) -> LessonResponse:
    """Читает один урок напрямую из Schedule.

    Args:
        lesson_id: ID запрошенного урока.
        request: Запрос с фабрикой UoW.

    Returns:
        Урок с UUID преподавателя и текущим статусом.

    Raises:
        HTTPException: Урок отсутствует (404) либо БД недоступна (503).
    """
    try:
        lesson = await GetHomeworkLessonHandler(request.app.state.uow_factory).handle(
            GetHomeworkLessonQuery(lesson_id=lesson_id)
        )
    except LessonNotFound as exc:
        raise HTTPException(status_code=404, detail="Lesson not found") from exc
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Schedule unavailable") from exc
    return LessonResponse(**asdict(lesson))


@router.get("/{lesson_id}/next", response_model=LessonResponse | None)
async def get_next_homework_lesson(
    lesson_id: LessonId, request: Request
) -> LessonResponse | None:
    """Возвращает предложение срока либо null, если кандидата нет.

    Args:
        lesson_id: ID урока выдачи.
        request: Запрос с фабрикой UoW.

    Returns:
        Ближайший урок либо None при успешном пустом поиске.

    Raises:
        HTTPException: Исходный урок отсутствует (404) либо БД недоступна (503).
    """
    try:
        lesson = await GetNextHomeworkLessonHandler(
            request.app.state.uow_factory
        ).handle(GetHomeworkLessonQuery(lesson_id=lesson_id))
    except LessonNotFound as exc:
        raise HTTPException(status_code=404, detail="Lesson not found") from exc
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Schedule unavailable") from exc
    return LessonResponse(**asdict(lesson)) if lesson is not None else None
