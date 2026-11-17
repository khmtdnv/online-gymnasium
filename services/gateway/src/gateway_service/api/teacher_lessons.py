"""Публичное расписание и карточка текущего преподавателя."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from gateway_service.api.homework import get_homework_client, teacher_only
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkUnavailableError,
)
from gateway_service.application.teacher_lessons import (
    LessonInfo,
    ListTeacherLessonsQuery,
    ScheduleUnavailableError,
    TeacherLessonResult,
)
from gateway_service.infrastructure.homework_client import HomeworkClient
from gateway_service.infrastructure.schedule_client import ScheduleClient

router = APIRouter(prefix="/api/v1/lessons", tags=["teacher lessons"])


def get_schedule_client(request: Request) -> ScheduleClient:
    """Возвращает настроенный клиент Schedule либо безопасный503."""
    client = request.app.state.schedule_client
    if client is None:
        raise HTTPException(503, "Service unavailable")
    return client


@router.get("", response_model=list[LessonInfo])
async def list_teacher_lessons(
    query: Annotated[ListTeacherLessonsQuery, Query()],
    teacher: Annotated[GetCurrentUserResult, Depends(teacher_only)],
    client: Annotated[ScheduleClient, Depends(get_schedule_client)],
) -> list[LessonInfo]:
    """Читает расписание пользователя, не позволяя выбрать другого учителя.

    Args:
        query: Даты включительно, максимум семь дней UTC.
        teacher: Активный преподаватель из цепочки аутентификации.
        client: Настроенный клиент Schedule.

    Returns:
        Уроки преподавателя, включая отменённые.

    Raises:
        HTTPException: Владелец расписания недоступен (503).
    """
    try:
        return await client.list_teacher_lessons(
            teacher_id=teacher.id, date_from=query.date_from, date_to=query.date_to
        )
    except ScheduleUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc


@router.get("/{lesson_id}", response_model=TeacherLessonResult)
async def get_teacher_lesson(
    lesson_id: Annotated[int, Path(ge=1, le=2147483647)],
    teacher: Annotated[GetCurrentUserResult, Depends(teacher_only)],
    client: Annotated[HomeworkClient, Depends(get_homework_client)],
) -> TeacherLessonResult:
    """Читает карточку через владельца заданий с доверенным UUID.

    Args:
        lesson_id: ID выбранного урока.
        teacher: Активный преподаватель из Gateway.
        client: Клиент сервиса Homework.

    Returns:
        Урок, предложение следующего и две группы заданий.

    Raises:
        HTTPException: Нет права403, урока404 либо сервис недоступен503.
    """
    try:
        return await client.get_teacher_lesson(
            teacher_id=teacher.id, lesson_id=lesson_id
        )
    except HomeworkRequestError as exc:
        message = "Access denied" if exc.status_code == 403 else "Lesson not found"
        raise HTTPException(exc.status_code, message) from exc
    except HomeworkUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc
