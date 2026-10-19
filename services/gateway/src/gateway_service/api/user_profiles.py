"""Закрытые ручки поиска и редактирования ФИО для Backoffice."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field, ValidationError

from gateway_service.api.dependencies import require_backoffice_service_token
from gateway_service.application.errors import UserNotFoundError
from gateway_service.application.user_profiles import (
    NamePart,
    SearchUsersQuery,
    UpdateUserNameCommand,
    UserNames,
    UserProfile,
    UserProfilesHandler,
)
from gateway_service.domain.user import Role

router = APIRouter(
    prefix="/internal/backoffice/users",
    include_in_schema=False,
    dependencies=[Depends(require_backoffice_service_token)],
)


class UpdateUserNameRequest(UserNames):
    """Полное новое ФИО; отчество можно очистить пустой строкой."""

    first_name: NamePart = Field(min_length=1)
    last_name: NamePart = Field(min_length=1)


def get_profiles_handler(request: Request) -> UserProfilesHandler:
    """Собирает обработчик с фабрикой транзакций приложения."""
    return UserProfilesHandler(request.app.state.uow_factory)


@router.get("/search", response_model=list[UserProfile])
async def search_users(
    handler: Annotated[UserProfilesHandler, Depends(get_profiles_handler)],
    q: Annotated[str, Query(min_length=2, max_length=200)],
    role: Role | None = None,
    active_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[UserProfile]:
    """Ищет ФИО и email; неверные параметры дают 422 до обращения к БД."""
    try:
        query = SearchUsersQuery(q=q, role=role, active_only=active_only, limit=limit)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid search query") from exc
    return await handler.search(query)


@router.get("/{user_id}", response_model=UserProfile)
async def get_profile(
    user_id: UUID,
    handler: Annotated[UserProfilesHandler, Depends(get_profiles_handler)],
) -> UserProfile:
    """Читает безопасные данные пользователя; отсутствующий ID даёт 404."""
    try:
        return await handler.get(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(404, "User not found") from exc


@router.put("/{user_id}/name", response_model=UserProfile)
async def update_name(
    user_id: UUID,
    body: UpdateUserNameRequest,
    handler: Annotated[UserProfilesHandler, Depends(get_profiles_handler)],
) -> UserProfile:
    """Обновляет только ФИО; роль, пароль и email этой ручкой изменить нельзя."""
    try:
        return await handler.update_name(
            UpdateUserNameCommand(user_id=user_id, **body.model_dump())
        )
    except UserNotFoundError as exc:
        raise HTTPException(404, "User not found") from exc
