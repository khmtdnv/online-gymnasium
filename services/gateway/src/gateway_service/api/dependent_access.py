"""Зависимость доступа родителя к данным конкретного ученика."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from gateway_service.api.security import get_authenticated_user
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.ports.unit_of_work import UnitOfWork
from gateway_service.domain.user import Role


async def check_dependent_access(
    viewer: GetCurrentUserResult, student_id: UUID, uow: UnitOfWork
) -> bool:
    """Проверяет право на данные ученика в рамках одной транзакции UoW.

    Родителю разрешены только ученики из `parent_student_links`;
    ученику — только собственные данные; админу — любые.

    Args:
        viewer: Активный пользователь после проверки JWT и БД Gateway.
        student_id: Ученик, к чьим данным запрашивается доступ.
        uow: Открытая транзакция Gateway для чтения связей.

    Returns:
        True, если доступ разрешён.
    """
    if viewer.role == Role.PARENT:
        return await uow.users.has_parent_student_link(viewer.id, student_id)
    return viewer.role == Role.ADMIN or (
        viewer.role == Role.STUDENT and viewer.id == student_id
    )


async def require_dependent_access(
    request: Request,
    viewer: Annotated[GetCurrentUserResult, Depends(get_authenticated_user)],
    student_id: Annotated[UUID, Query()],
) -> GetCurrentUserResult:
    """Проверяет право на данные ученика на каждый запрос дневника.

    Правила — общие с биллингом (см. `check_dependent_access`): родителю
    — по связи, ученику — свои данные, админу — любые.

    Args:
        request: Запрос с фабрикой UoW в состоянии приложения.
        viewer: Активный пользователь после проверки JWT и БД Gateway.
        student_id: Ученик, к чьим данным запрашивается доступ.

    Returns:
        Активный пользователь, прошедший проверку.

    Raises:
        HTTPException: 403 без права на данные ученика, 503 при сбое БД.
    """
    try:
        async with request.app.state.uow_factory() as uow:
            allowed = await check_dependent_access(viewer, student_id, uow)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "User data unavailable") from exc
    if not allowed:
        raise HTTPException(403, "Access denied")
    return viewer
