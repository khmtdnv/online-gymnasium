"""Закрытая операция добавления ученика без автоматического перевода."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from journal_service.api.class_periods import ClassPeriodResponse
from journal_service.api.dependencies import get_add_student_to_class_handler
from journal_service.api.security import get_backoffice_actor_id
from journal_service.application.add_student_to_class import (
    AddStudentToClassCommand,
    AddStudentToClassHandler,
)

router = APIRouter(prefix="/internal", include_in_schema=False)


class AddStudentRequest(BaseModel):
    """Принимает только ID класса, не позволяя назначить служебные поля."""

    model_config = ConfigDict(extra="forbid")
    class_id: int = Field(strict=True, ge=1, le=2147483647)


@router.put(
    "/students/{student_id}/current-class-period", response_model=ClassPeriodResponse
)
async def add_student_to_class(
    student_id: UUID,
    request_model: AddStudentRequest,
    request: Request,
    response: Response,
    actor_id: Annotated[str, Depends(get_backoffice_actor_id)],
    handler: Annotated[
        AddStudentToClassHandler, Depends(get_add_student_to_class_handler)
    ],
) -> ClassPeriodResponse:
    """Добавляет ученика или возвращает его период в том же классе.

    Args:
        student_id: UUID ученика из адреса запроса.
        request_model: Проверенный ID целевого класса.
        request: Запрос с назначенным Journal идентификатором.
        response: Ответ, которому назначается статус создания или повтора.
        actor_id: ID сотрудника от доверенного Backoffice.
        handler: Обработчик с Gateway-reader и общей транзакцией записи.

    Returns:
        Пять полей периода; 201 при создании и 200 при повторе.
    """
    result = await handler.handle(
        AddStudentToClassCommand(
            student_id=student_id,
            class_id=request_model.class_id,
            actor_id=actor_id,
            request_id=request.state.request_id,
        )
    )
    response.status_code = 201 if result.created else 200
    return ClassPeriodResponse.from_result(result.period)
