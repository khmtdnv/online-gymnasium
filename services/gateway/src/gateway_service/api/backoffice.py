from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import ConfigDict, ValidationError

from gateway_service.api.dependencies import (
    get_create_user_handler,
    get_link_parent_student_handler,
    get_list_users_handler,
    require_backoffice_service_token,
)
from gateway_service.application.backoffice import (
    CreateUserCommand,
    CreateUserHandler,
    LinkParentStudentCommand,
    LinkParentStudentHandler,
    ListUsersHandler,
)
from gateway_service.application.errors import (
    EmailAlreadyExistsError,
    InvalidParentStudentRolesError,
    UserNotFoundError,
)
from gateway_service.application.user_profiles import UserNames
from gateway_service.domain.user import Role

router = APIRouter(
    prefix="/internal/backoffice",
    tags=["backoffice"],
    dependencies=[Depends(require_backoffice_service_token)],
    include_in_schema=False,
)


class CreateUserRequest(UserNames):
    """Email, открытый пароль и роль нового пользователя."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=False)

    email: str
    password: str
    role: Role


class UserResponse(UserNames):
    """Публичные данные пользователя без пароля и его хеша."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: UUID
    email: str
    role: Role
    is_active: bool


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_defaults=True,
)
async def create_user(
    request_model: CreateUserRequest,
    handler: Annotated[CreateUserHandler, Depends(get_create_user_handler)],
) -> UserResponse:
    """Создаёт пользователя через закрытую ручку Backoffice.

    Args:
        request_model: Проверенные данные тела HTTP-запроса.
        handler: Обработчик прикладного сценария.

    Returns:
        Безопасные данные пользователя; HTTP-статус 201.

    Raises:
        HTTPException: Email или пароль не заполнены (422), email уже занят (409).
    """
    try:
        command = CreateUserCommand(
            email=request_model.email,
            password=request_model.password,
            role=request_model.role,
            first_name=request_model.first_name,
            last_name=request_model.last_name,
            middle_name=request_model.middle_name,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Email and password must not be blank",
        ) from exc
    try:
        result = await handler.handle(command)
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        ) from exc

    return UserResponse(
        id=result.id,
        email=result.email,
        role=result.role,
        is_active=result.is_active,
        first_name=result.first_name,
        last_name=result.last_name,
        middle_name=result.middle_name,
    )


@router.get(
    "/users", response_model=list[UserResponse], response_model_exclude_defaults=True
)
async def list_users(
    handler: Annotated[ListUsersHandler, Depends(get_list_users_handler)],
) -> list[UserResponse]:
    """Возвращает пользователей через закрытую ручку Backoffice.

    Args:
        handler: Обработчик прикладного сценария.

    Returns:
        Список пользователей без хешей паролей.
    """
    result = await handler.handle()

    users_list = []
    for user in result:
        users_list.append(
            UserResponse(
                id=user.id,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
                first_name=user.first_name,
                last_name=user.last_name,
                middle_name=user.middle_name,
            )
        )

    return users_list


@router.put(
    "/parents/{parent_id}/children/{student_id}",
    status_code=status.HTTP_201_CREATED,
)
async def link_parent_student(
    parent_id: UUID,
    student_id: UUID,
    handler: Annotated[
        LinkParentStudentHandler, Depends(get_link_parent_student_handler)
    ],
) -> Response:
    """Создаёт связь родителя и ученика через закрытую ручку.

    Args:
        parent_id: ID пользователя с ролью родителя.
        student_id: ID пользователя с ролью ученика.
        handler: Обработчик прикладного сценария.

    Returns:
        Пустой ответ: 201 для новой связи, 204 для существующей.

    Raises:
        HTTPException: Пользователь не найден (404) или роли не подходят (422).
    """
    try:
        created = await handler.handle(
            LinkParentStudentCommand(parent_id=parent_id, student_id=student_id)
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User was not found",
        ) from exc
    except InvalidParentStudentRolesError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Users must have parent and student roles",
        ) from exc

    return Response(
        status_code=(status.HTTP_201_CREATED if created else status.HTTP_204_NO_CONTENT)
    )
