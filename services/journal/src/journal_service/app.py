import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from journal_service.api.add_student import router as add_student_router
from journal_service.api.class_periods import router as class_periods_router
from journal_service.api.classes import router
from journal_service.api.health import router as health_router
from journal_service.api.homework_reads import router as homework_reads_router
from journal_service.api.period_changes import router as period_changes_router
from journal_service.api.teacher_classes import router as teacher_classes_router
from journal_service.application.ports.errors import (
    ClassNotFoundError,
    CurrentPeriodNotFoundError,
    DuplicateClassError,
    InvalidClassDataError,
    InvalidClassPeriodQueryError,
    InvalidStudentError,
    InvalidTeacherError,
    StudentClassConflictError,
    StudentClassPeriodConflictError,
    StudentNotFoundError,
    TeacherNotFoundError,
    UserLookupUnavailableError,
)
from journal_service.application.ports.gateway_user_reader import GatewayUserReader
from journal_service.application.ports.unit_of_work import UnitOfWork
from journal_service.config import JournalSettings
from journal_service.infrastructure.gateway_user_reader import HttpGatewayUserReader

logger = logging.getLogger(__name__)


def create_app(
    settings: JournalSettings,
    uow_factory: Callable[[], UnitOfWork],
    *,
    readiness_check: Callable[[], Awaitable[None]] | None = None,
    close_resources: Callable[[], Awaitable[None]] | None = None,
    gateway_user_reader: GatewayUserReader | None = None,
) -> FastAPI:
    """Собирает HTTP-приложение Journal из переданных зависимостей.

    Args:
        settings: Настройки текущего сервиса.
        uow_factory: Фабрика отдельного Unit of Work для прикладного сценария.
        readiness_check: Проверка подключения к базе; без неё ready возвращает 503.
        close_resources: Освобождение ресурсов при остановке приложения.
        gateway_user_reader: Внешний reader для внедрения; приложение его не закрывает.

    Returns:
        Приложение с внутренними маршрутами и зависимостями в app.state.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Создаёт принадлежащий приложению клиент и всегда освобождает ресурсы.

        Args:
            app: Приложение, чей жизненный цикл обслуживает контекст.

        Yields:
            Управление HTTP-серверу на время обработки запросов.
        """
        client: httpx.AsyncClient | None = None
        try:
            if (
                gateway_user_reader is None
                and settings.gateway_base_url
                and settings.gateway_service_token
            ):
                client = httpx.AsyncClient(
                    base_url=settings.gateway_base_url,
                    timeout=5.0,
                    follow_redirects=False,
                )
                app.state.gateway_user_reader = HttpGatewayUserReader(
                    client, settings.gateway_service_token
                )
            yield
        finally:
            try:
                if client is not None:
                    app.state.gateway_user_reader = None
                    await client.aclose()
            finally:
                if close_resources is not None:
                    await close_resources()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    @app.middleware("http")
    async def assign_request_id(request: Request, call_next):
        """Назначает запросу ID и добавляет его в полученный ответ.

        Args:
            request: Текущий HTTP-запрос.
            call_next: Следующий обработчик запроса в приложении.

        Returns:
            Ответ приложения с единственным заголовком X-Request-ID.
        """
        request_id = str(uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.state.settings = settings
    app.state.uow_factory = uow_factory
    app.state.readiness_check = readiness_check
    app.state.gateway_user_reader = gateway_user_reader

    app.include_router(router)
    app.include_router(class_periods_router)
    app.include_router(add_student_router)
    app.include_router(period_changes_router)
    app.include_router(teacher_classes_router)
    app.include_router(homework_reads_router)
    app.include_router(health_router)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        """Приводит HTTP-ошибку к единому формату, сохраняя её заголовки.

        Args:
            request: Текущий запрос с назначенным request_id.
            exc: HTTP-ошибка маршрута или зависимости.

        Returns:
            JSON-ответ без внутренних подробностей серверной ошибки.
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
            request=request,
            status_code=exc.status_code,
            code=codes.get(exc.status_code, "http_error"),
            message=message,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Возвращает единый ответ валидации без исходных данных запроса.

        Args:
            request: Текущий запрос с назначенным request_id.
            exc: Ошибка проверки параметров или тела запроса.

        Returns:
            Ответ 422 с безопасным общим сообщением.
        """
        return _error_response(
            request=request,
            status_code=422,
            code="validation_error",
            message="Invalid request data",
        )

    @app.exception_handler(DuplicateClassError)
    async def handle_duplicate_class_error(
        request: Request,
        exc: DuplicateClassError,
    ) -> JSONResponse:
        """Сообщает о конфликте с уже существующим классом.

        Args:
            request: Текущий запрос с назначенным request_id.
            exc: Ошибка повторного создания класса в том же учебном году.

        Returns:
            Ответ 409 без внутренних подробностей исключения.
        """
        return _error_response(
            request,
            status_code=409,
            code="conflict",
            message="Class already exists",
        )

    @app.exception_handler(InvalidClassDataError)
    async def handle_invalid_class_data_error(
        request: Request,
        exc: InvalidClassDataError,
    ) -> JSONResponse:
        """Сообщает о нарушении прикладных правил для данных класса.

        Args:
            request: Текущий запрос с назначенным request_id.
            exc: Ошибка проверки данных класса или параметров списка.

        Returns:
            Ответ 422 с безопасным общим сообщением.
        """
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Invalid class data",
        )

    @app.exception_handler(ClassNotFoundError)
    @app.exception_handler(CurrentPeriodNotFoundError)
    async def handle_missing_class_resource(
        request: Request,
        exc: ClassNotFoundError | CurrentPeriodNotFoundError,
    ) -> JSONResponse:
        """Сообщает об отсутствии класса или текущего периода без внутренних деталей.

        Args:
            request: Запрос с назначенным request_id.
            exc: Ожидаемая ошибка отсутствующего ресурса.

        Returns:
            Единый JSON-ответ 404.
        """
        message = (
            "Class not found"
            if isinstance(exc, ClassNotFoundError)
            else "Current class period not found"
        )
        return _error_response(
            request, status_code=404, code="not_found", message=message
        )

    @app.exception_handler(InvalidClassPeriodQueryError)
    async def handle_invalid_period_query(
        request: Request, exc: InvalidClassPeriodQueryError
    ) -> JSONResponse:
        """Сообщает о неверном прикладном запросе чтения периодов.

        Args:
            request: Запрос с назначенным request_id.
            exc: Ожидаемая ошибка ID или параметров страницы.

        Returns:
            Безопасный JSON-ответ 422.
        """
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Invalid class period query",
        )

    @app.exception_handler(TeacherNotFoundError)
    @app.exception_handler(InvalidTeacherError)
    @app.exception_handler(StudentNotFoundError)
    @app.exception_handler(InvalidStudentError)
    @app.exception_handler(StudentClassConflictError)
    @app.exception_handler(StudentClassPeriodConflictError)
    @app.exception_handler(UserLookupUnavailableError)
    async def handle_add_student_error(
        request: Request,
        exc: StudentNotFoundError
        | TeacherNotFoundError
        | InvalidTeacherError
        | InvalidStudentError
        | StudentClassConflictError
        | StudentClassPeriodConflictError
        | UserLookupUnavailableError,
    ) -> JSONResponse:
        """Отображает ожидаемые ошибки назначения в безопасный HTTP-контракт.

        Args:
            request: Запрос с назначенным request_id.
            exc: Прикладная ошибка проверки ученика или текущего класса.

        Returns:
            Ошибка 404, 422, 409 или 503 без внутренних деталей.
        """
        if isinstance(exc, TeacherNotFoundError):
            status_code, code, message = 404, "not_found", "Teacher not found"
        elif isinstance(exc, InvalidTeacherError):
            status_code, code, message = (
                422,
                "validation_error",
                "User must be an active teacher",
            )
        elif isinstance(exc, StudentNotFoundError):
            status_code, code, message = 404, "not_found", "Student not found"
        elif isinstance(exc, InvalidStudentError):
            status_code, code, message = (
                422,
                "validation_error",
                "User must be an active student",
            )
        elif isinstance(exc, StudentClassPeriodConflictError):
            status_code, code, message = 409, "conflict", "Student class period changed"
        elif isinstance(exc, StudentClassConflictError):
            status_code, code, message = 409, "conflict", "Student class conflict"
        else:
            status_code, code, message = (
                503,
                "service_unavailable",
                "Gateway user lookup unavailable",
            )
        return _error_response(
            request, status_code=status_code, code=code, message=message
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Записывает неожиданную ошибку в лог и скрывает детали от клиента.

        Args:
            request: Текущий запрос с назначенным request_id.
            exc: Непредвиденная ошибка выполнения запроса.

        Returns:
            Ответ 500 с безопасным сообщением и ID для поиска ошибки в логах.
        """
        request_id = request.state.request_id
        logger.error(
            "Unhandled Journal error request_id=%s",
            request_id,
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"request_id": request_id},
        )
        return _error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Internal server error",
        )

    return app


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Собирает единый JSON-ответ ошибки с ID текущего запроса.

    Args:
        request: Запрос с назначенным request_id в состоянии.
        status_code: HTTP-статус ответа.
        code: Машиночитаемое обозначение ошибки.
        message: Безопасное описание ошибки для клиента.
        headers: Дополнительные заголовки исходной ошибки.

    Returns:
        Ответ с кодом, сообщением и одинаковым request_id в JSON и заголовке.
    """
    request_id = request.state.request_id
    return JSONResponse(
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        status_code=status_code,
        headers={**(headers or {}), "X-Request-ID": request_id},
    )
