"""Внутренние HTTP-чтения периодов учеников и текущего состава класса."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from journal_service.api.dependencies import (
    get_current_period_for_student_handler,
    get_list_current_periods_for_class_handler,
    get_list_periods_for_student_handler,
)
from journal_service.api.security import RequireServicePermission
from journal_service.application.class_periods import (
    MAX_CLASS_ID,
    MAX_PERIOD_OFFSET,
    ClassPeriodResult,
    GetCurrentPeriodForStudentHandler,
    GetCurrentPeriodForStudentQuery,
    ListCurrentPeriodsForClassHandler,
    ListCurrentPeriodsForClassQuery,
    ListPeriodsForStudentHandler,
    ListPeriodsForStudentQuery,
)

router = APIRouter(
    prefix="/internal",
    include_in_schema=False,
)


class ClassPeriodResponse(BaseModel):
    """Возвращает ID ученика и границы периода без данных его учётной записи."""

    id: int
    student_id: UUID
    class_id: int
    joined_at: datetime
    left_at: datetime | None

    @classmethod
    def from_result(cls, result: ClassPeriodResult) -> ClassPeriodResponse:
        """Преобразует прикладной результат в проверенную HTTP-модель.

        Args:
            result: Данные периода после завершения Unit of Work.

        Returns:
            Ответ с явно выбранными публичными полями.
        """
        return cls(
            id=result.id,
            student_id=result.student_id,
            class_id=result.class_id,
            joined_at=result.joined_at,
            left_at=result.left_at,
        )


@router.get(
    "/students/{student_id}/current-class-period",
    response_model=ClassPeriodResponse,
    dependencies=[Depends(RequireServicePermission("student-current-class:read"))],
)
async def get_current_period_for_student(
    student_id: UUID,
    handler: Annotated[
        GetCurrentPeriodForStudentHandler,
        Depends(get_current_period_for_student_handler),
    ],
) -> ClassPeriodResponse:
    """Получает текущий период ученика; отсутствие периода даёт 404.

    Args:
        student_id: UUID ученика из адреса запроса.
        handler: Обработчик текущего периода.

    Returns:
        Открытый период ученика, не данные его учётной записи.
    """
    try:
        result = await handler.handle(
            GetCurrentPeriodForStudentQuery(student_id=student_id)
        )
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Journal unavailable") from exc
    return ClassPeriodResponse.from_result(result)


@router.get(
    "/students/{student_id}/class-periods",
    response_model=list[ClassPeriodResponse],
    dependencies=[Depends(RequireServicePermission("classes:read"))],
)
async def list_periods_for_student(
    student_id: UUID,
    handler: Annotated[
        ListPeriodsForStudentHandler, Depends(get_list_periods_for_student_handler)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=MAX_PERIOD_OFFSET)] = 0,
) -> list[ClassPeriodResponse]:
    """Получает страницу истории классов ученика, включая текущий период.

    Args:
        student_id: UUID ученика из адреса запроса.
        handler: Обработчик истории ученика.
        limit: Максимальное число периодов в ответе.
        offset: Число пропускаемых периодов.

    Returns:
        История от старых к новым; пустой список, если записей нет.
    """
    results = await handler.handle(
        ListPeriodsForStudentQuery(student_id=student_id, limit=limit, offset=offset)
    )
    return [ClassPeriodResponse.from_result(result) for result in results]


@router.get(
    "/classes/{class_id}/current-periods",
    response_model=list[ClassPeriodResponse],
    dependencies=[Depends(RequireServicePermission("classes:read"))],
)
async def list_current_periods_for_class(
    class_id: Annotated[int, Path(ge=1, le=MAX_CLASS_ID)],
    handler: Annotated[
        ListCurrentPeriodsForClassHandler,
        Depends(get_list_current_periods_for_class_handler),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=MAX_PERIOD_OFFSET)] = 0,
) -> list[ClassPeriodResponse]:
    """Получает страницу текущего состава; неизвестный класс даёт 404.

    Args:
        class_id: Положительный ID класса в диапазоне PostgreSQL INTEGER.
        handler: Обработчик состава класса.
        limit: Максимальное число периодов в ответе.
        offset: Число пропускаемых открытых периодов.

    Returns:
        Открытые периоды по возрастанию ID; пустой список для пустой страницы.
    """
    results = await handler.handle(
        ListCurrentPeriodsForClassQuery(class_id=class_id, limit=limit, offset=offset)
    )
    return [ClassPeriodResponse.from_result(result) for result in results]
