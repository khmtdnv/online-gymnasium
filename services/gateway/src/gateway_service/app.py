import logging
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.exceptions import HTTPException as StarletteHTTPException

from gateway_service.api.router import router
from gateway_service.application.ports.password_service import PasswordService
from gateway_service.application.ports.token_service import TokenService
from gateway_service.application.ports.unit_of_work import UnitOfWork
from gateway_service.config import GatewaySettings
from gateway_service.infrastructure.homework_client import HomeworkClient
from gateway_service.infrastructure.schedule_client import ScheduleClient

logger = logging.getLogger(__name__)


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Собирает единый JSON-ответ ошибки с ID запроса.

    Сохраняет переданные заголовки; X-Request-ID берёт из текущего запроса.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.
        status_code: HTTP-статус ответа ошибки.
        code: Машиночитаемый код ошибки для клиента.
        message: Безопасное описание ошибки для клиента.
        headers: Заголовки исходной HTTP-ошибки, которые нужно сохранить.

    Returns:
        Ответ с кодом, сообщением и X-Request-ID.
    """
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
        headers={**(headers or {}), "X-Request-ID": request_id},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Закрывает ресурсы приложения при завершении HTTP-процесса.

    Args:
        app: Приложение с ресурсами и зависимостями в app.state.
    """
    try:
        async with AsyncExitStack() as stack:
            settings = app.state.settings
            if app.state.homework_client is None and all(
                (
                    settings.homework_base_url,
                    settings.homework_service_token,
                )
            ):
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=settings.homework_base_url,
                        timeout=5.0,
                        follow_redirects=False,
                    )
                )
                app.state.homework_client = HomeworkClient(
                    http_client, settings.homework_service_token
                )
            if app.state.schedule_client is None and all(
                (settings.schedule_base_url, settings.schedule_service_token)
            ):
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=settings.schedule_base_url,
                        timeout=5.0,
                        follow_redirects=False,
                    )
                )
                app.state.schedule_client = ScheduleClient(
                    http_client, settings.schedule_service_token
                )
            yield
    finally:
        app.state.homework_client = app.state.injected_homework_client
        app.state.schedule_client = app.state.injected_schedule_client
        await app.state.engine.dispose()


def create_app(
    settings: GatewaySettings,
    engine: AsyncEngine,
    uow_factory: Callable[[], UnitOfWork],
    password_service: PasswordService,
    token_service: TokenService,
    *,
    homework_client: HomeworkClient | None = None,
    schedule_client: ScheduleClient | None = None,
) -> FastAPI:
    """Собирает HTTP-приложение с переданными зависимостями.

    Args:
        settings: Настройки текущего сервиса.
        engine: Объект SQLAlchemy для соединений с базой.
        uow_factory: Фабрика отдельной транзакции с её репозиториями.
        password_service: Сервис создания и проверки хешей паролей.
        token_service: Сервис проверки и выпуска JWT.
        homework_client: Подмена клиента; иначе собирается при старте из настроек.
        schedule_client: Подмена клиента Schedule; иначе собирается в lifespan.

    Returns:
        Приложение FastAPI с маршрутами и зависимостями в app.state.
    """
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    @app.middleware("http")
    async def assign_request_id(request: Request, call_next):
        """Назначает запросу ID и добавляет его в заголовок ответа.

        Args:
            request: HTTP-запрос с зависимостями приложения в app.state.
            call_next: Следующий обработчик HTTP-запроса.

        Returns:
            Ответ следующего обработчика с X-Request-ID.
        """
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        """Переводит HTTP-исключение в единый формат и сохраняет его заголовки.

        Args:
            request: HTTP-запрос с зависимостями приложения в app.state.
            exc: Исключение, которое нужно обработать, если оно возникло.

        Returns:
            JSON-ответ с исходным HTTP-статусом.
        """
        codes = {
            401: "authentication_error",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
        }
        message = (
            exc.detail
            if isinstance(exc.detail, str) and exc.status_code < 500
            else "Request failed"
        )
        return _error_response(
            request,
            status_code=exc.status_code,
            code=codes.get(exc.status_code, "http_error"),
            message=message,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        """Возвращает единый ответ для ошибки проверки входящего запроса.

        Args:
            request: HTTP-запрос с зависимостями приложения в app.state.
            exc: Исключение, которое нужно обработать, если оно возникло.

        Returns:
            JSON-ответ validation_error с HTTP-статусом 422.
        """
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        """Записывает непредвиденную ошибку в лог, скрывая детали от клиента.

        Args:
            request: HTTP-запрос с зависимостями приложения в app.state.
            exc: Исключение, которое нужно обработать, если оно возникло.

        Returns:
            Безопасный JSON-ответ internal_error с HTTP-статусом 500.
        """
        logger.exception(
            "Unhandled Gateway error request_id=%s", request.state.request_id
        )
        return _error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Internal server error",
        )

    app.include_router(router)
    app.state.settings = settings
    app.state.engine = engine
    app.state.uow_factory = uow_factory
    app.state.password_service = password_service
    app.state.token_service = token_service
    app.state.homework_client = homework_client
    app.state.injected_homework_client = homework_client
    app.state.schedule_client = schedule_client
    app.state.injected_schedule_client = schedule_client

    return app
