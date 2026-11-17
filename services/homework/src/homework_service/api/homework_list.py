"""Закрытое чтение личной страницы ДЗ по срокам."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from homework_service.api.dependencies import require_gateway
from homework_service.api.errors import HomeworkHTTPError, unavailable
from homework_service.application.homework_list import (
    HomeworkPageResult,
    ListMyHomeworkQuery,
)
from homework_service.application.ports.errors import OwnerLookupUnavailableError

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_gateway)])


class HomeworkPeriod(BaseModel):
    """Период и фильтр, без возможности выбрать чужого ученика."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    date_from: date
    date_to: date
    state: Literal["all", "needs_action", "submitted", "returned", "graded"] = "all"
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)


@router.get("/internal/student-homework-view", response_model=HomeworkPageResult)
async def list_my_homework(
    request: Request,
    query: Annotated[HomeworkPeriod, Query()],
    student_id: Annotated[UUID, Header(alias="X-Student-ID")],
) -> HomeworkPageResult:
    """Сохраняет стабильный422 для неверного/слишком большого периода,503 для сбоя."""
    handler = request.app.state.list_my_homework_handler
    if handler is None:
        raise unavailable()
    try:
        return await handler.handle(
            ListMyHomeworkQuery(student_id=student_id, **query.model_dump())
        )
    except (ValidationError, ValueError) as exc:
        raise HomeworkHTTPError(
            422, "invalid_homework_data", "Invalid or too large homework period"
        ) from exc
    except (OwnerLookupUnavailableError, SQLAlchemyError, OSError) as exc:
        raise unavailable() from exc
