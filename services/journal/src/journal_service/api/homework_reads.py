"""Минимальное чтение пары преподаватель—класс без прав на изменение."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.exc import SQLAlchemyError

from journal_service.api.security import RequireServicePermission
from journal_service.application.homework_reads import (
    CheckTeacherClassHandler,
    TeacherClassQuery,
)

router = APIRouter(
    prefix="/internal/teachers",
    include_in_schema=False,
    dependencies=[Depends(RequireServicePermission("teacher-classes:read"))],
)


@router.get("/{teacher_id}/classes/{class_id}", response_model=TeacherClassQuery)
async def get_teacher_assignment(
    teacher_id: UUID,
    class_id: Annotated[int, Path(ge=1, le=2147483647)],
    request: Request,
) -> TeacherClassQuery:
    """Подтверждает конкретную связь или сообщает об её отсутствии.

    Args:
        teacher_id: UUID учителя из адреса.
        class_id: ID класса из адреса.
        request: Запрос с фабрикой UoW в состоянии приложения.

    Returns:
        Проверенная пара, найденная в Journal.

    Raises:
        HTTPException: Назначение отсутствует (404) или БД недоступна (503).
    """
    query = TeacherClassQuery(teacher_id=teacher_id, class_id=class_id)
    try:
        assigned = await CheckTeacherClassHandler(request.app.state.uow_factory).handle(
            query
        )
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Journal unavailable") from exc
    if not assigned:
        raise HTTPException(status_code=404, detail="Teacher assignment not found")
    return query
