from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, ConfigDict

from gateway_service.api.cookies import clear_refresh_cookie, set_refresh_cookie
from gateway_service.api.dependencies import (
    get_login_handler,
    get_logout_handler,
    get_refresh_handler,
)
from gateway_service.api.security import check_auth_origin, get_authenticated_user
from gateway_service.application.auth import (
    GetCurrentUserResult,
    LoginCommand,
    LoginHandler,
    LogoutCommand,
    LogoutHandler,
    RefreshCommand,
    RefreshHandler,
)
from gateway_service.application.errors import AuthenticationError
from gateway_service.domain.user import Role

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Email и открытый пароль для проверки входа."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    email: str
    password: str


class LoginResponse(BaseModel):
    """Access-токен для HTTP-ответа; refresh-токен передаётся в cookie."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    access_token: str


@router.post(
    "/login", response_model=LoginResponse, dependencies=[Depends(check_auth_origin)]
)
async def login(
    request: Request,
    request_model: LoginRequest,
    handler: Annotated[LoginHandler, Depends(get_login_handler)],
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
):
    """Проверяет вход и записывает refresh-токен в HttpOnly-cookie.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.
        request_model: Проверенные данные тела HTTP-запроса.
        handler: Обработчик прикладного сценария.
        response: HTTP-ответ, в который нужно записать cookie.

    Returns:
        Access-токен в теле ответа.

    Raises:
        HTTPException: Неверные учётные данные; HTTP-статус 401.
            Проверка Origin в dependency может отклонить запрос с HTTP 403.
    """
    command = LoginCommand(
        email=request_model.email,
        password=request_model.password,
        previous_refresh_token=refresh_token,
    )
    try:
        result = await handler.handle(command)
        set_refresh_cookie(
            response=response,
            token=result.refresh_token,
            max_age=request.app.state.settings.refresh_token_ttl_seconds,
            secure=request.app.state.settings.refresh_cookie_secure,
        )
        return LoginResponse(access_token=result.access_token)

    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        ) from exc


class RefreshResponse(BaseModel):
    """Access-токен для HTTP-ответа; refresh-токен передаётся в cookie."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    access_token: str


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    dependencies=[Depends(check_auth_origin)],
)
async def refresh(
    request: Request,
    handler: Annotated[RefreshHandler, Depends(get_refresh_handler)],
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
):
    """Заменяет refresh-cookie и выдаёт новый access-токен.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.
        handler: Обработчик прикладного сценария.
        response: HTTP-ответ, в который нужно записать cookie.
        refresh_token: Refresh-токен из cookie, если он передан.

    Returns:
        Новый access-токен в теле ответа.

    Raises:
        HTTPException: Refresh-токен отсутствует или непригоден; HTTP-статус 401.
            Проверка Origin в dependency может отклонить запрос с HTTP 403.
    """
    try:
        if not refresh_token:
            raise AuthenticationError

        command = RefreshCommand(refresh_token=refresh_token)
        result = await handler.handle(command)
        set_refresh_cookie(
            response=response,
            token=result.refresh_token,
            max_age=request.app.state.settings.refresh_token_ttl_seconds,
            secure=request.app.state.settings.refresh_cookie_secure,
        )
        return RefreshResponse(access_token=result.access_token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc


class GetCurrentUserResponse(BaseModel):
    """Текущие ID, email и роль активного пользователя."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: UUID
    email: str
    role: Role


@router.get("/me", response_model=GetCurrentUserResponse)
async def get_current_user(
    user: Annotated[GetCurrentUserResult, Depends(get_authenticated_user)],
) -> GetCurrentUserResponse:
    """Возвращает текущего пользователя по Bearer access-токену.

    Args:
        user: Проверенный активный пользователь.

    Returns:
        ID, email и роль пользователя.

    Raises:
        HTTPException: Токен отсутствует или непригоден; HTTP-статус 401.
    """

    return GetCurrentUserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(check_auth_origin)],
)
async def logout(
    request: Request,
    response: Response,
    handler: Annotated[LogoutHandler, Depends(get_logout_handler)],
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> None:
    """Отзывает текущий refresh-токен и удаляет его cookie.

    Отсутствующий или непригодный токен не мешает повторному выходу.
    При сбое хранилища ошибка передаётся выше: успешный отзыв не подтверждён.

    Args:
        request: HTTP-запрос с настройками cookie в app.state.
        response: HTTP-ответ для удаления refresh-cookie с исходным path.
        handler: Обработчик отзыва текущего refresh-токена.
        refresh_token: Refresh-токен из cookie, если он передан.

    Raises:
        HTTPException: Проверка Origin в dependency отклонила запрос; HTTP 403.
    """
    if refresh_token:
        command = LogoutCommand(refresh_token=refresh_token)
        await handler.handle(command)

    clear_refresh_cookie(
        response=response, secure=request.app.state.settings.refresh_cookie_secure
    )
