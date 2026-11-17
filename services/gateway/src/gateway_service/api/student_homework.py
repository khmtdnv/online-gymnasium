"""Публичные чтения ДЗ для активного ученика."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from gateway_service.api.homework import get_homework_client
from gateway_service.api.security import RequireRoles
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkUnavailableError,
    StudentHomeworkResult,
)
from gateway_service.domain.user import Role
from gateway_service.infrastructure.homework_client import HomeworkClient

router = APIRouter(prefix="/api/v1/homework", tags=["homework"])
student_only = RequireRoles(allowed_roles=(Role.STUDENT,))


class HomeworkPagination(BaseModel):
    """Разрешает только страницу; UUID и класс пользователь не выбирает."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)


@router.get("", response_model=list[StudentHomeworkResult])
async def list_student_homework(
    pagination: Annotated[HomeworkPagination, Query()],
    student: Annotated[GetCurrentUserResult, Depends(student_only)],
    client: Annotated[HomeworkClient, Depends(get_homework_client)],
) -> list[StudentHomeworkResult]:
    """Передаёт владельцу заданий UUID проверенного ученика.

    Args:
        pagination: Проверенные limit и offset.
        student: Активный пользователь с актуальной ролью student.
        client: Клиент закрытых ручек Homework.

    Returns:
        Страница ДЗ текущего класса.

    Raises:
        HTTPException: Homework недоступен или нарушил контракт503.
    """
    try:
        return await client.list_student_homework(
            student_id=student.id,
            limit=pagination.limit,
            offset=pagination.offset,
        )
    except HomeworkUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc


@router.get("/{homework_id}", response_model=StudentHomeworkResult)
async def get_student_homework(
    homework_id: Annotated[int, Path(ge=1, le=2147483647)],
    student: Annotated[GetCurrentUserResult, Depends(student_only)],
    client: Annotated[HomeworkClient, Depends(get_homework_client)],
) -> StudentHomeworkResult:
    """Читает отдельное ДЗ с проверкой текущего класса внутри Homework.

    Args:
        homework_id: ID запрошенного задания.
        student: Аутентифицированный активный ученик.
        client: Клиент Homework.

    Returns:
        Доступное задание с актуальным сроком.

    Raises:
        HTTPException: Нет доступного задания404 или зависимость недоступна503.
    """
    try:
        return await client.get_student_homework(
            student_id=student.id, homework_id=homework_id
        )
    except HomeworkRequestError as exc:
        raise HTTPException(404, "Homework not found") from exc
    except HomeworkUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc
