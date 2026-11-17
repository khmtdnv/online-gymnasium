"""Служебный доступ и сборка сценария создания ДЗ."""

import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from homework_service.api.errors import HomeworkHTTPError, unavailable
from homework_service.application.homework import CreateHomeworkHandler

service_bearer = HTTPBearer(auto_error=False)


def require_gateway(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(service_bearer)
    ],
) -> None:
    """Разрешает доверенный контекст только аутентифицированному Gateway.

    Args:
        request: Запрос с настройками сервиса.
        credentials: Служебный Bearer, не JWT преподавателя.

    Raises:
        HomeworkHTTPError: Интеграция не настроена или секрет не подходит.
    """
    expected = request.app.state.settings.gateway_service_token
    if not expected:
        raise unavailable()
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HomeworkHTTPError(
            401, "invalid_service_credentials", "Invalid service credentials"
        )


def get_create_homework_handler(request: Request) -> CreateHomeworkHandler:
    """Возвращает сценарий либо закрывает ненастроенное создание с 503.

    Args:
        request: Запрос с зависимостями процесса.

    Returns:
        Обработчик с отдельной транзакцией на каждый вызов.

    Raises:
        HomeworkHTTPError: Не настроены зависимости создания.
    """
    handler = request.app.state.create_homework_handler
    if handler is None:
        raise unavailable()
    return handler
