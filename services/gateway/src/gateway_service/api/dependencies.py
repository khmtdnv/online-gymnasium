import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gateway_service.application.auth import (
    GetCurrentUserHandler,
    LoginHandler,
    LogoutHandler,
    RefreshHandler,
)
from gateway_service.application.backoffice import (
    CreateUserHandler,
    LinkParentStudentHandler,
    ListUsersHandler,
)
from gateway_service.application.user_lookup import GetUserHandler

journal_bearer_scheme = HTTPBearer(auto_error=False)


def get_user_handler(request: Request) -> GetUserHandler:
    """Собирает чтение пользователя для межсервисного запроса.

    Args:
        request: Запрос с фабрикой UoW в app.state.

    Returns:
        Обработчик минимального чтения пользователя.
    """
    return GetUserHandler(uow_factory=request.app.state.uow_factory)


def require_journal_service_token(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(journal_bearer_scheme)
    ],
) -> None:
    """Проверяет отдельный служебный секрет Journal, а не JWT пользователя.

    Args:
        request: Запрос с настройками служебного доступа.
        credentials: Bearer-секрет из заголовка Authorization, если он передан.

    Raises:
        HTTPException: Доступ не настроен (503) или секрет не подходит (401).
    """
    expected_token = request.app.state.settings.journal_service_token
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unavailable",
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"), expected_token.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_login_handler(request: Request) -> LoginHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    return LoginHandler(
        uow_factory=request.app.state.uow_factory,
        password_service=request.app.state.password_service,
        token_service=request.app.state.token_service,
    )


def get_refresh_handler(request: Request) -> RefreshHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    return RefreshHandler(
        uow_factory=request.app.state.uow_factory,
        token_service=request.app.state.token_service,
    )


def get_current_user_handler(request: Request) -> GetCurrentUserHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    return GetCurrentUserHandler(
        uow_factory=request.app.state.uow_factory,
        token_service=request.app.state.token_service,
    )


def require_backoffice_service_token(
    request: Request,
    x_backoffice_service_token: Annotated[str | None, Header()] = None,
) -> None:
    """Проверяет служебный токен закрытых ручек Backoffice.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.
        x_backoffice_service_token: Служебный токен из заголовка
            X-Backoffice-Service-Token.

    Raises:
        HTTPException: Заголовок отсутствует или токен неверен; HTTP-статус 403.
    """
    expected_token = request.app.state.settings.backoffice_service_token

    if not x_backoffice_service_token or not secrets.compare_digest(
        x_backoffice_service_token, expected_token
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid backoffice service token",
        )


def get_create_user_handler(request: Request) -> CreateUserHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    return CreateUserHandler(
        uow_factory=request.app.state.uow_factory,
        password_service=request.app.state.password_service,
    )


def get_list_users_handler(request: Request) -> ListUsersHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    return ListUsersHandler(uow_factory=request.app.state.uow_factory)


def get_link_parent_student_handler(request: Request) -> LinkParentStudentHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    return LinkParentStudentHandler(uow_factory=request.app.state.uow_factory)


def get_logout_handler(request: Request) -> LogoutHandler:
    """Собирает обработчик выхода из зависимостей приложения.

    Args:
        request: HTTP-запрос с фабрикой UoW и сервисом токенов в app.state.

    Returns:
        Обработчик отзыва текущего refresh-токена.
    """
    return LogoutHandler(
        uow_factory=request.app.state.uow_factory,
        token_service=request.app.state.token_service,
    )
