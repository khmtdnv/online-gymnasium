"""Закрытые чтения ДЗ от доверенного Gateway."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from homework_service.api.dependencies import require_gateway
from homework_service.api.errors import HomeworkHTTPError, unavailable
from homework_service.application.ports.errors import (
    HomeworkNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.application.student_reads import (
    GetStudentHomeworkHandler,
    GetStudentHomeworkQuery,
    ListStudentHomeworkHandler,
    ListStudentHomeworkQuery,
    StudentHomeworkResult,
)

router = APIRouter(
    prefix="/internal/homework",
    include_in_schema=False,
    dependencies=[Depends(require_gateway)],
)


class HomeworkPagination(BaseModel):
    """Разрешает только limit/offset, не выбор другого ученика или класса."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)


def get_list_handler(request: Request) -> ListStudentHomeworkHandler:
    """Возвращает чтение страницы; отсутствие настроек не означает пустой список."""
    handler = request.app.state.list_student_homework_handler
    if handler is None:
        raise unavailable()
    return handler


def get_one_handler(request: Request) -> GetStudentHomeworkHandler:
    """Возвращает чтение задания либо 503 при неполной настройке."""
    handler = request.app.state.get_student_homework_handler
    if handler is None:
        raise unavailable()
    return handler


@router.get("", response_model=list[StudentHomeworkResult])
async def list_student_homework(
    student_id: Annotated[UUID, Header(alias="X-Student-ID")],
    pagination: Annotated[HomeworkPagination, Query()],
    handler: Annotated[ListStudentHomeworkHandler, Depends(get_list_handler)],
) -> list[StudentHomeworkResult]:
    """Читает страницу текущего класса после служебной аутентификации.

    Args:
        student_id: UUID, сформированный Gateway, не query-параметр.
        pagination: Размер страницы и смещение.
        handler: Сценарий проверки класса и разрешения сроков.

    Returns:
        Доступная страница, включая пустую.

    Raises:
        HomeworkHTTPError: Недоступен владелец или своя БД.
    """
    try:
        return await handler.handle(
            ListStudentHomeworkQuery(
                student_id=student_id,
                limit=pagination.limit,
                offset=pagination.offset,
            )
        )
    except (OwnerLookupUnavailableError, SQLAlchemyError, OSError) as exc:
        raise unavailable() from exc


@router.get("/{homework_id}", response_model=StudentHomeworkResult)
async def get_student_homework(
    homework_id: Annotated[int, Path(ge=1, le=2147483647)],
    student_id: Annotated[UUID, Header(alias="X-Student-ID")],
    handler: Annotated[GetStudentHomeworkHandler, Depends(get_one_handler)],
) -> StudentHomeworkResult:
    """Проверяет класс даже для прямого обращения к ID задания.

    Args:
        homework_id: ID задания.
        student_id: Доверенный UUID ученика.
        handler: Сценарий проверки доступа и срока.

    Returns:
        Одно доступное задание.

    Raises:
        HomeworkHTTPError: Нет доступного задания404 или зависимость недоступна503.
    """
    try:
        return await handler.handle(
            GetStudentHomeworkQuery(
                student_id=student_id,
                homework_id=homework_id,
            )
        )
    except HomeworkNotFoundError as exc:
        raise HomeworkHTTPError(
            404, "homework_not_found", "Homework not found"
        ) from exc
    except (OwnerLookupUnavailableError, SQLAlchemyError, OSError) as exc:
        raise unavailable() from exc
