"""Служебные HTTP-команды перевода и завершения периода ученика."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from journal_service.api.class_periods import ClassPeriodResponse
from journal_service.api.dependencies import (
    get_end_student_class_period_handler,
    get_transfer_student_to_class_handler,
)
from journal_service.api.security import get_backoffice_actor_id
from journal_service.application.class_periods import MAX_CLASS_ID
from journal_service.application.end_student_class_period import (
    EndStudentClassPeriodCommand,
    EndStudentClassPeriodHandler,
)
from journal_service.application.transfer_student_to_class import (
    TransferStudentToClassCommand,
    TransferStudentToClassHandler,
)

router = APIRouter(prefix="/internal", include_in_schema=False)


class TransferStudentRequest(BaseModel):
    """Принимает целевой класс и исходный период без подмены служебных полей."""

    model_config = ConfigDict(extra="forbid", strict=True)

    target_class_id: int = Field(ge=1, le=MAX_CLASS_ID)
    expected_period_id: int = Field(ge=1, le=MAX_CLASS_ID)


@router.post(
    "/students/{student_id}/current-class-period/transfer",
    response_model=ClassPeriodResponse,
)
async def transfer_student_to_class(
    student_id: UUID,
    request_model: TransferStudentRequest,
    request: Request,
    actor_id: Annotated[str, Depends(get_backoffice_actor_id)],
    handler: Annotated[
        TransferStudentToClassHandler, Depends(get_transfer_student_to_class_handler)
    ],
) -> ClassPeriodResponse:
    """Переводит из ожидаемого периода; устаревшее состояние даёт409.

    Args:
        student_id: UUID ученика из URL.
        request_model: Целевой класс и ожидаемый исходный период.
        request: Запрос с серверным request_id.
        actor_id: Сотрудник доверенного сервиса с правом записи.
        handler: Сценарий перевода с Gateway-reader и UoW.

    Returns:
        Новый период либо текущий при переводе в тот же класс.
    """
    result = await handler.handle(
        TransferStudentToClassCommand(
            student_id=student_id,
            target_class_id=request_model.target_class_id,
            expected_period_id=request_model.expected_period_id,
            actor_id=actor_id,
            request_id=request.state.request_id,
        )
    )
    return ClassPeriodResponse.from_result(result)


@router.delete(
    "/students/{student_id}/current-class-period",
    status_code=204,
    response_class=Response,
)
async def end_student_class_period(
    student_id: UUID,
    request: Request,
    expected_period_id: Annotated[int, Query(ge=1, le=MAX_CLASS_ID)],
    actor_id: Annotated[str, Depends(get_backoffice_actor_id)],
    handler: Annotated[
        EndStudentClassPeriodHandler, Depends(get_end_student_class_period_handler)
    ],
) -> Response:
    """Завершает ожидаемый период без зависимости от доступности Gateway.

    Args:
        student_id: UUID ученика из URL.
        request: Запрос с серверным request_id.
        expected_period_id: ID исходного периода из формы.
        actor_id: Проверенный ID сотрудника Backoffice.
        handler: Обработчик завершения в одной транзакции.

    Returns:
        Пустой204 после закрытия либо при отсутствии открытого периода.
    """
    await handler.handle(
        EndStudentClassPeriodCommand(
            student_id=student_id,
            expected_period_id=expected_period_id,
            actor_id=actor_id,
            request_id=request.state.request_id,
        )
    )
    return Response(status_code=204)
