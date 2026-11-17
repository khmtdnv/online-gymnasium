"""Публичная личная страница ДЗ, только для ученика из JWT."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from gateway_service.api.security import RequireRoles
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.homework import HomeworkUnavailableError
from gateway_service.application.homework_list import (
    HomeworkPageResult,
    HomeworkPeriod,
    ListMyHomeworkHandler,
    ListMyHomeworkQuery,
)
from gateway_service.application.teacher_lessons import ScheduleUnavailableError
from gateway_service.domain.user import Role

router = APIRouter(prefix="/api/v1/my-homework", tags=["personal homework"])


@router.get("", response_model=HomeworkPageResult)
async def my_homework(
    request: Request,
    response: Response,
    query: Annotated[HomeworkPeriod, Query()],
    user: Annotated[GetCurrentUserResult, Depends(RequireRoles((Role.STUDENT,)))],
) -> HomeworkPageResult:
    """Не даёт передать student_id/class_id и не отдаёт личные результаты в кеш."""
    response.headers["Cache-Control"] = "private, no-store"
    if (
        request.app.state.homework_client is None
        or request.app.state.schedule_client is None
    ):
        raise HTTPException(503, "Service unavailable")
    try:
        return await ListMyHomeworkHandler(
            request.app.state.uow_factory,
            request.app.state.homework_client,
            request.app.state.schedule_client,
        ).handle(ListMyHomeworkQuery(student_id=user.id, **query.model_dump()))
    except (
        HomeworkUnavailableError,
        ScheduleUnavailableError,
        SQLAlchemyError,
        OSError,
    ) as exc:
        raise HTTPException(503, "Service unavailable") from exc
