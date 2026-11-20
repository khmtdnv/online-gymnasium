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
from gateway_service.application.homework import HomeworkRequestError
from gateway_service.application.ports.password_service import PasswordService
from gateway_service.application.ports.token_service import TokenService
from gateway_service.application.ports.unit_of_work import UnitOfWork
from gateway_service.config import GatewaySettings
from gateway_service.infrastructure.analytics_client import AnalyticsClient
from gateway_service.infrastructure.billing_client import BillingClient
from gateway_service.infrastructure.document_client import DocumentClient
from gateway_service.infrastructure.homework_client import HomeworkClient
from gateway_service.infrastructure.homework_file_client import HomeworkFileClient
from gateway_service.infrastructure.journal_client import JournalClient
from gateway_service.infrastructure.login_throttle import LoginThrottle
from gateway_service.infrastructure.notification_client import NotificationClient
from gateway_service.infrastructure.pen_client import PenClient
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
            if (
                app.state.notifications_client is None
                and settings.notifications_base_url
                and settings.notifications_service_token
            ):
                notification_http = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=settings.notifications_base_url,
                        timeout=5.0,
                        follow_redirects=False,
                        limits=httpx.Limits(
                            max_connections=5, max_keepalive_connections=5
                        ),
                    )
                )
                app.state.notifications_client = NotificationClient(
                    notification_http, settings.notifications_service_token
                )
            if (
                app.state.documents_client is None
                and settings.documents_base_url
                and settings.documents_service_token
            ):
                document_http = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=settings.documents_base_url,
                        timeout=30.0,
                        follow_redirects=False,
                        limits=httpx.Limits(
                            max_connections=5, max_keepalive_connections=5
                        ),
                    )
                )
                app.state.documents_client = DocumentClient(
                    document_http, settings.documents_service_token
                )
            if (
                app.state.billing_client is None
                and settings.billing_base_url
                and settings.billing_service_token
            ):
                billing_http = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=settings.billing_base_url,
                        timeout=60.0,
                        follow_redirects=False,
                        limits=httpx.Limits(
                            max_connections=10, max_keepalive_connections=5
                        ),
                    )
                )
                app.state.billing_client = BillingClient(
                    billing_http, settings.billing_service_token
                )
            if (
                app.state.pen_client is None
                and settings.pen_base_url
                and settings.pen_service_token
            ):
                pen_http = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=settings.pen_base_url,
                        timeout=5.0,
                        follow_redirects=False,
                    )
                )
                app.state.pen_client = PenClient(pen_http, settings.pen_service_token)
            if (
                app.state.analytics_client is None
                and settings.analytics_base_url
                and settings.analytics_read_service_token
            ):
                client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=settings.analytics_base_url,
                        timeout=10.0,
                        follow_redirects=False,
                    )
                )
                app.state.analytics_client = AnalyticsClient(
                    client, settings.analytics_read_service_token
                )
            if app.state.journal_client is None and all(
                (settings.journal_base_url, settings.journal_read_service_token)
            ):
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=settings.journal_base_url,
                        timeout=5.0,
                        follow_redirects=False,
                    )
                )
                app.state.journal_client = JournalClient(
                    http_client, settings.journal_read_service_token
                )
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
            if app.state.homework_file_client is None and all(
                (settings.homework_base_url, settings.homework_service_token)
            ):
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=settings.homework_base_url,
                        timeout=httpx.Timeout(
                            connect=5.0, read=120.0, write=120.0, pool=5.0
                        ),
                        limits=httpx.Limits(
                            max_connections=4, max_keepalive_connections=4
                        ),
                        follow_redirects=False,
                    )
                )
                app.state.homework_file_client = HomeworkFileClient(
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
        app.state.homework_file_client = app.state.injected_homework_file_client
        app.state.schedule_client = app.state.injected_schedule_client
        app.state.journal_client = app.state.injected_journal_client
        app.state.analytics_client = app.state.injected_analytics_client
        app.state.pen_client = app.state.injected_pen_client
        app.state.billing_client = app.state.injected_billing_client
        app.state.documents_client = app.state.injected_documents_client
        app.state.notifications_client = app.state.injected_notifications_client
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
    homework_file_client: HomeworkFileClient | None = None,
    journal_client: JournalClient | None = None,
    analytics_client: AnalyticsClient | None = None,
    pen_client: PenClient | None = None,
    billing_client: BillingClient | None = None,
    documents_client: DocumentClient | None = None,
    notifications_client: NotificationClient | None = None,
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
        homework_file_client: Подмена отдельного потокового клиента Homework.
        journal_client: Подмена клиента с ограниченными read-правами Journal.
        analytics_client: Подмена клиента общего аудита и отчёта.
        pen_client: Подмена закрытого хранилища штрихов.
        billing_client: Подмена закрытого API тестовых платежей.
        documents_client: Подмена закрытой генерации и чтения учебных PDF.
        notifications_client: Подмена личных уведомлений и отметок прочтения.

    Returns:
        Приложение FastAPI с маршрутами и зависимостями в app.state.
    """
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    @app.exception_handler(HomeworkRequestError)
    async def handle_homework_error(request: Request, exc: HomeworkRequestError):
        """Сохраняет только известные машинные коды отказа файлового владельца.

        Args:
            request: Запрос с назначенным Gateway request_id.
            exc: Проверенный отказ клиента Homework, без сырого сообщения сервиса.

        Returns:
            Единый JSON с известным кодом либо безопасный503 для неизвестного.
        """
        messages = {
            (403, "access_denied"): "Access denied",
            (404, "homework_not_found"): "Homework not found",
            (409, "homework_file_not_ready"): "Homework file not ready",
            (422, "invalid_homework_file"): "Invalid homework file",
            (404, "homework_answer_not_found"): "Answer not found",
            (409, "homework_answer_conflict"): "Answer state conflict",
            (422, "invalid_homework_answer"): "Invalid answer",
        }
        message = messages.get((exc.status_code, exc.code))
        return _error_response(
            request,
            status_code=exc.status_code if message is not None else 503,
            code=exc.code if message is not None else "service_unavailable",
            message=message or "Service unavailable",
            headers={"Cache-Control": "private, no-store"},
        )

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
            429: "rate_limit_exceeded",
        }
        message = (
            exc.detail
            if isinstance(exc.detail, str) and exc.status_code < 500
            else "Request failed"
        )
        if exc.status_code == 403 and exc.detail == "Tuition payment required":
            codes[403] = "tuition_payment_required"
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
    app.state.login_throttle = LoginThrottle(
        max_failures=settings.login_throttle_max_failures,
        window_seconds=settings.login_throttle_window_seconds,
    )
    app.state.homework_client = homework_client
    app.state.injected_homework_client = homework_client
    app.state.homework_file_client = homework_file_client
    app.state.injected_homework_file_client = homework_file_client
    app.state.schedule_client = schedule_client
    app.state.injected_schedule_client = schedule_client
    app.state.journal_client = journal_client
    app.state.injected_journal_client = journal_client
    app.state.analytics_client = analytics_client
    app.state.injected_analytics_client = analytics_client
    app.state.pen_client = pen_client
    app.state.injected_pen_client = pen_client
    app.state.billing_client = billing_client
    app.state.injected_billing_client = billing_client
    app.state.documents_client = documents_client
    app.state.injected_documents_client = documents_client
    app.state.notifications_client = notifications_client
    app.state.injected_notifications_client = notifications_client

    return app
