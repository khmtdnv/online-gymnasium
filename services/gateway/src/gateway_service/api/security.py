from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gateway_service.api.dependencies import get_current_user_handler
from gateway_service.application.auth import (
    GetCurrentUserCommand,
    GetCurrentUserHandler,
    GetCurrentUserResult,
)
from gateway_service.application.errors import AuthenticationError
from gateway_service.domain.user import Role

bearer_scheme = HTTPBearer(auto_error=False)


async def get_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    handler: Annotated[GetCurrentUserHandler, Depends(get_current_user_handler)],
) -> GetCurrentUserResult:
    """Проверяет access-токен и возвращает активного пользователя Gateway.

    Args:
        credentials: Bearer-токен из заголовка Authorization, если он передан.
        handler: Обработчик проверки токена и чтения пользователя из базы.

    Returns:
        Пользователь с актуальной ролью из базы Gateway.

    Raises:
        HTTPException: Токен отсутствует или непригоден либо пользователь
            отсутствует или неактивен; HTTP-статус 401.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token not provided",
            headers={"WWW-Authenticate": "Bearer"},
        )
    command = GetCurrentUserCommand(access_token=credentials.credentials)
    try:
        return await handler.handle(command)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token invalid or not provided",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


class RequireRoles:
    """Разрешает доступ только пользователям с явно перечисленными ролями."""

    def __init__(self, allowed_roles: tuple[Role, ...]) -> None:
        """Сохраняет разрешённые роли для этой проверки доступа.

        Args:
            allowed_roles: Разрешённые роли; пустой набор запрещает доступ всем.
        """
        self._allowed_roles = allowed_roles

    async def __call__(
        self,
        user: Annotated[GetCurrentUserResult, Depends(get_authenticated_user)],
    ) -> GetCurrentUserResult:
        """Проверяет актуальную роль уже аутентифицированного пользователя.

        Args:
            user: Активный пользователь, полученный общей dependency.

        Returns:
            Проверенный пользователь, если его роль разрешена.

        Raises:
            HTTPException: Роль пользователя не разрешена; HTTP-статус 403.
        """
        if user.role not in self._allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )

        return user


def check_auth_origin(request: Request) -> None:
    """Разрешает auth-запрос только из настроенного origin интерфейса.

    Args:
        request: HTTP-запрос с заголовками и настройками в app.state.

    Raises:
        HTTPException: Origin отсутствует, равен null или отличается
            от public_origin; HTTP-статус 403.
    """
    if request.headers.get("origin") != request.app.state.settings.public_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed"
        )
