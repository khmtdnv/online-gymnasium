"""Закрытое чтение пользователей для Journal."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from gateway_service.api.dependencies import (
    get_user_handler,
    require_journal_service_token,
)
from gateway_service.application.errors import UserNotFoundError
from gateway_service.application.user_lookup import GetUserHandler, GetUserQuery
from gateway_service.domain.user import Role

router = APIRouter(
    prefix="/internal/users",
    dependencies=[Depends(require_journal_service_token)],
    include_in_schema=False,
)


class UserLookupResponse(BaseModel):
    """Минимальный HTTP-ответ без приватных данных пользователя."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: UUID
    role: Role
    is_active: bool


@router.get("/{user_id}", response_model=UserLookupResponse)
async def get_user(
    user_id: UUID,
    handler: Annotated[GetUserHandler, Depends(get_user_handler)],
) -> UserLookupResponse:
    """Читает пользователя после проверки служебного доступа Journal.

    Args:
        user_id: ID продуктового пользователя из Gateway.
        handler: Обработчик чтения через отдельный Unit of Work.

    Returns:
        ID, роль и активность пользователя без административных изменений.

    Raises:
        HTTPException: Пользователь отсутствует; HTTP-статус 404.
    """
    try:
        result = await handler.handle(GetUserQuery(user_id=user_id))
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc
    return UserLookupResponse(
        id=result.id, role=result.role, is_active=result.is_active
    )
