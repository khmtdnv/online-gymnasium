"""Закрытое расписание для доверенного Gateway."""

import secrets
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError

from schedule_service.api.lessons import LessonResponse
from schedule_service.application.teacher_lessons import (
    ListTeacherLessonsHandler,
    ListTeacherLessonsQuery,
    TeacherLessonDates,
)

bearer = HTTPBearer(auto_error=False)


def require_gateway(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    """Разрешает отдельный секрет Gateway, не секрет Homework.

    Args:
        request: Запрос с настройками Schedule.
        credentials: Служебный Bearer вызывающего сервиса.

    Raises:
        HTTPException: Не настроен отдельный доступ (503) или неверный токен (401).
    """
    expected = request.app.state.settings.gateway_service_token
    homework_token = request.app.state.settings.homework_service_token
    if not expected or (
        homework_token
        and secrets.compare_digest(expected.encode(), homework_token.encode())
    ):
        raise HTTPException(503, "Schedule integration unavailable")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(
            401, "Invalid service credentials", headers={"WWW-Authenticate": "Bearer"}
        )


router = APIRouter(
    prefix="/internal/teacher-lessons",
    include_in_schema=False,
    dependencies=[Depends(require_gateway)],
)


@router.get("", response_model=list[LessonResponse])
async def list_teacher_lessons(
    request: Request,
    dates: Annotated[TeacherLessonDates, Query()],
    teacher_id: Annotated[UUID, Header(alias="X-Teacher-ID")],
) -> list[LessonResponse]:
    """Возвращает расписание только указанного доверенного преподавателя.

    Args:
        request: Запрос с фабрикой UoW.
        dates: Границы календарного диапазона UTC.
        teacher_id: UUID, установленный аутентифицированным Gateway.

    Returns:
        Уроки в порядке starts_at,id.

    Raises:
        HTTPException: Своя БД недоступна (503).
    """
    try:
        lessons = await ListTeacherLessonsHandler(request.app.state.uow_factory).handle(
            ListTeacherLessonsQuery(
                teacher_id=teacher_id, date_from=dates.date_from, date_to=dates.date_to
            )
        )
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(503, "Schedule unavailable") from exc
    return [LessonResponse(**asdict(lesson)) for lesson in lessons]
