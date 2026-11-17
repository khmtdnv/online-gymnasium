"""Личный недельный календарь и читаемая карточка урока."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from gateway_service.api.security import RequireRoles
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkUnavailableError,
)
from gateway_service.application.my_schedule import (
    GetMyScheduleHandler,
    GetMyScheduleQuery,
    LessonViewResult,
    MyScheduleResult,
)
from gateway_service.application.teacher_lessons import ScheduleUnavailableError
from gateway_service.domain.user import Role
from gateway_service.infrastructure.journal_client import JournalUnavailableError

router = APIRouter(prefix="/api/v1/my-schedule", tags=["personal schedule"])
User = Annotated[
    GetCurrentUserResult, Depends(RequireRoles((Role.STUDENT, Role.TEACHER)))
]


class WeekQuery(BaseModel):
    """Только понедельник; UUID/роль/класс из запроса не принимаются."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    week_start: date


def get_handler(request: Request) -> GetMyScheduleHandler:
    """Отсутствие настройки владельца означает503, а не пустую неделю."""
    if (
        request.app.state.journal_client is None
        or request.app.state.schedule_client is None
    ):
        raise HTTPException(503, "Service unavailable")
    return GetMyScheduleHandler(
        request.app.state.uow_factory,
        request.app.state.journal_client,
        request.app.state.schedule_client,
    )


@router.get("", response_model=MyScheduleResult)
async def my_schedule(
    request: Request,
    response: Response,
    query: Annotated[WeekQuery, Query()],
    user: User,
) -> MyScheduleResult:
    """Собирает неделю строго проверенного пользователя."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        command = GetMyScheduleQuery(
            user_id=user.id, role=user.role.value, week_start=query.week_start
        )
        return await get_handler(request).handle(command)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid school week") from exc
    except (
        JournalUnavailableError,
        ScheduleUnavailableError,
        SQLAlchemyError,
        OSError,
    ) as exc:
        raise HTTPException(503, "Service unavailable") from exc


async def lesson_base(request: Request, user: GetCurrentUserResult, lesson_id: int):
    """Выбирает проверку ученика или учителя, не смешивая их права."""
    client = request.app.state.homework_client
    if client is None:
        raise HTTPException(503, "Service unavailable")
    if user.role == Role.STUDENT:
        return await client.get_student_lesson(student_id=user.id, lesson_id=lesson_id)
    return await client.get_teacher_lesson(teacher_id=user.id, lesson_id=lesson_id)


@router.get("/lessons/{lesson_id}", response_model=LessonViewResult)
async def lesson_view(
    request: Request,
    response: Response,
    lesson_id: Annotated[int, Path(ge=1, le=2147483647)],
    user: User,
) -> LessonViewResult:
    """Добавляет подписи только в новый view-контракт, сохраняя старый API."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        result = await lesson_base(request, user, lesson_id)
        lessons = [result.lesson] + ([result.next_lesson] if result.next_lesson else [])
        cards = await get_handler(request).enrich_lessons(lessons)
        return LessonViewResult(
            **result.model_dump(exclude={"lesson", "next_lesson"}),
            lesson=cards[0],
            next_lesson=cards[1] if len(cards) > 1 else None,
        )
    except HomeworkRequestError as exc:
        raise HTTPException(exc.status_code, "Lesson unavailable") from exc
    except (
        HomeworkUnavailableError,
        JournalUnavailableError,
        ScheduleUnavailableError,
        SQLAlchemyError,
        OSError,
    ) as exc:
        raise HTTPException(503, "Service unavailable") from exc
