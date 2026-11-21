"""Закрытые чтения интервалов календаря и названий предметов."""

import secrets
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError

from schedule_service.api.lessons import LessonResponse
from schedule_service.api.teacher_lessons import bearer, require_gateway
from schedule_service.application.calendar_lessons import (
    CalendarLessonsQuery,
    CalendarPeriodTooLargeError,
    ListCalendarLessonsHandler,
)
from schedule_service.application.errors import LessonNotFound
from schedule_service.application.homework_reads import (
    GetHomeworkLessonHandler,
    GetHomeworkLessonQuery,
)


def require_calendar_service(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    """Разрешает Gateway или Homework; неоднозначная настройка закрывает доступ."""
    settings = request.app.state.settings
    tokens = [
        value
        for value in (settings.gateway_service_token, settings.homework_service_token)
        if value
    ]
    if not tokens or len(set(tokens)) != len(tokens):
        raise HTTPException(503, "Calendar integration unavailable")
    if credentials is None or not any(
        secrets.compare_digest(credentials.credentials.encode(), value.encode())
        for value in tokens
    ):
        raise HTTPException(
            401, "Invalid service credentials", headers={"WWW-Authenticate": "Bearer"}
        )


router = APIRouter(include_in_schema=False)


@router.get(
    "/internal/gateway-lessons/{lesson_id}",
    response_model=LessonResponse,
    dependencies=[Depends(require_gateway)],
)
async def gateway_lesson(
    request: Request, lesson_id: Annotated[int, Path(ge=1, le=2147483647)]
) -> LessonResponse:
    """Читает один актуальный урок для авторизации Gateway, без Redis-копии."""
    try:
        lesson = await GetHomeworkLessonHandler(request.app.state.uow_factory).handle(
            GetHomeworkLessonQuery(lesson_id=lesson_id)
        )
    except LessonNotFound as exc:
        raise HTTPException(404, "Lesson not found") from exc
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(503, "Schedule unavailable") from exc
    return LessonResponse(**asdict(lesson))


@router.get(
    "/internal/calendar-lessons",
    response_model=list[LessonResponse],
    dependencies=[Depends(require_calendar_service)],
)
async def calendar_lessons(
    request: Request, query: Annotated[CalendarLessonsQuery, Query()]
) -> list[LessonResponse]:
    """Возвращает полный ограниченный интервал, не скрывая ошибки за пустым списком."""
    try:
        lessons = await ListCalendarLessonsHandler(
            request.app.state.uow_factory
        ).handle(query)
    except CalendarPeriodTooLargeError as exc:
        raise HTTPException(422, "Too many lessons; narrow the period") from exc
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(503, "Schedule unavailable") from exc
    return [LessonResponse(**asdict(lesson)) for lesson in lessons]


class SubjectIds(BaseModel):
    """Уникальный пакет положительных ID без произвольных полей."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    ids: list[Annotated[int, Field(strict=True, ge=1, le=2147483647)]] = Field(
        max_length=1000
    )

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("Duplicate subject IDs")
        return self


class SubjectResponse(BaseModel):
    """Неизвестное имя остаётся явным null."""

    id: int
    name: str | None


@router.get(
    "/internal/subjects",
    response_model=list[SubjectResponse],
    dependencies=[Depends(require_gateway)],
)
async def list_subjects(request: Request) -> list[SubjectResponse]:
    """Возвращает весь справочник предметов только для Gateway."""
    try:
        async with request.app.state.uow_factory() as uow:
            subjects = await uow.subjects.list_all()
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(503, "Schedule unavailable") from exc
    return [SubjectResponse(**asdict(subject)) for subject in subjects]


@router.post(
    "/internal/subjects/lookup",
    response_model=list[SubjectResponse],
    dependencies=[Depends(require_gateway)],
)
async def lookup_subjects(request: Request, body: SubjectIds) -> list[SubjectResponse]:
    """Читает справочник пакетом только для Gateway."""
    try:
        async with request.app.state.uow_factory() as uow:
            subjects = await uow.subjects.get_many(body.ids)
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(503, "Schedule unavailable") from exc
    return [SubjectResponse(**asdict(subject)) for subject in subjects]
